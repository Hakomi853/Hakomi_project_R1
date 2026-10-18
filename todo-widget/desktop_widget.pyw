# -*- coding: utf-8 -*-
"""每日待办 · 桌面悬浮挂件（增强版）

功能：
1. 无边框、置顶、可拖动；闲置自动贴边隐藏，鼠标移到屏幕边缘唤出。
2. 任务类型：每日 / 一次性 / 每周 / 自定义周期（内置日历选日期或星期）。
3. 每项任务可设每日提醒时间，到点桌面右下角弹窗 + 全局提示音。
4. 打卡方式：一次性打钩 / 自定义输入（如"输入完成时间："）。
5. 保存每次打卡记录，历史记录支持「日历检索」与「项目总览」两种查看。
"""
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox
import json
import os
import sys
import random
import datetime
import calendar
import math
import struct
import wave
import ctypes
import winreg
import queue
import threading
from ctypes import wintypes

try:
    import winsound
except ImportError:
    winsound = None


def enable_dpi_awareness():
    """开启高分屏 DPI 感知，让字体与窗口渲染清晰（须在创建 Tk 之前调用）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def refresh_todo_icon():
    """按当天日期重新生成桌面图标，并刷新 Windows 图标缓存。

    仅在日期变化时重新生成（用 .icon_date 记录上次生成日期），避免每次启动都刷。
    """
    try:
        marker = os.path.join(BASE, '.icon_date')
        today = datetime.date.today().isoformat()
        if os.path.exists(marker):
            with open(marker, 'r', encoding='utf-8') as f:
                if f.read().strip() == today:
                    return
        import importlib.util
        spec = importlib.util.spec_from_file_location('gen_icon', os.path.join(BASE, 'gen_icon.py'))
        gen_icon = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen_icon)
        gen_icon.write_ico([256, 48, 32, 16])
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(today)
        # 通知资源管理器刷新图标缓存
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
        except Exception:
            pass
    except Exception:
        pass


# ---------- 开机自启（注册表 Run 键） ----------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "每日待办"


def _pythonw_path():
    exe = sys.executable
    if not exe.lower().endswith('pythonw.exe'):
        exe = exe.replace('python.exe', 'pythonw.exe')
    return exe


def startup_command():
    pyw = os.path.join(BASE, 'desktop_widget.pyw')
    return '"%s" "%s"' % (_pythonw_path(), pyw)


def set_startup(enabled):
    """设置/取消开机自启。返回是否成功。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def is_startup_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ---------- 单实例（命名互斥体 + 命名事件唤起） ----------
MUTEX_NAME = 'TodoWidget_SingleInstance_Mutex'
EVENT_NAME = 'TodoWidget_WakeEvent'
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance():
    """尝试获取单实例锁。返回 (是否首个实例, 唤起事件句柄或 None)。"""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.GetLastError.restype = wintypes.DWORD
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        already = kernel32.GetLastError() == ERROR_ALREADY_EXISTS
        if already:
            return False, None
        kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        wake = kernel32.CreateEventW(None, True, False, EVENT_NAME)  # 手动重置，初始未触发
        return True, wake
    except Exception:
        return True, None


def wake_existing_instance():
    """唤起已运行的实例。"""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.OpenEventW.restype = wintypes.HANDLE
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.SetEvent.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        ev = kernel32.OpenEventW(0x0002, False, EVENT_NAME)  # EVENT_MODIFY_STATE
        if ev:
            kernel32.SetEvent(ev)
            kernel32.CloseHandle(ev)
    except Exception:
        pass


def apply_rounded(window, radius=18):
    """给无边框窗口设置圆角（Windows GDI 区域）。"""
    try:
        hwnd = window.winfo_id()
        w = window.winfo_width()
        h = window.winfo_height()
        if w < 10 or h < 10:
            return
        rgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius, radius)
        ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)
    except Exception:
        pass


# ================= 系统托盘图标 =================
class TrayIcon:
    """系统托盘图标（ctypes 实现，独立线程消息循环，事件通过队列回传主线程）。"""
    WM_TRAY = 0x8000 + 1
    WM_COMMAND = 0x0111
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    NIM_ADD = 0x00
    NIM_DELETE = 0x02
    NIF_MESSAGE = 0x01
    NIF_ICON = 0x02
    NIF_TIP = 0x04
    ID_SHOW = 1001
    ID_QUIT = 1002
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010

    def __init__(self, icon_path, tooltip, on_show, on_quit):
        self._icon_path = icon_path
        self._tooltip = tooltip
        self._on_show = on_show
        self._on_quit = on_quit
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        # 设置 API 签名（64 位下防止句柄截断）
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadIconW.restype = wintypes.HICON
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
        user32.AppendMenuW.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                          ctypes.c_int, wintypes.HWND, wintypes.LPRECT]
        user32.TrackPopupMenu.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        # 图标
        hicon = user32.LoadImageW(None, self._icon_path, self.IMAGE_ICON, 0, 0, self.LR_LOADFROMFILE)
        if not hicon:
            hicon = user32.LoadIconW(None, 32512)  # IDI_APPLICATION

        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                                     ctypes.c_size_t, ctypes.c_ssize_t)

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == self.WM_TRAY:
                if lparam == self.WM_LBUTTONDBLCLK:
                    self._q.put(('show',))
                elif lparam == self.WM_RBUTTONUP:
                    menu = user32.CreatePopupMenu()
                    user32.AppendMenuW(menu, 0x0000, self.ID_SHOW, '显示挂件')
                    user32.AppendMenuW(menu, 0x0000, self.ID_QUIT, '退出')
                    pt = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    user32.SetForegroundWindow(hwnd)
                    user32.TrackPopupMenu(menu, 0x0000, pt.x, pt.y, 0, hwnd, None)
                    user32.PostMessageW(hwnd, 0, 0, 0)
                    user32.DestroyMenu(menu)
                return 0
            if msg == self.WM_COMMAND:
                cmd = wparam & 0xFFFF
                if cmd == self.ID_SHOW:
                    self._q.put(('show',))
                elif cmd == self.ID_QUIT:
                    self._q.put(('quit',))
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ('style', wintypes.UINT),
                ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HANDLE),
                ('hbrBackground', wintypes.HBRUSH),
                ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR),
            ]
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                           wintypes.HINSTANCE, wintypes.LPVOID]
        user32.CreateWindowExW.restype = wintypes.HWND

        hinst = kernel32.GetModuleHandleW(None)
        cls_name = 'TodoWidgetTrayClass'
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        wc.hIcon = hicon
        user32.RegisterClassW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(0, cls_name, cls_name, 0, 0, 0, 0, 0,
                                      None, None, hinst, None)
        if not hwnd:
            return

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ('cbSize', wintypes.DWORD),
                ('hWnd', wintypes.HWND),
                ('uID', wintypes.UINT),
                ('uFlags', wintypes.UINT),
                ('uCallbackMessage', wintypes.UINT),
                ('hIcon', wintypes.HICON),
                ('szTip', wintypes.WCHAR * 128),
                ('dwState', wintypes.DWORD),
                ('dwStateMask', wintypes.DWORD),
                ('szInfo', wintypes.WCHAR * 256),
                ('uVersion', wintypes.UINT),
                ('szInfoTitle', wintypes.WCHAR * 64),
                ('dwInfoFlags', wintypes.DWORD),
                ('guidItem', ctypes.c_byte * 16),
                ('hBalloonIcon', wintypes.HICON),
            ]
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = self.NIF_MESSAGE | self.NIF_ICON | self.NIF_TIP
        nid.uCallbackMessage = self.WM_TRAY
        nid.hIcon = hicon
        nid.szTip = self._tooltip
        shell32.Shell_NotifyIconW(self.NIM_ADD, ctypes.byref(nid))

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        shell32.Shell_NotifyIconW(self.NIM_DELETE, ctypes.byref(nid))
        user32.DestroyWindow(hwnd)

    def poll(self):
        try:
            return self._q.get_nowait()
        except queue.Empty:
            return None


def is_foreground_fullscreen(exclude_hwnd=None, fg_hwnd=None):
    """检测前台窗口是否为全屏应用（排除桌面与自身窗口）。"""
    try:
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = fg_hwnd if fg_hwnd else user32.GetForegroundWindow()
        if not hwnd:
            return False
        if exclude_hwnd is not None and hwnd == exclude_hwnd:
            return False
        # 排除桌面窗口（Progman / WorkerW）
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        if buf.value.lower() in ('progman', 'workerw'):
            return False
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        sw = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        sh = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        return w >= sw - 2 and h >= sh - 2
    except Exception:
        return False


BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'todo_data.json')
PROMPT_WAV = os.path.join(BASE, 'prompt.wav')


# ---------- 配色 ----------
BG      = '#f4f6fb'
CARD    = '#ffffff'
TEXT    = '#1f2430'
SUB     = '#8a93a6'
ACCENT  = '#5b6cff'
ACCENT2 = '#8a5bff'
SUCCESS = '#23c16b'
DANGER  = '#ff5d73'
LINE    = '#eceef4'
HEADER  = '#5b6cff'

TYPE_META = {
    'daily':  {'label': '每日', 'icon': '↻', 'color': '#5b6cff'},
    'once':   {'label': '一次性', 'icon': '①', 'color': '#f0a020'},
    'weekly': {'label': '每周', 'icon': 'W', 'color': '#23c16b'},
    'custom': {'label': '周期', 'icon': '⟳', 'color': '#8a5bff'},
}

FONT_TITLE = ('Microsoft YaHei UI', 11, 'bold')
FONT_TEXT  = ('Microsoft YaHei UI', 10)
FONT_SMALL = ('Microsoft YaHei UI', 9)
FONT_SUB   = ('Microsoft YaHei UI', 8)

WEEK_CN = ['一', '二', '三', '四', '五', '六', '日']
WEEK_FULL = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
WEEKDAY_MAP = {name: i for i, name in enumerate(WEEK_FULL)}


# ================= 工具函数 =================
def today():
    return datetime.date.today()


def today_iso():
    return today().isoformat()


def gen_id():
    return datetime.datetime.now().strftime('%Y%m%d%H%M%S%f') + str(random.randint(10, 99))


def load_all():
    if os.path.exists(DATA):
        try:
            with open(DATA, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if isinstance(d, dict):
                d.setdefault('tasks', [])
                d.setdefault('records', [])
                return d
        except Exception:
            pass
    return {'tasks': [], 'records': []}


def save_all(data):
    try:
        with open(DATA, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------- 周期判断 ----------
def cycle_range(d, reset_weekday=0):
    """以 reset_weekday（0=周一 ... 6=周日）为周期起始日，返回 d 所在周期的起止 iso"""
    offset = (d.weekday() - reset_weekday) % 7
    start = d - datetime.timedelta(days=offset)
    end = start + datetime.timedelta(days=6)
    return start.isoformat(), end.isoformat()


def should_do_on(task, d):
    """判断任务在某天是否应执行。d 为 datetime.date"""
    t = task.get('type', 'daily')
    if t == 'daily':
        return True
    if t == 'once':
        return task.get('date') == d.isoformat()
    if t == 'weekly':
        mode = task.get('weekly_mode', 'days')
        if mode == 'once':
            return True      # 一周内任意一天都出现，完成一次即可
        if mode == 'range':
            # 自定义期限：仅在一周内指定的可完成日期（星期）出现
            return d.weekday() in set(task.get('available_weekdays', []))
        # 默认 days：每周指定星期几
        return d.weekday() in set(task.get('weekdays', []))
    if t == 'custom':
        start = task.get('start_date')
        if not start:
            return False
        try:
            sd = datetime.date.fromisoformat(start)
        except Exception:
            return False
        if d < sd:
            return False
        interval = int(task.get('interval_days', 1) or 1)
        if interval < 1:
            interval = 1
        return (d - sd).days % interval == 0
    return False


def tasks_for_date(tasks, d):
    """返回某天应执行的、未删除的任务"""
    return [t for t in tasks if t.get('active', True) and should_do_on(t, d)]


def get_record(records, task_id, date_iso):
    for r in records:
        if r['task_id'] == task_id and r['date'] == date_iso:
            return r
    return None


def cycle_records(records, task_id, d, reset_weekday=0):
    """返回任务在 d 所在周期内（以 reset_weekday 为起始）的所有打卡记录"""
    s, e = cycle_range(d, reset_weekday)
    return [r for r in records if r['task_id'] == task_id and s <= r['date'] <= e]


def is_done(task, records, d):
    """判断任务在 d 当天是否已完成（每周完成一次类按「以重置日为起始的周期」计）"""
    if task.get('type') == 'weekly' and task.get('weekly_mode') in ('once', 'range'):
        return bool(cycle_records(records, task['id'], d, task.get('reset_weekday', 0)))
    return get_record(records, task['id'], d.isoformat()) is not None


def find_task(tasks, task_id):
    for t in tasks:
        if t['id'] == task_id:
            return t
    return None


# ---------- 提示音 ----------
def ensure_prompt_wav():
    if os.path.exists(PROMPT_WAV):
        return PROMPT_WAV
    try:
        rate = 22050
        frames = []
        for _ in range(2):
            for freq in (880, 1175):
                n = int(rate * 0.16)
                for i in range(n):
                    t = i / rate
                    env = (n - i) / n
                    v = int(0.5 * 32767 * env * math.sin(2 * math.pi * freq * t))
                    frames.append(v)
        with wave.open(PROMPT_WAV, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(b''.join(struct.pack('<h', v) for v in frames))
        return PROMPT_WAV
    except Exception:
        return None


def play_sound():
    if winsound is None:
        return
    try:
        path = ensure_prompt_wav()
        if path:
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


# ================= 日历控件 =================
class CalendarWidget(tk.Frame):
    """日历控件：mode='single' 单选日期；mode='weekday' 多选星期"""

    def __init__(self, master, mode='single', on_change=None, **kw):
        super().__init__(master, **kw)
        self.mode = mode
        self.on_change = on_change
        self.year = today().year
        self.month = today().month
        self.selected_date = today_iso()      # single 模式
        self.selected_weekdays = set()        # weekday 模式，0=周一
        self._build()

    def _build(self):
        self.head = tk.Frame(self, bg=self['bg'])
        self.head.pack(fill='x')

        tk.Button(self.head, text='◀', bd=0, bg=self['bg'], fg=ACCENT, font=FONT_SMALL,
                  cursor='hand2', command=self._prev).pack(side='left', padx=4)
        self.title = tk.Label(self.head, text='', bg=self['bg'], fg=TEXT, font=FONT_TEXT)
        self.title.pack(side='left', expand=True)
        tk.Button(self.head, text='▶', bd=0, bg=self['bg'], fg=ACCENT, font=FONT_SMALL,
                  cursor='hand2', command=self._next).pack(side='right', padx=4)

        # 星期表头
        self.grid = tk.Frame(self, bg=self['bg'])
        self.grid.pack(fill='both', expand=True)
        for i, w in enumerate(WEEK_CN):
            tk.Label(self.grid, text=w, bg=self['bg'], fg=SUB, font=FONT_SUB, width=3)\
                .grid(row=0, column=i, padx=1, pady=2)
        self._render()

    def _prev(self):
        self.month -= 1
        if self.month < 1:
            self.month = 12
            self.year -= 1
        self._render()

    def _next(self):
        self.month += 1
        if self.month > 12:
            self.month = 1
            self.year += 1
        self._render()

    def _render(self):
        self.title.config(text='%d年 %d月' % (self.year, self.month))
        for w in self.grid.winfo_children():
            if int(w.grid_info().get('row', 0)) > 0:
                w.destroy()

        first_wd = datetime.date(self.year, self.month, 1).weekday()  # 周一=0
        days = calendar.monthrange(self.year, self.month)[1]

        row = 1
        col = first_wd
        for day in range(1, days + 1):
            d = datetime.date(self.year, self.month, day)
            iso = d.isoformat()
            is_today = iso == today_iso()

            bg = self['bg']
            fg = TEXT
            if self.mode == 'single' and iso == self.selected_date:
                bg, fg = ACCENT, 'white'
            elif self.mode == 'weekday' and d.weekday() in self.selected_weekdays:
                bg, fg = ACCENT2, 'white'
            elif is_today:
                bg, fg = '#e7ebff', ACCENT

            lbl = tk.Label(self.grid, text=str(day), bg=bg, fg=fg, font=FONT_SMALL, width=3,
                           cursor='hand2')
            lbl.grid(row=row, column=col, padx=1, pady=1)
            lbl.bind('<Button-1>', lambda e, iso=iso, d=d: self._pick(iso, d))
            col += 1
            if col > 6:
                col = 0
                row += 1

    def _pick(self, iso, d):
        if self.mode == 'single':
            self.selected_date = iso
        else:
            wd = d.weekday()
            if wd in self.selected_weekdays:
                self.selected_weekdays.discard(wd)
            else:
                self.selected_weekdays.add(wd)
        self._render()
        if self.on_change:
            self.on_change()


# ================= 提醒弹窗 =================
class ReminderPopup(tk.Toplevel):
    def __init__(self, task, on_checkin, on_later):
        super().__init__()
        self.task = task
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg=CARD)

        w, h = 300, 130
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry('%dx%d+%d+%d' % (w, h, sw - w - 24, sh - h - 70))

        tk.Label(self, text='⏰ 待办提醒', bg=CARD, fg=ACCENT, font=FONT_TITLE)\
            .pack(anchor='w', padx=16, pady=(14, 2))
        tk.Label(self, text=task['text'], bg=CARD, fg=TEXT, font=FONT_TEXT, wraplength=268,
                 justify='left').pack(anchor='w', padx=16)
        sub = '提醒时间 %s' % task.get('remind_time', '')
        tk.Label(self, text=sub, bg=CARD, fg=SUB, font=FONT_SUB)\
            .pack(anchor='w', padx=16, pady=(2, 8))

        bar = tk.Frame(self, bg=CARD)
        bar.pack(fill='x', padx=12)
        tk.Button(bar, text='去打卡', bg=ACCENT, fg='white', bd=0, font=FONT_SMALL,
                  activebackground=ACCENT2, activeforeground='white', cursor='hand2',
                  command=lambda: (on_checkin(), self.destroy())).pack(side='left', padx=6, ipadx=10, ipady=4)
        tk.Button(bar, text='稍后', bg='#eef0f7', fg=TEXT, bd=0, font=FONT_SMALL,
                  activebackground=LINE, cursor='hand2',
                  command=lambda: (on_later(), self.destroy())).pack(side='left', padx=6, ipadx=10, ipady=4)

        self.lift()
        self.after(60000, self._auto_close)  # 1 分钟自动关闭

    def _auto_close(self):
        try:
            self.destroy()
        except Exception:
            pass


# ================= 自定义输入打卡弹窗 =================
class CheckinDialog(tk.Toplevel):
    def __init__(self, task, on_submit):
        super().__init__()
        self.task = task
        self.on_submit = on_submit
        self.title('打卡')
        self.configure(bg=CARD)
        self.resizable(False, False)

        w, h = 320, 160
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry('%dx%d+%d+%d' % (w, h, (sw - w) // 2, (sh - h) // 2 - 60))
        self.transient(self.master)

        prompt = task.get('check_prompt') or '请输入内容：'
        tk.Label(self, text=task['text'], bg=CARD, fg=TEXT, font=FONT_TITLE, wraplength=280,
                 justify='left').pack(anchor='w', padx=16, pady=(14, 2))
        tk.Label(self, text=prompt, bg=CARD, fg=ACCENT, font=FONT_SMALL)\
            .pack(anchor='w', padx=16, pady=(0, 6))

        self.entry = tk.Entry(self, font=FONT_TEXT, relief='flat', bg='#f2f4fa', fg=TEXT,
                              insertbackground=TEXT)
        self.entry.pack(fill='x', padx=16, ipady=6)
        self.entry.focus_set()
        self.entry.bind('<Return>', lambda e: self._ok())

        bar = tk.Frame(self, bg=CARD)
        bar.pack(fill='x', padx=16, pady=12)
        tk.Button(bar, text='确定打卡', bg=ACCENT, fg='white', bd=0, font=FONT_SMALL,
                  activebackground=ACCENT2, activeforeground='white', cursor='hand2',
                  command=self._ok).pack(side='right', ipadx=12, ipady=4)
        tk.Button(bar, text='取消', bg='#eef0f7', fg=TEXT, bd=0, font=FONT_SMALL,
                  activebackground=LINE, cursor='hand2', command=self.destroy)\
            .pack(side='right', padx=6, ipadx=12, ipady=4)

    def _ok(self):
        val = self.entry.get().strip()
        if not val:
            return
        self.on_submit(val)
        self.destroy()


# ================= 添加任务对话框 =================
class AddTaskDialog(tk.Toplevel):
    def __init__(self, master, on_save, edit_task=None):
        super().__init__(master)
        self.on_save = on_save
        self.edit_task = edit_task
        self.title('编辑待办' if edit_task else '添加待办')
        self.configure(bg=CARD)
        self.resizable(False, False)

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = 360
        h = min(sh - 120, 720)
        self.geometry('%dx%d+%d+%d' % (w, h, (sw - w) // 2, (sh - h) // 2 - 30))
        self.transient(master)

        self.type_var = tk.StringVar(value='daily')
        self.check_var = tk.StringVar(value='checkbox')
        self.remind_var = tk.BooleanVar(value=False)
        self.weekly_mode_var = tk.StringVar(value='days')
        self.reset_weekday_var = tk.StringVar(value='周一')

        self._build()
        if edit_task:
            self._prefill(edit_task)

    def _label(self, text):
        tk.Label(self.content, text=text, bg=CARD, fg=SUB, font=FONT_SMALL, anchor='w')\
            .pack(fill='x', padx=16, pady=(10, 2))

    def _build(self):
        # 底部按钮栏（固定，不滚动）
        bar = tk.Frame(self, bg=CARD)
        bar.pack(side='bottom', fill='x', padx=16, pady=12)
        tk.Button(bar, text='保存', bg=ACCENT, fg='white', bd=0, font=FONT_TEXT,
                  activebackground=ACCENT2, activeforeground='white', cursor='hand2',
                  command=self._save).pack(side='right', ipadx=16, ipady=5)
        tk.Button(bar, text='取消', bg='#eef0f7', fg=TEXT, bd=0, font=FONT_TEXT,
                  activebackground=LINE, cursor='hand2', command=self.destroy)\
            .pack(side='right', padx=6, ipadx=16, ipady=5)

        # 滚动容器
        wrap = tk.Frame(self, bg=CARD)
        wrap.pack(side='top', fill='both', expand=True)
        self.canvas = tk.Canvas(wrap, bg=CARD, highlightthickness=0, bd=0)
        self.sb = tk.Scrollbar(wrap, orient='vertical', command=self.canvas.yview, width=8)
        self.content = tk.Frame(self.canvas, bg=CARD)
        self.content.bind('<Configure>',
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.sb.pack(side='right', fill='y')
        self.bind('<MouseWheel>', self._scroll)
        self.canvas.bind('<Configure>',
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))

        tk.Label(self.content, text='编辑待办' if self.edit_task else '新增待办', bg=CARD, fg=TEXT, font=FONT_TITLE)\
            .pack(anchor='w', padx=16, pady=(14, 4))

        # 名称
        self._label('任务名称')
        self.name_entry = tk.Entry(self.content, font=FONT_TEXT, relief='flat', bg='#f2f4fa', fg=TEXT,
                                   insertbackground=TEXT)
        self.name_entry.pack(fill='x', padx=16, ipady=6)

        # 类型
        self._label('任务类型')
        type_frame = tk.Frame(self.content, bg=CARD)
        type_frame.pack(fill='x', padx=16)
        types = [('daily', '每日'), ('once', '一次性'), ('weekly', '每周'), ('custom', '自定义周期')]
        for key, name in types:
            tk.Radiobutton(type_frame, text=name, value=key, variable=self.type_var, bg=CARD,
                           fg=TEXT, font=FONT_SMALL, activebackground=CARD, activeforeground=ACCENT,
                           selectcolor=CARD, command=self._on_type_change)\
                .pack(side='left', padx=(0, 6))

        # 日期区域
        self._label('执行日期')
        self.date_area = tk.Frame(self.content, bg=CARD)
        self.date_area.pack(fill='x', padx=16)
        self._on_type_change()

        # 提醒
        self._label('每日提醒时间')
        rem_frame = tk.Frame(self.content, bg=CARD)
        rem_frame.pack(fill='x', padx=16)
        tk.Checkbutton(rem_frame, text='开启提醒', variable=self.remind_var, bg=CARD, fg=TEXT,
                       font=FONT_SMALL, activebackground=CARD, selectcolor=CARD,
                       command=self._on_remind_toggle).pack(side='left')
        self.remind_box = tk.Frame(self.content, bg=CARD)
        self.remind_box.pack(fill='x', padx=16)
        self.hour_spin = tk.Spinbox(self.remind_box, from_=0, to=23, width=4, font=FONT_SMALL,
                                    justify='center', bd=0, bg='#f2f4fa', fg=TEXT)
        self.min_spin = tk.Spinbox(self.remind_box, from_=0, to=59, width=4, font=FONT_SMALL,
                                   justify='center', bd=0, bg='#f2f4fa', fg=TEXT)
        self.hour_spin.delete(0, 'end')
        self.hour_spin.insert(0, '9')
        self.min_spin.delete(0, 'end')
        self.min_spin.insert(0, '00')
        self.hour_spin.pack(side='left')
        tk.Label(self.remind_box, text=':', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')
        self.min_spin.pack(side='left')

        # 打卡方式
        self._label('打卡方式')
        check_frame = tk.Frame(self.content, bg=CARD)
        check_frame.pack(fill='x', padx=16)
        tk.Radiobutton(check_frame, text='一次性打钩', value='checkbox', variable=self.check_var,
                       bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                       activeforeground=ACCENT, selectcolor=CARD, command=self._on_check_change)\
            .pack(side='left', padx=(0, 8))
        tk.Radiobutton(check_frame, text='自定义输入', value='text', variable=self.check_var,
                       bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                       activeforeground=ACCENT, selectcolor=CARD, command=self._on_check_change)\
            .pack(side='left')

        self.prompt_label = tk.Label(self.content, text='输入提示词（如：输入完成时间：）', bg=CARD, fg=SUB,
                                     font=FONT_SMALL, anchor='w')
        self.prompt_label.pack(fill='x', padx=16, pady=(8, 0))
        self.prompt_entry = tk.Entry(self.content, font=FONT_TEXT, relief='flat', bg='#f2f4fa', fg=TEXT,
                                     insertbackground=TEXT)
        self.prompt_entry.pack(fill='x', padx=16, ipady=6)
        self.prompt_entry.insert(0, '输入完成时间：')
        self._on_check_change()

    def _scroll(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def _prefill(self, t):
        self.name_entry.insert(0, t.get('text', ''))
        self.type_var.set(t.get('type', 'daily'))
        self._on_type_change()   # 重建日期区控件

        typ = t.get('type', 'daily')
        if typ == 'once' and t.get('date'):
            self.cal.selected_date = t['date']
            self.cal._render()
        elif typ == 'weekly':
            mode = t.get('weekly_mode', 'days')
            self.weekly_mode_var.set(mode)
            self.reset_weekday_var.set(WEEK_FULL[t.get('reset_weekday', 0)])
            self._on_weekly_mode_change()
            if mode == 'days' and t.get('weekdays'):
                self.cal.selected_weekdays = set(t['weekdays'])
                self.cal._render()
            elif mode == 'range' and t.get('available_weekdays'):
                self.cal.selected_weekdays = set(t['available_weekdays'])
                self.cal._render()
        elif typ == 'custom':
            if t.get('start_date'):
                self.cal.selected_date = t['start_date']
                self.cal._render()
            if t.get('interval_days'):
                self.interval_spin.delete(0, 'end')
                self.interval_spin.insert(0, str(t['interval_days']))

        if t.get('remind_enabled'):
            self.remind_var.set(True)
            hm = (t.get('remind_time') or '09:00').split(':')
            self.hour_spin.delete(0, 'end')
            self.hour_spin.insert(0, hm[0])
            self.min_spin.delete(0, 'end')
            self.min_spin.insert(0, hm[1])
            self._on_remind_toggle()

        self.check_var.set(t.get('check_type', 'checkbox'))
        self.prompt_entry.delete(0, 'end')
        self.prompt_entry.insert(0, t.get('check_prompt', '输入完成时间：'))
        self._on_check_change()

    def _clear_date_area(self):
        for c in self.date_area.winfo_children():
            c.destroy()

    def _on_type_change(self):
        self._clear_date_area()
        t = self.type_var.get()
        if t == 'daily':
            tk.Label(self.date_area, text='每天执行', bg=CARD, fg=SUB, font=FONT_SMALL)\
                .pack(anchor='w', pady=4)
        elif t == 'once':
            self.cal = CalendarWidget(self.date_area, mode='single', bg=CARD)
            self.cal.pack(anchor='w')
        elif t == 'weekly':
            mode_frame = tk.Frame(self.date_area, bg=CARD)
            mode_frame.pack(anchor='w', pady=(0, 2))
            for key, name in [('days', '指定星期几'), ('once', '每周完成一次'), ('range', '自定义期限')]:
                tk.Radiobutton(mode_frame, text=name, value=key, variable=self.weekly_mode_var,
                               bg=CARD, fg=TEXT, font=FONT_SMALL, activebackground=CARD,
                               activeforeground=ACCENT, selectcolor=CARD,
                               command=self._on_weekly_mode_change)\
                    .pack(side='left', padx=(0, 4))
            self.weekly_body = tk.Frame(self.date_area, bg=CARD)
            self.weekly_body.pack(anchor='w', fill='x')
            self._on_weekly_mode_change()
        elif t == 'custom':
            tk.Label(self.date_area, text='起始日期', bg=CARD, fg=SUB, font=FONT_SMALL)\
                .pack(anchor='w')
            self.cal = CalendarWidget(self.date_area, mode='single', bg=CARD)
            self.cal.pack(anchor='w')
            row = tk.Frame(self.date_area, bg=CARD)
            row.pack(anchor='w', pady=(4, 2))
            tk.Label(row, text='每', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')
            self.interval_spin = tk.Spinbox(row, from_=1, to=365, width=4, font=FONT_SMALL,
                                            justify='center', bd=0, bg='#f2f4fa', fg=TEXT)
            self.interval_spin.delete(0, 'end')
            self.interval_spin.insert(0, '1')
            self.interval_spin.pack(side='left', padx=4)
            tk.Label(row, text='天一次', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')

    def _on_weekly_mode_change(self):
        for c in self.weekly_body.winfo_children():
            c.destroy()
        mode = self.weekly_mode_var.get()
        if mode == 'days':
            tk.Label(self.weekly_body, text='点选每周要执行的星期（可多选，选中日每天都要打卡）', bg=CARD, fg=SUB,
                     font=FONT_SMALL).pack(anchor='w', pady=(0, 2))
            self.cal = CalendarWidget(self.weekly_body, mode='weekday', bg=CARD)
            self.cal.pack(anchor='w')
        elif mode == 'once':
            row = tk.Frame(self.weekly_body, bg=CARD)
            row.pack(anchor='w', fill='x', pady=6)
            tk.Label(row, text='一周内任意时间完成一次，每周', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')
            self.reset_menu = tk.OptionMenu(row, self.reset_weekday_var, *WEEK_FULL)
            self.reset_menu.config(bg=CARD, fg=TEXT, font=FONT_SMALL, bd=0, activebackground=BG,
                                   highlightthickness=0, cursor='hand2')
            self.reset_menu['menu'].config(font=FONT_SMALL)
            self.reset_menu.pack(side='left', padx=2)
            tk.Label(row, text='重置（新一轮开始）', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')
        elif mode == 'range':
            tk.Label(self.weekly_body, text='点选每周可完成的日期（星期，可多选）', bg=CARD, fg=SUB,
                     font=FONT_SMALL).pack(anchor='w', pady=(0, 2))
            self.cal = CalendarWidget(self.weekly_body, mode='weekday', bg=CARD)
            self.cal.pack(anchor='w')
            row = tk.Frame(self.weekly_body, bg=CARD)
            row.pack(anchor='w', fill='x', pady=(4, 2))
            tk.Label(row, text='每周', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')
            self.reset_menu = tk.OptionMenu(row, self.reset_weekday_var, *WEEK_FULL)
            self.reset_menu.config(bg=CARD, fg=TEXT, font=FONT_SMALL, bd=0, activebackground=BG,
                                   highlightthickness=0, cursor='hand2')
            self.reset_menu['menu'].config(font=FONT_SMALL)
            self.reset_menu.pack(side='left', padx=2)
            tk.Label(row, text='重置（新一轮开始）', bg=CARD, fg=TEXT, font=FONT_SMALL).pack(side='left')

    def _on_remind_toggle(self):
        state = 'normal' if self.remind_var.get() else 'disabled'
        self.hour_spin.config(state=state)
        self.min_spin.config(state=state)

    def _on_check_change(self):
        if self.check_var.get() == 'text':
            self.prompt_label.config(fg=ACCENT)
            self.prompt_entry.config(state='normal')
        else:
            self.prompt_label.config(fg=SUB)
            self.prompt_entry.config(state='disabled')

    def _save(self):
        text = self.name_entry.get().strip()
        if not text:
            self.name_entry.focus_set()
            return
        t = self.type_var.get()
        task = {
            'id': self.edit_task['id'] if self.edit_task else gen_id(),
            'text': text,
            'type': t,
            'check_type': self.check_var.get(),
            'check_prompt': self.prompt_entry.get().strip() or '请输入内容：',
            'remind_enabled': self.remind_var.get(),
            'remind_time': None,
            'active': True,
            'created_at': today_iso(),
        }
        if self.remind_var.get():
            try:
                hh = int(self.hour_spin.get())
                mm = int(self.min_spin.get())
                task['remind_time'] = '%02d:%02d' % (hh % 24, mm % 60)
            except Exception:
                task['remind_time'] = '09:00'
        if t == 'once':
            task['date'] = self.cal.selected_date
        elif t == 'weekly':
            mode = self.weekly_mode_var.get()
            task['weekly_mode'] = mode
            if mode == 'days':
                task['weekdays'] = sorted(self.cal.selected_weekdays) or [today().weekday()]
            elif mode == 'range':
                task['available_weekdays'] = sorted(self.cal.selected_weekdays)
                task['reset_weekday'] = WEEKDAY_MAP.get(self.reset_weekday_var.get(), 0)
            elif mode == 'once':
                task['reset_weekday'] = WEEKDAY_MAP.get(self.reset_weekday_var.get(), 0)
        elif t == 'custom':
            task['start_date'] = self.cal.selected_date
            try:
                task['interval_days'] = int(self.interval_spin.get())
            except Exception:
                task['interval_days'] = 1
        self.on_save(task)
        self.destroy()


# ================= 历史记录窗口 =================
class HistoryWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title('打卡历史')
        self.configure(bg=BG)
        self.geometry('380x560')
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry('+%d+%d' % ((sw - 380) // 2, (sh - 560) // 2 - 30))
        self.transient(master)

        self.tab = 'calendar'  # 'calendar' | 'overview'
        self.sel_date = today_iso()
        self._build()
        self._refresh()

    def _build(self):
        tabs = tk.Frame(self, bg=BG)
        tabs.pack(fill='x', padx=10, pady=8)
        self.cal_btn = tk.Button(tabs, text='📅 日历检索', bg=ACCENT, fg='white', bd=0,
                                 font=FONT_SMALL, activebackground=ACCENT, activeforeground='white',
                                 cursor='hand2', command=lambda: self._switch('calendar'))
        self.cal_btn.pack(side='left', ipadx=14, ipady=6)
        self.ov_btn = tk.Button(tabs, text='📋 项目总览', bg=CARD, fg=TEXT, bd=0, font=FONT_SMALL,
                                activebackground=CARD, cursor='hand2',
                                command=lambda: self._switch('overview'))
        self.ov_btn.pack(side='left', padx=6, ipadx=14, ipady=6)

        # 滚动容器
        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        self.sb = tk.Scrollbar(wrap, orient='vertical', command=self.canvas.yview, width=8)
        self.body = tk.Frame(self.canvas, bg=BG)
        self.body.bind('<Configure>',
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.sb.pack(side='right', fill='y')
        self.bind('<MouseWheel>', self._scroll)
        self.canvas.bind('<Configure>',
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))

    def _scroll(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def _switch(self, tab):
        self.tab = tab
        self.cal_btn.config(bg=ACCENT if tab == 'calendar' else CARD,
                            fg='white' if tab == 'calendar' else TEXT)
        self.ov_btn.config(bg=ACCENT if tab == 'overview' else CARD,
                           fg='white' if tab == 'overview' else TEXT)
        self._refresh()

    def _clear_body(self):
        for c in self.body.winfo_children():
            c.destroy()

    def _refresh(self):
        self._clear_body()
        data = load_all()
        if self.tab == 'calendar':
            self._render_calendar(data)
        else:
            self._render_overview(data)

    def _render_calendar(self, data):
        cal = CalendarWidget(self.body, mode='single', bg=BG,
                             on_change=lambda: self._set_date(cal.selected_date))
        cal.selected_date = self.sel_date
        cal._render()
        cal.pack(fill='x', pady=4)

        # 该日记录
        head = tk.Frame(self.body, bg=BG)
        head.pack(fill='x', pady=(6, 2))
        tk.Label(head, text=self.sel_date + ' 的打卡记录', bg=BG, fg=TEXT, font=FONT_TEXT)\
            .pack(side='left')

        box = tk.Frame(self.body, bg=CARD)
        box.pack(fill='x')

        records = [r for r in data['records'] if r['date'] == self.sel_date]
        if not records:
            tk.Label(box, text='当天暂无打卡记录', bg=CARD, fg=SUB, font=FONT_SMALL)\
                .pack(pady=30)
            return
        for r in records:
            task = find_task(data['tasks'], r['task_id'])
            name = task['text'] if task else '（已删除任务）'
            row = tk.Frame(box, bg=CARD)
            row.pack(fill='x', padx=10, pady=4)
            tk.Label(row, text='●', bg=CARD, fg=SUCCESS, font=FONT_SMALL).pack(side='left', padx=(0, 6))
            tk.Label(row, text=name, bg=CARD, fg=TEXT, font=FONT_SMALL, anchor='w')\
                .pack(side='left', fill='x', expand=True)
            val = r.get('value')
            detail = r.get('time', '') + ('  |  ' + val if val else '')
            tk.Label(row, text=detail, bg=CARD, fg=SUB, font=FONT_SUB).pack(side='right')

    def _set_date(self, iso):
        self.sel_date = iso
        self._refresh()

    def _render_overview(self, data):
        box = tk.Frame(self.body, bg=CARD)
        box.pack(fill='x')
        tasks = data['tasks']
        if not tasks:
            tk.Label(box, text='还没有待办项目', bg=CARD, fg=SUB, font=FONT_SMALL).pack(pady=30)
            return
        for t in tasks:
            recs = [r for r in data['records'] if r['task_id'] == t['id']]
            recs.sort(key=lambda r: r['date'] + r.get('time', ''), reverse=True)
            meta = TYPE_META.get(t['type'], TYPE_META['daily'])

            row = tk.Frame(box, bg=CARD)
            row.pack(fill='x', padx=10, pady=6)
            tk.Label(row, text=meta['icon'], bg=CARD, fg=meta['color'], font=FONT_TEXT, width=2)\
                .pack(side='left')
            col = tk.Frame(row, bg=CARD)
            col.pack(side='left', fill='x', expand=True)
            tk.Label(col, text=t['text'], bg=CARD, fg=TEXT, font=FONT_TEXT, anchor='w')\
                .pack(fill='x')
            tk.Label(col, text='%s · 累计打卡 %d 次' % (meta['label'], len(recs)), bg=CARD,
                     fg=SUB, font=FONT_SUB, anchor='w').pack(fill='x')

            # 最近几条记录
            for r in recs[:3]:
                val = r.get('value')
                s = '%s  %s' % (r['date'], r.get('time', ''))
                if val:
                    s += '  →  ' + val
                tk.Label(col, text=s, bg=CARD, fg=SUB, font=FONT_SUB, anchor='w')\
                    .pack(fill='x')
            if len(recs) > 3:
                tk.Label(col, text='… 共 %d 条记录' % len(recs), bg=CARD, fg=SUB, font=FONT_SUB,
                         anchor='w').pack(fill='x')


# ================= 任务管理窗口 =================
class TaskManagerWindow(tk.Toplevel):
    def __init__(self, master, on_changed=None):
        super().__init__(master)
        self.on_changed = on_changed
        self.title('待办管理')
        self.configure(bg=BG)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry('430x580+%d+%d' % ((sw - 430) // 2, (sh - 580) // 2 - 30))
        self.transient(master)
        self._build()
        self._refresh()

    def _build(self):
        head = tk.Frame(self, bg=BG)
        head.pack(fill='x', padx=12, pady=(10, 4))
        self.stat_label = tk.Label(head, text='', bg=BG, fg=SUB, font=FONT_SMALL)
        self.stat_label.pack(side='left')
        tk.Button(head, text='＋ 添加', bg=ACCENT, fg='white', bd=0, font=FONT_SMALL,
                  activebackground=ACCENT2, activeforeground='white', cursor='hand2',
                  command=self._add).pack(side='right', ipadx=12, ipady=5)

        # 开机自启开关
        opts = tk.Frame(self, bg=BG)
        opts.pack(fill='x', padx=12, pady=(0, 4))
        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        tk.Checkbutton(opts, text='开机自启', variable=self.startup_var, bg=BG, fg=TEXT,
                       font=FONT_SMALL, activebackground=BG, selectcolor=BG,
                       command=lambda: set_startup(self.startup_var.get()))\
            .pack(side='left')
        tk.Label(opts, text='关闭按钮 → 最小化到托盘', bg=BG, fg=SUB, font=FONT_SUB)\
            .pack(side='right')

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill='both', expand=True, padx=12, pady=(0, 12))
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0)
        self.sb = tk.Scrollbar(wrap, orient='vertical', command=self.canvas.yview, width=8)
        self.list_frame = tk.Frame(self.canvas, bg=BG)
        self.list_frame.bind('<Configure>',
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.sb.pack(side='right', fill='y')
        self.bind('<MouseWheel>', self._scroll)
        self.canvas.bind('<Configure>',
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))

    def _scroll(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    def _notify(self):
        if self.on_changed:
            self.on_changed()

    def _refresh(self):
        data = load_all()
        tasks = data['tasks']
        active = sum(1 for t in tasks if t.get('active', True))
        self.stat_label.config(text='共 %d 项 · 启用 %d 项' % (len(tasks), active))

        for c in self.list_frame.winfo_children():
            c.destroy()

        if not tasks:
            tk.Label(self.list_frame, text='还没有任何待办\n点右上角「＋ 添加」创建', bg=BG, fg=SUB,
                     font=FONT_SMALL, justify='center').pack(pady=40)
            return
        for t in tasks:
            self._render_task(t)

    def _render_task(self, t):
        meta = TYPE_META.get(t['type'], TYPE_META['daily'])
        act = t.get('active', True)
        recs = [r for r in load_all()['records'] if r['task_id'] == t['id']]

        card = tk.Frame(self.list_frame, bg=CARD)
        card.pack(fill='x', pady=4)

        top = tk.Frame(card, bg=CARD)
        top.pack(fill='x', padx=10, pady=(8, 2))
        tk.Label(top, text=meta['icon'], bg=CARD, fg=meta['color'], font=FONT_TEXT, width=2)\
            .pack(side='left')
        name = tk.Label(top, text=t['text'], bg=CARD, fg=TEXT if act else SUB,
                        font=FONT_TEXT, anchor='w')
        if not act:
            name.config(font=('Microsoft YaHei UI', 10, 'overstrike'))
        name.pack(side='left', fill='x', expand=True)

        sub_parts = [meta['label']]
        if t['type'] == 'once':
            sub_parts.append(t.get('date', ''))
        elif t['type'] == 'weekly':
            mode = t.get('weekly_mode', 'days')
            if mode == 'days':
                wd = [WEEK_FULL[i] for i in sorted(t.get('weekdays', []))]
                sub_parts.append('、'.join(wd))
            elif mode == 'once':
                sub_parts.append('每周完成一次 · %s重置' % WEEK_FULL[t.get('reset_weekday', 0)])
            elif mode == 'range':
                wd = [WEEK_CN[i] for i in sorted(t.get('available_weekdays', []))]
                sub_parts.append('限%s完成 · %s重置' % ('、'.join(wd) if wd else '未选', WEEK_FULL[t.get('reset_weekday', 0)]))
        elif t['type'] == 'custom':
            sub_parts.append('每 %d 天 · 自 %s' % (t.get('interval_days', 1), t.get('start_date', '')))
        if t.get('remind_enabled'):
            sub_parts.append('⏰ ' + t.get('remind_time', ''))
        sub_parts.append('打钩' if t['check_type'] == 'checkbox' else '自定义输入')
        sub_parts.append('累计 %d 次' % len(recs))
        tk.Label(card, text='  '.join(sub_parts), bg=CARD, fg=SUB, font=FONT_SUB, anchor='w',
                 justify='left', wraplength=360)\
            .pack(fill='x', padx=12, pady=(0, 2))

        bar = tk.Frame(card, bg=CARD)
        bar.pack(fill='x', padx=10, pady=(0, 8))
        tk.Button(bar, text='停用' if act else '启用',
                  bg='#eef0f7' if act else SUCCESS, fg=TEXT if act else 'white',
                  bd=0, font=FONT_SMALL, activebackground=LINE, cursor='hand2',
                  command=lambda t=t: self._toggle(t)).pack(side='left', ipadx=10, ipady=3)
        tk.Button(bar, text='编辑', bg='#eef0f7', fg=TEXT, bd=0, font=FONT_SMALL,
                  activebackground=LINE, cursor='hand2',
                  command=lambda t=t: self._edit(t)).pack(side='left', padx=6, ipadx=10, ipady=3)
        tk.Button(bar, text='删除', bg='#ffecef', fg=DANGER, bd=0, font=FONT_SMALL,
                  activebackground='#ffdce3', cursor='hand2',
                  command=lambda t=t: self._delete(t)).pack(side='left', padx=6, ipadx=10, ipady=3)

    def _add(self):
        AddTaskDialog(self, lambda task: (self._save(task), self._refresh()))

    def _edit(self, t):
        AddTaskDialog(self, lambda task: (self._save(task), self._refresh()), edit_task=t)

    def _save(self, task):
        data = load_all()
        for i, x in enumerate(data['tasks']):
            if x['id'] == task['id']:
                data['tasks'][i] = task
                break
        else:
            data['tasks'].append(task)
        save_all(data)
        self._notify()

    def _toggle(self, t):
        data = load_all()
        for x in data['tasks']:
            if x['id'] == t['id']:
                x['active'] = not x.get('active', True)
                break
        save_all(data)
        self._notify()
        self._refresh()

    def _delete(self, t):
        if not messagebox.askyesno('确认删除', '确定删除「%s」吗？\n（历史打卡记录会保留）' % t['text']):
            return
        data = load_all()
        data['tasks'] = [x for x in data['tasks'] if x['id'] != t['id']]
        save_all(data)
        self._notify()
        self._refresh()


# ================= 主挂件 =================
class TodoWidget:
    IDLE_MS = 2500          # 闲置多久后隐藏（毫秒）
    EDGE_PX = 3             # 隐藏后露出的边宽度
    EDGE_TRIGGER = 8        # 鼠标距离边缘多少像素触发唤出

    def __init__(self):
        enable_dpi_awareness()
        refresh_todo_icon()   # 按当天日期更新桌面图标
        self.root = tk.Tk()
        self.root.title('每日待办')
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.configure(bg=BG)

        self.collapsed = False
        self.hidden = False
        self.edge = 'right'
        self.w, self.h = 360, 500
        self.header_h = 44
        self._hidden_pos = None
        self.fs_hidden = False     # 因前台全屏而完全隐藏
        self.fs_pos = None
        self.tray = None           # 系统托盘图标（首次关闭时创建）
        self._quitting = False

        self.reminded = set()   # 已提醒 (task_id, date, time)

        self._set_pos()
        self._build_header()
        self._build_body()
        self.refresh()

        # 应用圆角（等窗口尺寸确定后）
        self.root.update_idletasks()
        apply_rounded(self.root)

        self.root.after(200, self._idle_loop)
        self.root.after(15000, self._remind_loop)
        self.root.after(200, self._fs_loop)
        self.root.after(60000, self._icon_refresh_loop)   # 跨天自动刷新图标

        # 默认开启开机自启（首次运行即注册）
        try:
            if not is_startup_enabled():
                set_startup(True)
        except Exception:
            pass

    def _set_pos(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry('%dx%d+%d+%d' % (self.w, self.h, sw - self.w - 24, sh - self.h - 70))

    # ---------- 贴边隐藏 ----------
    def _idle_loop(self):
        try:
            self._check_idle()
        finally:
            self.root.after(200, self._idle_loop)

    def _check_idle(self):
        if self.collapsed or self.fs_hidden:
            return
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        mx, my = self.root.winfo_pointerxy()

        if self.hidden:
            # 鼠标移动到贴边边缘则唤出
            if self.edge == 'right' and mx >= sw - self.EDGE_TRIGGER and y <= my <= y + h:
                self._show()
            elif self.edge == 'left' and mx <= self.EDGE_TRIGGER and y <= my <= y + h:
                self._show()
            elif self.edge == 'top' and my <= self.EDGE_TRIGGER and x <= mx <= x + w:
                self._show()
            return

        # 未隐藏：鼠标在窗口内则不计时
        inside = (x <= mx <= x + w) and (y <= my <= y + h)
        if inside:
            self._idle_since = datetime.datetime.now()
            return

        if not hasattr(self, '_idle_since'):
            self._idle_since = datetime.datetime.now()
        elapsed = (datetime.datetime.now() - self._idle_since).total_seconds() * 1000
        if elapsed >= self.IDLE_MS:
            self._hide()

    def _hide(self):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()

        # 判断贴哪边（就近隐藏）
        dist_left = x
        dist_right = sw - (x + w)
        if x <= 20:
            self.edge = 'left'
        elif dist_right <= 20:
            self.edge = 'right'
        else:
            self.edge = 'right' if dist_right < dist_left else 'left'

        self._hidden_pos = (x, y)
        if self.edge == 'right':
            new_x = sw - self.EDGE_PX
        else:
            new_x = -(w - self.EDGE_PX)
        self.root.geometry('%dx%d+%d+%d' % (w, h, new_x, y))
        self.hidden = True

    def _show(self):
        if not self.hidden:
            return
        x, y = self._hidden_pos
        sw = self.root.winfo_screenwidth()
        w = self.root.winfo_width()
        if self.edge == 'right':
            x = sw - w - 24
        else:
            x = 24
        self.root.geometry('%dx%d+%d+%d' % (w, self.root.winfo_height(), x, y))
        self.hidden = False
        self._idle_since = datetime.datetime.now()

    # ---------- 全屏监测（轮询前台窗口矩形，其他应用全屏时完全隐藏，不留边） ----------
    def _fs_loop(self):
        try:
            self._check_fullscreen()
        finally:
            self.root.after(200, self._fs_loop)

    def _check_fullscreen(self):
        fs = is_foreground_fullscreen(exclude_hwnd=self.root.winfo_id())
        if fs:
            if not self.fs_hidden:
                self.fs_pos = (self.root.winfo_x(), self.root.winfo_y())
                self.fs_hidden = True
                sw = self.root.winfo_screenwidth()
                self.root.geometry('+%d+%d' % (sw + 50, self.root.winfo_y()))
        else:
            if self.fs_hidden:
                self.fs_hidden = False
                if self.fs_pos:
                    self.root.geometry('+%d+%d' % self.fs_pos)
                self._idle_since = datetime.datetime.now()

    # ---------- 标题栏 ----------
    def _build_header(self):
        h = tk.Frame(self.root, bg=HEADER, height=self.header_h)
        h.pack(fill='x', side='top')
        h.pack_propagate(False)
        h.bind('<Button-1>', self._drag_start)
        h.bind('<B1-Motion>', self._drag_move)

        self.title_label = tk.Label(h, text='📋 今日待办', bg=HEADER, fg='white', font=FONT_TITLE)
        self.title_label.pack(side='left', padx=10)
        self.title_label.bind('<Button-1>', self._drag_start)
        self.title_label.bind('<B1-Motion>', self._drag_move)

        self.collapse_btn = tk.Button(h, text='—', bg=HEADER, fg='white', bd=0, font=FONT_TEXT,
                                      activebackground=HEADER, activeforeground='white',
                                      cursor='hand2', command=self._toggle_collapse)
        self.collapse_btn.pack(side='right', padx=2)
        tk.Button(h, text='✕', bg=HEADER, fg='white', bd=0, font=FONT_TEXT,
                  activebackground=DANGER, activeforeground='white', cursor='hand2',
                  command=self.hide_to_tray).pack(side='right', padx=6)

    # ---------- 主体 ----------
    def _build_body(self):
        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill='both', expand=True)

        # 进度
        bar_card = tk.Frame(self.body, bg=CARD)
        bar_card.pack(fill='x', padx=10, pady=(10, 6))
        self.progress_label = tk.Label(bar_card, text='', bg=CARD, fg=SUB, font=FONT_SMALL)
        self.progress_label.pack(anchor='w', padx=12, pady=(8, 4))
        self.progress_canvas = tk.Canvas(bar_card, width=336, height=8, bg=CARD, highlightthickness=0)
        self.progress_canvas.pack(padx=12, pady=(0, 10))

        # 列表
        list_wrap = tk.Frame(self.body, bg=CARD)
        list_wrap.pack(fill='both', expand=True, padx=10, pady=(6, 6))
        self.canvas = tk.Canvas(list_wrap, bg=CARD, highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(list_wrap, orient='vertical', command=self.canvas.yview, width=8)
        self.list_frame = tk.Frame(self.canvas, bg=CARD)
        self.list_frame.bind('<Configure>',
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.list_frame, anchor='nw')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')
        self.root.bind('<MouseWheel>', self._scroll)
        self.canvas.bind('<Configure>',
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width))

        # 底部按钮
        bottom = tk.Frame(self.body, bg=BG)
        bottom.pack(fill='x', padx=10, pady=(0, 10))
        tk.Button(bottom, text='＋ 添加', bg=ACCENT, fg='white', bd=0, font=FONT_SMALL,
                  activebackground=ACCENT2, activeforeground='white', cursor='hand2',
                  command=self.open_add).pack(side='left', ipadx=10, ipady=6)
        tk.Button(bottom, text='📅 历史', bg=CARD, fg=TEXT, bd=0, font=FONT_SMALL,
                  activebackground=LINE, cursor='hand2', command=self.open_history)\
            .pack(side='right', ipadx=8, ipady=6)
        tk.Button(bottom, text='⚙ 管理', bg=CARD, fg=TEXT, bd=0, font=FONT_SMALL,
                  activebackground=LINE, cursor='hand2', command=self.open_manager)\
            .pack(side='right', padx=4, ipadx=8, ipady=6)

    def _scroll(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), 'units')

    # ---------- 拖动 ----------
    def _drag_start(self, e):
        self._dx = e.x_root - self.root.winfo_x()
        self._dy = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.root.geometry('+%d+%d' % (e.x_root - self._dx, e.y_root - self._dy))
        self._idle_since = datetime.datetime.now()

    # ---------- 折叠 ----------
    def _toggle_collapse(self):
        self.collapsed = not self.collapsed
        if self.collapsed:
            self.body.pack_forget()
            self.root.geometry('%dx%d' % (self.w, self.header_h))
            self.collapse_btn.config(text='□')
        else:
            self.body.pack(fill='both', expand=True)
            self.root.geometry('%dx%d' % (self.w, self.h))
            self.collapse_btn.config(text='—')
            self.refresh()
        self.root.update_idletasks()
        apply_rounded(self.root)

    # ---------- 后台常驻（托盘） ----------
    def hide_to_tray(self):
        """最小化到系统托盘，后台常驻"""
        self.root.withdraw()
        if self.tray is None:
            try:
                self.tray = TrayIcon(
                    os.path.join(BASE, 'todo.ico'), '每日待办',
                    on_show=self.show_from_tray, on_quit=self.quit_app)
            except Exception:
                self.tray = None
        self.root.after(100, self._tray_loop)

    def show_from_tray(self):
        self.root.deiconify()
        self.root.lift()
        self._idle_since = datetime.datetime.now()

    def quit_app(self):
        self._quitting = True
        self.root.destroy()

    def _tray_loop(self):
        try:
            if self.tray:
                ev = self.tray.poll()
                if ev:
                    if ev[0] == 'show':
                        self.show_from_tray()
                    elif ev[0] == 'quit':
                        self.quit_app()
        finally:
            if not self._quitting:
                self.root.after(100, self._tray_loop)

    # ---------- 跨天自动刷新图标 ----------
    def _icon_refresh_loop(self):
        try:
            refresh_todo_icon()
        finally:
            self.root.after(60000, self._icon_refresh_loop)

    # ---------- 单实例唤起 ----------
    def set_wake_event(self, handle):
        self._wake_handle = handle
        self.root.after(500, self._wake_loop)

    def _wake_loop(self):
        try:
            h = getattr(self, '_wake_handle', None)
            if h:
                kernel32 = ctypes.windll.kernel32
                kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel32.WaitForSingleObject.restype = wintypes.DWORD
                kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
                if kernel32.WaitForSingleObject(h, 0) == 0:  # WAIT_OBJECT_0
                    kernel32.ResetEvent(h)
                    self.wake_up()
        finally:
            self.root.after(500, self._wake_loop)

    def wake_up(self):
        """唤起窗口（从托盘/贴边/全屏隐藏状态恢复）"""
        if self.fs_hidden:
            self.fs_hidden = False
            if self.fs_pos:
                self.root.geometry('+%d+%d' % self.fs_pos)
        if self.hidden:
            self._show()
        self.root.deiconify()
        self.root.lift()
        self._idle_since = datetime.datetime.now()

    # ---------- 打卡 ----------
    def _is_weekly_once(self, task):
        return task.get('type') == 'weekly' and task.get('weekly_mode') in ('once', 'range')

    def do_checkin(self, task):
        data = load_all()
        if task['check_type'] == 'text':
            CheckinDialog(self.root, lambda val: self._record(data, task, val))
        else:
            if self._is_weekly_once(task):
                wr = cycle_records(data['records'], task['id'], today(), task.get('reset_weekday', 0))
                if wr:
                    ids = {r['id'] for r in wr}
                    data['records'] = [r for r in data['records'] if r['id'] not in ids]
                    save_all(data)
                else:
                    self._record(data, task, None)
            else:
                rec = get_record(data['records'], task['id'], today_iso())
                if rec:
                    data['records'] = [r for r in data['records'] if r['id'] != rec['id']]
                    save_all(data)
                else:
                    self._record(data, task, None)
            self.refresh()

    def _record(self, data, task, value):
        data.setdefault('records', []).append({
            'id': gen_id(),
            'task_id': task['id'],
            'date': today_iso(),
            'time': datetime.datetime.now().strftime('%H:%M'),
            'value': value,
            'kind': task['check_type'],
        })
        save_all(data)
        self.refresh()

    def remove_task(self, tid):
        data = load_all()
        data['tasks'] = [t for t in data['tasks'] if t['id'] != tid]
        save_all(data)
        self.refresh()

    # ---------- 弹窗 ----------
    def open_add(self):
        AddTaskDialog(self.root, self._save_task)

    def _save_task(self, task):
        data = load_all()
        for i, x in enumerate(data['tasks']):
            if x['id'] == task['id']:
                data['tasks'][i] = task
                break
        else:
            data['tasks'].append(task)
        save_all(data)
        self.refresh()

    def open_history(self):
        HistoryWindow(self.root)

    def open_manager(self):
        TaskManagerWindow(self.root, on_changed=self.refresh)

    # ---------- 提醒 ----------
    def _remind_loop(self):
        try:
            self._check_reminders()
        finally:
            self.root.after(15000, self._remind_loop)

    def _check_reminders(self):
        now = datetime.datetime.now()
        hm = now.strftime('%H:%M')
        data = load_all()
        today_tasks = tasks_for_date(data['tasks'], today())
        for t in today_tasks:
            if not t.get('remind_enabled'):
                continue
            if t.get('remind_time') != hm:
                continue
            key = (t['id'], today_iso(), hm)
            if key in self.reminded:
                continue
            if is_done(t, data['records'], today()):
                continue
            self.reminded.add(key)
            play_sound()
            ReminderPopup(t, lambda t=t: self.do_checkin(t), lambda: None)

    # ---------- 渲染 ----------
    def refresh(self):
        data = load_all()
        tasks = tasks_for_date(data['tasks'], today())

        self.title_label.config(text='📋 %s · %s' % (today_iso(), WEEK_FULL[today().weekday()]))

        done = sum(1 for t in tasks if is_done(t, data['records'], today()))
        total = len(tasks)
        self.progress_label.config(text='今日进度 %d / %d' % (done, total))
        self.progress_canvas.delete('all')
        self.progress_canvas.create_rectangle(0, 0, 336, 8, fill='#eef0f7', outline='')
        if total:
            self.progress_canvas.create_rectangle(0, 0, 336 * done / total, 8, fill=ACCENT, outline='')

        for child in self.list_frame.winfo_children():
            child.destroy()

        if not tasks:
            tk.Label(self.list_frame,
                     text='今天没有待办\n点下方「＋ 添加待办」创建\n支持每日/一次性/每周/自定义周期',
                     bg=CARD, fg=SUB, font=FONT_SMALL, justify='center').pack(pady=30)
            return

        for t in tasks:
            self._render_task(t)

    def _render_task(self, t):
        data = load_all()
        if self._is_weekly_once(t):
            wr = cycle_records(data['records'], t['id'], today(), t.get('reset_weekday', 0))
            rec = wr[-1] if wr else None
            done = bool(wr)
        else:
            rec = get_record(data['records'], t['id'], today_iso())
            done = rec is not None
        meta = TYPE_META.get(t['type'], TYPE_META['daily'])

        row = tk.Frame(self.list_frame, bg=CARD)
        row.pack(fill='x', padx=6, pady=3)

        # 打卡按钮
        if t['check_type'] == 'checkbox':
            btn_text = '✓' if done else ''
            btn_bg = SUCCESS if done else CARD
            btn_fg = 'white' if done else SUB
        else:
            btn_text = '✓' if done else '✎'
            btn_bg = SUCCESS if done else CARD
            btn_fg = 'white' if done else ACCENT
        box = tk.Label(row, text=btn_text, bg=btn_bg, fg=btn_fg,
                       font=('Microsoft YaHei UI', 9, 'bold'), width=2, height=1,
                       bd=0, cursor='hand2', highlightthickness=1,
                       highlightbackground=SUCCESS if done else '#cfd4e0')
        box.pack(side='left', padx=(2, 8), pady=4)
        box.bind('<Button-1>', lambda e, t=t: self.do_checkin(t))

        # 类型图标
        tk.Label(row, text=meta['icon'], bg=CARD, fg=meta['color'], font=FONT_TEXT, width=2)\
            .pack(side='left')

        # 文字
        col = tk.Frame(row, bg=CARD)
        col.pack(side='left', fill='x', expand=True)
        fg = SUB if done else TEXT
        name = tk.Label(col, text=t['text'], bg=CARD, fg=fg, font=FONT_TEXT, anchor='w',
                        justify='left', wraplength=190)
        name.pack(fill='x')
        if done:
            name.config(font=('Microsoft YaHei UI', 10, 'overstrike'))
        sub_parts = [meta['label']]
        if t['type'] == 'weekly':
            mode = t.get('weekly_mode', 'days')
            if mode == 'once':
                sub_parts.append('每周一次 · %s重置' % WEEK_FULL[t.get('reset_weekday', 0)])
            elif mode == 'range':
                wd = [WEEK_CN[i] for i in sorted(t.get('available_weekdays', []))]
                sub_parts.append('限%s完成' % ('、'.join(wd) if wd else '未选'))
        if t.get('remind_enabled'):
            sub_parts.append('⏰ ' + t.get('remind_time', ''))
        if rec and rec.get('value'):
            sub_parts.append('打卡：' + rec['value'])
        tk.Label(col, text='  '.join(sub_parts), bg=CARD, fg=SUB, font=FONT_SUB, anchor='w',
                 justify='left', wraplength=210)\
            .pack(fill='x')

        # 删除
        del_btn = tk.Label(row, text='✕', bg=CARD, fg=SUB, font=FONT_TEXT, cursor='hand2', width=2)
        del_btn.pack(side='right', padx=(4, 2))
        del_btn.bind('<Button-1>', lambda e, t=t: self.remove_task(t['id']))
        del_btn.bind('<Enter>', lambda e: del_btn.config(fg=DANGER))
        del_btn.bind('<Leave>', lambda e: del_btn.config(fg=SUB))


def main():
    # 单实例：已有实例则唤起后退出
    is_first, wake_handle = acquire_single_instance()
    if not is_first:
        wake_existing_instance()
        return
    w = TodoWidget()
    if wake_handle:
        w.set_wake_event(wake_handle)
    w.root.mainloop()


if __name__ == '__main__':
    main()
