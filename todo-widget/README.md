# 每日待办 · 桌面悬浮挂件

Windows 桌面上的无边框待办挂件：平时贴在屏幕边缘，鼠标移过去就滑出来，点完任务自动收起。

## 功能

- **悬浮贴边**：无边框、置顶、可拖动；闲置自动隐藏到屏幕边缘，鼠标移到边缘唤出。
- **四种任务周期**：每日 / 一次性 / 每周（可选星期）/ 自定义周期（内置日历选日期）。
- **到点提醒**：每项任务可设提醒时间，到点右下角弹窗 + 提示音。
- **两种打卡方式**：直接打钩，或自定义输入（例如「输入完成时间：」）。
- **打卡历史**：「日历检索」按天看完成情况，「项目总览」看单项任务的全部记录。
- **动态图标**：`gen_icon.py` 按当天日期生成 `todo.ico`，仅在日期变化时刷新（记录在 `.icon_date`）。

## 运行环境

- Windows 10 / 11
- Python 3（仅标准库：`tkinter`、`ctypes`、`winsound`，无需 `pip install`）
- 本机使用 `C:\python\python3.14.4\pythonw.exe`

## 启动

双击 `启动待办挂件.bat`（内部用 `%~dp0` 定位，移动到任何目录都能用），或：

```bat
pythonw desktop_widget.pyw
```

## 目录说明

| 文件 | 作用 |
| --- | --- |
| `desktop_widget.pyw` | 主程序（界面、任务逻辑、提醒、贴边行为） |
| `todo.html` | 历史记录 / 日历视图的内嵌页面 |
| `gen_icon.py` | 生成并刷新 `todo.ico` 图标 |
| `todo.ico` | 当前图标 |
| `preview.png` | 效果预览图 |
| `启动待办挂件.bat` | 启动器 |
| `todo_data.json` | **本地数据**：任务与打卡记录，首次运行自动生成，已被 `.gitignore` 排除 |
| `.icon_date` | **本地状态**：上次刷新图标的日期，已被 `.gitignore` 排除 |

## 数据说明

任务数据保存在同目录的 `todo_data.json`，结构为 `{"tasks": [...]}`，字段包括 `type`（`daily` / `once` / `weekly` / `custom`）、`check_type`、`remind_time`、`weekdays` 等。备份时只需复制这个文件。

> `todo_data.json` 与 `.icon_date` 属于个人运行时数据，仓库中不包含；首次运行会自动重建。
