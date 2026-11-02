# -*- coding: utf-8 -*-
"""PDF 浮水印工具（GUI 版）

功能：
  - 左側檔案清單：可拖放 PDF 進視窗，或按「新增 PDF」
  - 中間即時預覽：任何設定改動都會立即重繪（顯示第 1 個檔案的目前頁面）
  - 右側設定：文字／樣式／字號／透明度／角度／顏色／密度
  - 「套用並儲存」對清單中全部檔案加浮水印，輸出到原檔旁（加「浮水印」後綴）
  - 右上角可切換淺色／深色主題

本工具完全離線運作，檔案不會外傳。
"""
import io
import os
import re
import sys
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pymupdf
from PIL import Image

try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
except Exception:
    DND_FILES = None
    BaseTk = tk.Tk

try:
    import sv_ttk
except Exception:
    sv_ttk = None

VERSION = "1.1.0"
UI_FONT = "Microsoft JhengHei"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\msjh.ttc",
    r"C:\Windows\Fonts\msjhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\Deng.ttf",
]
COLORS = {
    "灰色": (0.55, 0.55, 0.55),
    "黑色": (0.10, 0.10, 0.10),
    "紅色": (0.75, 0.12, 0.12),
    "藍色": (0.15, 0.30, 0.75),
}
DEFAULT_TEXT = "僅供個人複習"
ACCENT = "#005fb8"          # 淺色主題強調色
ACCENT_DARK = "#4cc2ff"     # 深色主題強調色


def pick_font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


def draw_on_page(page, s):
    """在 pymupdf 頁面上畫浮水印（預覽與輸出共用同一套幾何）"""
    r = page.rect
    text = s["text"] if s["text"] else " "
    color = s["color"]
    angle = s["angle"]
    if s["style"] == "center":
        if s["auto"]:
            fs = max(24, min(r.width, r.height) / max(4, len(text)) * 1.15)
        else:
            fs = s["fontsize"]
        box = pymupdf.Rect(-r.width * 0.25, r.height / 2 - fs,
                           r.width * 1.25, r.height / 2 + fs * 1.8)
        page.insert_textbox(
            box, text, fontsize=fs, fontname="wmfont", fontfile=s["fontfile"],
            align=pymupdf.TEXT_ALIGN_CENTER, fill=color,
            fill_opacity=s["opacity"],
            morph=(pymupdf.Point(r.width / 2, r.height / 2), pymupdf.Matrix(angle)),
        )
    else:
        if s["auto"]:
            fs = max(14, min(r.width, r.height) / 26)
        else:
            fs = s["fontsize"]
        dens = s["density"] / 100.0
        dx, dy = r.width / 3.2 * dens, r.height / 4.5 * dens
        row = 0
        y = dy * 0.55
        while y < r.height + fs:
            x = dx * 0.35 + (row % 2) * (dx / 2)
            while x < r.width + fs:
                page.insert_text(
                    pymupdf.Point(x, y), text, fontsize=fs,
                    fontname="wmfont", fontfile=s["fontfile"], fill=color,
                    fill_opacity=s["opacity"],
                    morph=(pymupdf.Point(x, y), pymupdf.Matrix(angle)),
                )
                x += dx
            y += dy
            row += 1


def unique_output(path):
    base, ext = os.path.splitext(path)
    out = base + "_浮水印" + ext
    n = 1
    while os.path.exists(out):
        out = base + "_浮水印" + str(n) + ext
        n += 1
    return out


class App(BaseTk):
    def __init__(self, preload=None, selftest=False):
        super().__init__()
        self.title("PDF 浮水印工具")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(1240, int(sw * 0.92))
        h = min(880, int(sh * 0.92))
        self.geometry("{}x{}".format(w, h))
        self.minsize(1020, 660)
        self._set_icon()

        self.fontfile = pick_font()
        self.files = []
        self.doc = None
        self.doc_path = None
        self.page_index = 0
        self.base_cache = None      # (path, pno, w, h, PIL.Image)
        self._photo = None
        self._after_id = None
        self._apply_results = None
        self.selftest = selftest

        if sv_ttk is not None:
            sv_ttk.set_theme("light")
        self._build_ui()
        if sv_ttk is not None:
            self._apply_theme_colors()
        self._bind_events()

        if preload:
            self.add_files(preload)
        self.after(200, self._initial_render)

    def _set_icon(self):
        candidates = []
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "icon.ico"))
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico"))
        for c in candidates:
            if os.path.exists(c):
                try:
                    self.iconbitmap(c)
                    self._icon_path = c
                    return
                except Exception:
                    pass

    # ---------------- UI ----------------
    def _build_ui(self):
        style = ttk.Style(self)
        if sv_ttk is None:
            # 沒有 sv-ttk 時的退化外觀
            try:
                style.theme_use("clam")
            except Exception:
                pass
        style.configure(".", font=(UI_FONT, 10))
        style.configure("Big.TButton", font=(UI_FONT, 11, "bold"), padding=(14, 9))
        style.configure("Tool.TButton", font=(UI_FONT, 9), padding=(8, 3))
        style.configure("Title.TLabel", font=(UI_FONT, 15, "bold"))
        style.configure("Header.TLabel", font=(UI_FONT, 11, "bold"))
        style.configure("Sub.TLabel", font=(UI_FONT, 9), foreground="#6b7280")
        style.configure("Val.TLabel", font=("Consolas", 9), foreground="#6b7280")

        # 頂部標題列
        header = ttk.Frame(self, padding=(16, 10, 16, 4))
        header.pack(fill="x")
        ttk.Label(header, text="PDF 浮水印工具", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="　v" + VERSION + "・離線本機處理", style="Sub.TLabel").pack(
            side="left", pady=(4, 0))
        if sv_ttk is not None:
            self.theme_btn = ttk.Button(header, text="🌙 深色", style="Tool.TButton",
                                        command=self.on_toggle_theme)
            self.theme_btn.pack(side="right")

        # 主體三欄
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)

        def card(parent, title, sub=None):
            c = ttk.Frame(parent, style="Card.TFrame", padding=(14, 10, 14, 12))
            ttk.Label(c, text=title, style="Header.TLabel").pack(anchor="w")
            if sub:
                ttk.Label(c, text=sub, style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            else:
                ttk.Frame(c, style="Card.TFrame", height=8).pack()
            return c

        # 左：檔案清單
        left = card(main, "檔案", "把 PDF 拖進視窗即可加入")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        lb = ttk.Frame(left, style="Card.TFrame")
        lb.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(lb, selectmode=tk.EXTENDED,
                                  font=(UI_FONT, 9), activestyle="none",
                                  borderwidth=0, highlightthickness=0,
                                  exportselection=False)
        lsb = ttk.Scrollbar(lb, orient="vertical", command=self.listbox.yview)
        self.listbox.config(yscrollcommand=lsb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        btns = ttk.Frame(left, style="Card.TFrame")
        btns.pack(fill="x", pady=(8, 2))
        ttk.Button(btns, text="新增 PDF", style="Tool.TButton",
                   command=self.on_add).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(btns, text="移除所選", style="Tool.TButton",
                   command=self.on_remove).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(btns, text="清空", style="Tool.TButton",
                   command=self.on_clear).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Label(left, text="預覽與浮水印會套用到清單中全部檔案",
                  style="Sub.TLabel", wraplength=220).pack(anchor="w", pady=(6, 0))

        # 中：預覽
        mid = card(main, "即時預覽")
        mid.grid(row=0, column=1, sticky="nsew", padx=8)
        nav = ttk.Frame(mid, style="Card.TFrame")
        nav.pack(side="bottom", fill="x", pady=(8, 0))
        self.canvas = tk.Canvas(mid, bg="#33363c", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.prev_btn = ttk.Button(nav, text="◀ 上一頁", style="Tool.TButton",
                                   command=lambda: self.flip(-1), state="disabled")
        self.prev_btn.pack(side="left")
        self.page_var = tk.StringVar(value="—")
        ttk.Label(nav, textvariable=self.page_var,
                  font=(UI_FONT, 9)).pack(side="left", expand=True)
        self.next_btn = ttk.Button(nav, text="下一頁 ▶", style="Tool.TButton",
                                   command=lambda: self.flip(1), state="disabled")
        self.next_btn.pack(side="right")

        # 右：設定（套用按鈕先佔住卡片底部，內容填其餘空間）
        right = card(main, "浮水印設定")
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        applyf = ttk.Frame(right, style="Card.TFrame")
        applyf.pack(side="bottom", fill="x", pady=(10, 0))
        self.apply_btn = ttk.Button(applyf, text="套用並儲存", style="Big.TButton",
                                    command=self.on_apply)
        self.apply_btn.pack(fill="x")
        ttk.Label(applyf, text="輸出：存在原檔旁，檔名加「浮水印」；原檔不會被改動。",
                  style="Sub.TLabel", wraplength=260).pack(anchor="w", pady=(6, 0))
        inner = ttk.Frame(right, style="Card.TFrame")
        inner.pack(fill="both", expand=True)
        inner.grid_columnconfigure(1, weight=1)

        ttk.Label(inner, text="浮水印文字", style="Header.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(2, 3))
        self.text_var = tk.StringVar(value=DEFAULT_TEXT)
        ttk.Entry(inner, textvariable=self.text_var,
                  font=(UI_FONT, 10)).grid(row=1, column=0, columnspan=3, sticky="we")

        self.style_var = tk.StringVar(value="tile")
        rf = ttk.Frame(inner, style="Card.TFrame")
        rf.grid(row=2, column=0, columnspan=3, sticky="we", pady=(10, 0))
        ttk.Radiobutton(rf, text="滿頁平鋪", value="tile",
                        variable=self.style_var).pack(side="left", expand=True)
        ttk.Radiobutton(rf, text="居中大水印", value="center",
                        variable=self.style_var).pack(side="left", expand=True)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(inner, text="自動字號（跟隨頁面大小）", variable=self.auto_var,
                        command=self.on_auto_toggle).grid(row=3, column=0, columnspan=3,
                                                          sticky="w", pady=(10, 0))

        def srow(r, label, frm, to, var, val_var, val_text):
            ttk.Label(inner, text=label, style="Sub.TLabel").grid(
                row=r, column=0, sticky="w", pady=(10, 0))
            sc = ttk.Scale(inner, from_=frm, to=to, variable=var,
                           command=lambda v: self._on_change())
            sc.grid(row=r, column=1, sticky="we", padx=(12, 8), pady=(10, 0))
            val_var.set(val_text)
            ttk.Label(inner, textvariable=val_var, style="Val.TLabel", width=7,
                      anchor="e").grid(row=r, column=2, sticky="e", pady=(10, 0))
            return sc

        self.size_var = tk.DoubleVar(value=30)
        self.size_val = tk.StringVar()
        self.size_scale = srow(4, "字號", 12, 90, self.size_var, self.size_val, "30 pt")
        self.op_var = tk.DoubleVar(value=12)
        self.op_val = tk.StringVar()
        self.op_scale = srow(5, "不透明度", 5, 50, self.op_var, self.op_val, "12 %")
        self.ang_var = tk.DoubleVar(value=38)
        self.ang_val = tk.StringVar()
        self.ang_scale = srow(6, "角度", 0, 90, self.ang_var, self.ang_val, "38 °")

        ttk.Label(inner, text="顏色", style="Sub.TLabel").grid(row=7, column=0, sticky="w",
                                                               pady=(12, 0))
        self.color_box = ttk.Combobox(inner, values=list(COLORS.keys()),
                                      state="readonly", font=(UI_FONT, 9))
        self.color_box.current(0)
        self.color_box.grid(row=7, column=1, columnspan=2, sticky="we", padx=(12, 0), pady=(12, 0))

        self.den_var = tk.DoubleVar(value=100)
        self.den_val = tk.StringVar()
        self.den_scale = srow(8, "平鋪密度", 60, 200, self.den_var, self.den_val, "100 %")

        # 底部狀態列
        self.status_var = tk.StringVar()
        status = ttk.Label(self, textvariable=self.status_var, anchor="w",
                           style="Sub.TLabel", padding=(16, 4))
        status.pack(fill="x", side="bottom")
        font_name = os.path.basename(self.fontfile) if self.fontfile else "未找到中文字體！"
        self.status_var.set("就緒｜v{}｜浮水印字體：{}".format(VERSION, font_name))
        if not self.fontfile:
            messagebox.showwarning("PDF 浮水印工具", "找不到可用的中文字體，浮水印文字可能無法顯示。")

        if DND_FILES:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self.on_drop)

    def _apply_theme_colors(self):
        dark = sv_ttk.get_theme() == "dark"
        muted = "#9aa1ac" if dark else "#6b7280"
        style = ttk.Style(self)
        style.configure("Sub.TLabel", foreground=muted)
        style.configure("Val.TLabel", foreground=muted)
        if dark:
            lb_bg, lb_fg, sel_bg, sel_fg = "#2b2b2c", "#f2f2f2", ACCENT_DARK, "#08131f"
            self._accent_hex = ACCENT_DARK
        else:
            lb_bg, lb_fg, sel_bg, sel_fg = "#ffffff", "#1c1c1c", ACCENT, "#ffffff"
            self._accent_hex = ACCENT
        self.listbox.config(bg=lb_bg, fg=lb_fg,
                            selectbackground=sel_bg, selectforeground=sel_fg)
        if hasattr(self, "theme_btn"):
            self.theme_btn.config(text="☀ 淺色" if dark else "🌙 深色")

    def on_toggle_theme(self):
        sv_ttk.toggle_theme()
        self._apply_theme_colors()

    def _bind_events(self):
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_change(0))
        self.text_var.trace_add("write", lambda *a: self._on_change())
        self.style_var.trace_add("write", lambda *a: self._on_change())
        self.op_var.trace_add("write", lambda *a: self._on_change())
        self.ang_var.trace_add("write", lambda *a: self._on_change())
        self.den_var.trace_add("write", lambda *a: self._on_change())
        self.color_box.bind("<<ComboboxSelected>>", lambda e: self._on_change())
        self.canvas.bind("<Configure>", lambda e: self._on_change(120))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- 檔案管理 ----------------
    def on_add(self):
        paths = filedialog.askopenfilenames(
            title="選擇 PDF 檔案", filetypes=[("PDF 檔案", "*.pdf"), ("所有檔案", "*.*")])
        self.add_files(paths)

    def on_drop(self, ev):
        data = ev.data
        parts = re.findall(r"\{([^}]*)\}|(\S+)", data)
        paths = [(a if a else b).strip('"') for a, b in parts]
        self.add_files([p for p in paths if p.lower().endswith(".pdf")])

    def add_files(self, paths):
        changed = False
        for p in paths:
            p = os.path.abspath(p)
            if p.lower().endswith(".pdf") and p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", "📄 " + os.path.basename(p))
                changed = True
        if changed:
            self._reload_doc()
            self._on_change(0)

    def on_remove(self):
        sel = list(self.listbox.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            del self.files[idx]
            self.listbox.delete(idx)
        self._reload_doc()
        self._on_change(0)

    def on_clear(self):
        self.files = []
        self.listbox.delete(0, "end")
        self._reload_doc()
        self._on_change(0)

    def _reload_doc(self):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = None
            self.doc_path = None
        self.base_cache = None
        self.page_index = 0
        if self.files:
            path = self.files[0]
            try:
                d = pymupdf.open(path)
                if d.needs_pass:
                    self.status_var.set("⚠ 第一個檔案有密碼保護，無法預覽：" + os.path.basename(path))
                    d.close()
                    return
                self.doc = d
                self.doc_path = path
            except Exception as ex:
                self.status_var.set("⚠ 無法開啟檔案：" + str(ex))

    # ---------------- 預覽 ----------------
    def flip(self, step):
        if self.doc is None:
            return
        n = len(self.doc)
        self.page_index = min(n - 1, max(0, self.page_index + step))
        self.base_cache = None
        self._on_change(0)

    def _on_change(self, delay=220):
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.after(delay, self._render_now)

    def _initial_render(self):
        self._render_now()

    def _collect(self):
        return {
            "text": self.text_var.get().strip(),
            "style": self.style_var.get(),
            "auto": self.auto_var.get(),
            "fontsize": int(round(self.size_var.get())),
            "opacity": max(0.05, min(0.95, self.op_var.get() / 100.0)),
            "angle": int(round(self.ang_var.get())),
            "color": COLORS.get(self.color_box.get(), (0.55, 0.55, 0.55)),
            "density": int(round(self.den_var.get())),
            "fontfile": self.fontfile,
        }

    def _sync_labels(self):
        self.size_val.set("{} pt".format(int(round(self.size_var.get()))))
        self.op_val.set("{} %".format(int(round(self.op_var.get()))))
        self.ang_val.set("{} °".format(int(round(self.ang_var.get()))))
        self.den_val.set("{} %".format(int(round(self.den_var.get()))))
        if self.auto_var.get():
            self.size_scale.state(["disabled"])
        else:
            self.size_scale.state(["!disabled"])
        if self.style_var.get() == "center":
            self.den_scale.state(["disabled"])
        else:
            self.den_scale.state(["!disabled"])

    def on_auto_toggle(self):
        self._sync_labels()
        self._on_change()

    def _render_now(self):
        self._after_id = None
        self._sync_labels()
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        self.canvas.delete("all")
        self._photo = None
        self.prev_btn.config(state="disabled")
        self.next_btn.config(state="disabled")
        if not self.files:
            self.page_var.set("—")
            self.canvas.create_text(cw / 2, ch / 2, fill="#aeb4be",
                                    font=(UI_FONT, 12),
                                    text="把 PDF 拖進視窗，或按左邊「新增 PDF」\n\n任何設定改動都會即時預覽")
            return
        if self.doc is None:
            self.page_var.set("—")
            self.canvas.create_text(cw / 2, ch / 2, fill="#e8a0a0",
                                    font=(UI_FONT, 11),
                                    text="無法預覽第一個檔案\n（可能加密或損毀）")
            return
        n = len(self.doc)
        self.page_var.set("第 {} / {} 頁".format(self.page_index + 1, n))
        self.prev_btn.config(state="normal" if self.page_index > 0 else "disabled")
        self.next_btn.config(state="normal" if self.page_index < n - 1 else "disabled")

        page = self.doc[self.page_index]
        z = min((cw - 16) / page.rect.width, (ch - 16) / page.rect.height)
        z = max(0.05, z)
        key = (self.doc_path, self.page_index, round(cw), round(ch))
        try:
            if self.base_cache and self.base_cache[:4] == key:
                base_img = self.base_cache[4]
            else:
                pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
                base_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                self.base_cache = (self.doc_path, self.page_index, round(cw), round(ch), base_img)
            s = self._collect()
            ov = pymupdf.open()
            opage = ov.new_page(width=page.rect.width, height=page.rect.height)
            draw_on_page(opage, s)
            opix = opage.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=True)
            ov_img = Image.frombytes("RGBA", (opix.width, opix.height), opix.samples)
            combined = Image.alpha_composite(base_img.convert("RGBA"), ov_img)
            buf = io.BytesIO()
            combined.save(buf, format="PNG")
            self._photo = tk.PhotoImage(data=buf.getvalue())
            self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
            ov.close()
        except Exception as ex:
            self.canvas.create_text(cw / 2, ch / 2, fill="#e8a0a0",
                                    font=(UI_FONT, 10),
                                    text="預覽失敗：{}".format(ex))

    # ---------------- 套用輸出 ----------------
    def on_apply(self):
        if not self.files:
            messagebox.showinfo("PDF 浮水印工具", "請先加入至少一個 PDF 檔案。")
            return
        s = self._collect()
        if not s["fontfile"]:
            messagebox.showerror("PDF 浮水印工具", "找不到中文字體，無法產生浮水印。")
            return
        self.apply_btn.config(state="disabled")
        self.status_var.set("正在套用浮水印…（掃描大檔可能需要數十秒）")
        self._apply_results = None
        threading.Thread(target=self._apply_worker, args=(list(self.files), s),
                         daemon=True).start()
        self.after(120, self._poll_apply)

    def _apply_worker(self, files, s):
        results = []
        for f in files:
            try:
                doc = pymupdf.open(f)
                if doc.needs_pass:
                    doc.close()
                    results.append((f, None, "檔案有密碼保護，已略過"))
                    continue
                for page in doc:
                    draw_on_page(page, s)
                out = unique_output(f)
                doc.save(out, garbage=3, deflate=True)
                doc.close()
                results.append((f, out, None))
            except Exception as ex:
                results.append((f, None, str(ex)))
        self._apply_results = results

    def _poll_apply(self):
        if self._apply_results is None:
            self.after(120, self._poll_apply)
            return
        results = self._apply_results
        self.apply_btn.config(state="normal")
        ok = [r for r in results if r[1]]
        bad = [r for r in results if not r[1]]
        self.status_var.set("完成：成功 {} 個，略過／失敗 {} 個".format(len(ok), len(bad)))
        msg = "成功加上浮水印：{} 個檔案\n（輸出在原檔旁，檔名加「浮水印」）".format(len(ok))
        if bad:
            msg += "\n\n以下檔案未處理：\n" + "\n".join(
                "・{}（{}）".format(os.path.basename(r[0]), r[2]) for r in bad)
        if ok and messagebox.askyesno("完成", msg + "\n\n要開啟輸出資料夾嗎？"):
            os.startfile(os.path.dirname(ok[0][1]))

    def on_close(self):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.destroy()


def main():
    argv = sys.argv[1:]
    selftest = "--selftest" in argv
    preload = [a for a in argv if not a.startswith("--")]
    app = App(preload=preload, selftest=selftest)

    if selftest:
        sample = preload[0] if preload else None

        def run_test():
            try:
                assert sample and os.path.exists(sample), "樣本不存在"
                app.text_var.set("GUI測試水印")
                app.auto_var.set(False)
                app.size_var.set(36)
                app._render_now()
                assert app._photo is not None, "預覽圖未產生"
                assert app.apply_btn.winfo_ismapped(), "套用按鈕沒有顯示在畫面上！"
                s = app._collect()
                app._apply_worker([sample], s)
                res = app._apply_results
                assert res and res[0][1], "輸出失敗：" + str(res)
                chk = pymupdf.open(res[0][1])
                txt = chk[3].get_text()
                chk.close()
                assert "GUI測試水印" in txt, "輸出中找不到浮水印文字"
                print("SELFTEST OK ->", res[0][1])
            except Exception as ex:
                print("SELFTEST FAIL:", ex)
            finally:
                app.destroy()

        app.after(1200, run_test)
        app.mainloop()
    else:
        app.mainloop()


if __name__ == "__main__":
    main()
