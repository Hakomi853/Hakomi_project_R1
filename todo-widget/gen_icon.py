# -*- coding: utf-8 -*-
"""生成日历样式的 .ico 图标（纯标准库，无第三方依赖）。"""
import struct
import os
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'todo.ico')

# 颜色 (r, g, b, a)
BLUE  = (91, 108, 255, 255)     # 顶部装订条
RING  = (70, 84, 210, 255)      # 装订环
WHITE = (255, 255, 255, 255)    # 主体
NUM   = (31, 36, 48, 255)       # 数字
EDGE  = (226, 229, 240, 255)    # 底部描边

DIGITS = {
    '0': ['111', '101', '101', '101', '111'],
    '1': ['010', '110', '010', '010', '111'],
    '2': ['111', '001', '111', '100', '111'],
    '3': ['111', '001', '111', '001', '111'],
    '4': ['101', '101', '111', '001', '001'],
    '5': ['111', '100', '111', '001', '111'],
    '6': ['111', '100', '111', '101', '111'],
    '7': ['111', '001', '001', '010', '010'],
    '8': ['111', '101', '111', '101', '111'],
    '9': ['111', '101', '111', '001', '111'],
}


def make_buffer(w, h):
    return [[(0, 0, 0, 0) for _ in range(w)] for _ in range(h)]


def fill_rect(buf, x0, y0, x1, y1, color):
    h = len(buf)
    w = len(buf[0])
    for y in range(max(0, y0), min(h, y1)):
        for x in range(max(0, x0), min(w, x1)):
            buf[y][x] = color


def fill_circle(buf, cx, cy, r, color):
    h = len(buf)
    w = len(buf[0])
    r2 = r * r
    for y in range(max(0, cy - r), min(h, cy + r + 1)):
        for x in range(max(0, cx - r), min(w, cx + r + 1)):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r2:
                buf[y][x] = color


def rounded_rect(buf, x0, y0, x1, y1, r, color):
    fill_rect(buf, x0 + r, y0, x1 - r, y1, color)
    fill_rect(buf, x0, y0 + r, x1, y1 - r, color)
    for cx, cy in ((x0 + r, y0 + r), (x1 - r - 1, y0 + r),
                   (x0 + r, y1 - r - 1), (x1 - r - 1, y1 - r - 1)):
        fill_circle(buf, cx, cy, r, color)


def draw_digit(buf, ch, x0, y0, scale, color):
    rows = DIGITS.get(ch, DIGITS['0'])
    for ry, row in enumerate(rows):
        for rx, px in enumerate(row):
            if px == '1':
                fill_rect(buf, x0 + rx * scale, y0 + ry * scale,
                          x0 + (rx + 1) * scale, y0 + (ry + 1) * scale, color)


def render(size):
    buf = make_buffer(size, size)
    pad = max(1, int(size * 24 / 256))
    r = max(1, int(size * 48 / 256))
    x0, y0 = pad, pad
    x1, y1 = size - pad, size - pad
    header_h = int(size * 68 / 256)

    # 蓝色圆角底（整体）
    rounded_rect(buf, x0, y0, x1, y1, r, BLUE)
    # 白色主体（下半部分）
    fill_rect(buf, x0, y0 + header_h, x1, y1, WHITE)
    fill_circle(buf, x0 + r, y1 - r - 1, r, WHITE)
    fill_circle(buf, x1 - r - 1, y1 - r - 1, r, WHITE)

    # 装订环
    ring_y = y0 + header_h // 2
    ring_r = max(1, int(size * 17 / 256))
    hole_r = max(0, int(size * 8 / 256))
    for cx in (int(size * 90 / 256), int(size * 166 / 256)):
        fill_circle(buf, cx, ring_y, ring_r, RING)
        fill_circle(buf, cx, ring_y, hole_r, BLUE)

    # 日期数字
    day = datetime.date.today().day
    s = str(day)
    scale = max(1, int(size * 20 / 256))
    dw, dh = 3 * scale, 5 * scale
    total_w = len(s) * dw + (len(s) - 1) * scale
    sx = (size - total_w) // 2
    body_top = y0 + header_h
    sy = body_top + ((y1 - body_top) - dh) // 2
    x = sx
    for ch in s:
        draw_digit(buf, ch, x, sy, scale, NUM)
        x += dw + scale
    return buf


def buffer_to_bmp_data(buf):
    """把像素缓冲转成 ICO 内嵌的 32 位 BMP 数据（含 AND mask）。"""
    h = len(buf)
    w = len(buf[0])
    # BITMAPINFOHEADER (40 bytes)
    header = struct.pack('<IiiHHIIiiII', 40, w, h * 2, 1, 32, 0,
                         w * h * 4 + (w + 31) // 32 * 4 * h, 0, 0, 0, 0)
    xor = b''
    for y in range(h - 1, -1, -1):       # BMP 自底向上
        for x in range(w):
            r, g, b, a = buf[y][x]
            xor += struct.pack('<BBBB', b, g, r, a)
    # AND mask（全 0，每行 4 字节对齐）
    mask_row = b'\x00' * ((w + 31) // 32 * 4)
    mask = mask_row * h
    return header + xor + mask


def write_ico(sizes):
    images = []
    for s in sizes:
        images.append(buffer_to_bmp_data(render(s)))

    # ICONDIR
    count = len(sizes)
    header = struct.pack('<HHH', 0, 1, count)
    offset = 6 + 16 * count
    entries = b''
    datas = b''
    for s, data in zip(sizes, images):
        b = 0 if s >= 256 else s
        entries += struct.pack('<BBBBHHII', b, b, 0, 0, 1, 32, len(data), offset)
        datas += data
        offset += len(data)
    with open(OUT, 'wb') as f:
        f.write(header + entries + datas)
    return OUT


if __name__ == '__main__':
    path = write_ico([256, 48, 32, 16])
    print('图标已生成:', path, os.path.getsize(path), 'bytes')
