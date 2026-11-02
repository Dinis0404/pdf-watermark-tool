# -*- coding: utf-8 -*-
"""PDF 浮水印小工具（離線本機處理，檔案不會外傳）

用法一：把 PDF 拖放到「加水印.bat」圖示上（可一次拖多個）
用法二：雙擊「加水印.bat」，把 PDF 拖進黑色視窗後按 Enter
"""
import os
import re
import sys
import datetime
import pymupdf

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msjhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\Deng.ttf",
]
ANGLE = 38          # 水印傾斜角度
GRAY = (0.55, 0.55, 0.55)
OPACITY_TILE = 0.3  # 平鋪樣式透明度
OPACITY_BIG = 0.15   # 居中樣式透明度


def pick_font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


def stamp(path, text, style, fontfile):
    doc = pymupdf.open(path)
    if doc.needs_pass:
        print("  ✘ 檔案有密碼保護，略過：" + os.path.basename(path))
        doc.close()
        return None
    for page in doc:
        r = page.rect
        if style == "1":
            # 居中：單個大水印
            fs = max(30, min(r.width, r.height) / max(4, len(text)) * 1.15)
            box = pymupdf.Rect(-r.width * 0.2, r.height / 2 - fs,
                               r.width * 1.2, r.height / 2 + fs * 1.6)
            page.insert_textbox(
                box, text, fontsize=fs, fontname="wmfont", fontfile=fontfile,
                align=pymupdf.TEXT_ALIGN_CENTER, fill=GRAY,
                fill_opacity=OPACITY_BIG,
                morph=(pymupdf.Point(r.width / 2, r.height / 2), pymupdf.Matrix(ANGLE)),
            )
        else:
            # 滿頁平鋪：交錯排列的小水印
            fs = 22 if r.width < 700 else 30
            dx, dy = r.width / 3.2, r.height / 4.5
            row = 0
            y = dy * 0.55
            while y < r.height + fs:
                x = dx * 0.35 + (row % 2) * (dx / 2)
                while x < r.width + fs:
                    page.insert_text(
                        pymupdf.Point(x, y), text, fontsize=fs,
                        fontname="wmfont", fontfile=fontfile, fill=GRAY,
                        fill_opacity=OPACITY_TILE,
                        morph=(pymupdf.Point(x, y), pymupdf.Matrix(ANGLE)),
                    )
                    x += dx
                y += dy
                row += 1
    base, ext = os.path.splitext(path)
    out = base + "_浮水印" + ext
    n = 1
    while os.path.exists(out):
        out = base + "_浮水印" + str(n) + ext
        n += 1
    doc.save(out, garbage=3, deflate=True)
    doc.close()
    return out


def split_drag_line(line):
    """解析拖進視窗的一行路徑（含引號、含空格路徑都能處理）"""
    parts = re.findall(r'"([^"]*)"|(\S+)', line.strip())
    files = [(a if a else b).strip('"') for a, b in parts]
    return [f for f in files if f]


def main():
    args = sys.argv[1:]
    files, text, style = [], None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--text" and i + 1 < len(args):
            text = args[i + 1]; i += 2
        elif a == "--style" and i + 1 < len(args):
            style = args[i + 1]; i += 2
        else:
            files.append(a); i += 1

    interactive = False
    if not files:
        interactive = True
        line = input("把 PDF 拖進本視窗，然後按 Enter（可一次拖多個）:\n> ")
        files = split_drag_line(line)
        if not files:
            print("沒有收到檔案。")
            return

    if text is None:
        t = input("浮水印文字（直接按 Enter ＝ 僅供個人複習）: ").strip()
        text = t if t else "僅供個人複習"
    if style not in ("1", "2"):
        s = input("樣式：輸入 1＝居中大水印  2＝滿頁平鋪（直接按 Enter ＝ 2）: ").strip()
        style = s if s in ("1", "2") else "2"

    fontfile = pick_font()
    print()
    done = 0
    for f in files:
        if not os.path.exists(f):
            print("✘ 找不到檔案：" + f)
            continue
        if not f.lower().endswith(".pdf"):
            print("✘ 不是 PDF 檔：" + f)
            continue
        out = stamp(f, text, style, fontfile)
        if out:
            done += 1
            print("✔ 完成：" + os.path.basename(out))
    print("\n共處理 {} 個檔案。輸出在原檔案旁邊（檔名多了「浮水印」）。".format(done))
    if interactive:
        input("按 Enter 關閉視窗...")


if __name__ == "__main__":
    main()
