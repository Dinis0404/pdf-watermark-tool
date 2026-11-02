# -*- coding: utf-8 -*-
"""PDF 浮水印工具（GUI 版）

功能：
  - 左側檔案清單：可拖放 PDF 進視窗，或按「新增 PDF」
  - 中間即時預覽：任何設定改動都會立即重繪（顯示第 1 個檔案的目前頁面）
  - 右側設定：文字／樣式／字號／透明度／角度／顏色／密度
  - 「套用並儲存」對清單中全部檔案加浮水印，輸出到原檔旁（加「浮水印」後綴）

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
        self.geometry("1180x780")
        self.minsize(980, 640)
        self.configure(bg="#f2f4f8")

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

        self._build_ui()
        self._bind_events()

        if preload:
            self.add_files(preload)
        self.after(200, self._initial_render)

    # ---------------- UI ----------------
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass
        style.configure("Big.TButton", font=("Microsoft JhengHei", 11, "bold"), padding=8)
        style.configure("Tool.TButton", font=("Microsoft JhengHei", 9), padding=3)
        style.configure("Lab.TLabel", font=("Microsoft JhengHei", 10, "bold"), background="#f2f4f8")
        style.configure("Hint.TLabel", font=("Microsoft JhengHei", 8), background="#f2f4f8",
                        foreground="#777777")
        style.configure("Val.TLabel", font=("Microsoft JhengHei", 9), background="#f2f4f8")

        # 左：檔案清單
        left = ttk.LabelFrame(self, text=" 檔案（可拖放 PDF 進視窗） ")
        left.place(x=10, y=10, width=250, height=640)
        self.listbox = tk.Listbox(left, selectmode=tk.EXTENDED,
                                  font=("Microsoft JhengHei", 9),
                                  activestyle="none")
        self.listbox.pack(fill="both", expand=True, padx=6, pady=(6, 4))
        btns = ttk.Frame(left)
        btns.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Button(btns, text="新增 PDF", style="Tool.TButton",
                   command=self.on_add).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(btns, text="移除所選", style="Tool.TButton",
                   command=self.on_remove).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Button(btns, text="清空", style="Tool.TButton",
                   command=self.on_clear).pack(side="left", expand=True, fill="x", padx=1)
        ttk.Label(left, text="預覽與浮水印會套用到清單中全部檔案",
                  style="Hint.TLabel").pack(padx=8, pady=(0, 6), anchor="w")

        # 中：預覽
        mid = ttk.LabelFrame(self, text=" 預覽（即時） ")
        mid.place(x=270, y=10, width=600, height=640)
        self.canvas = tk.Canvas(mid, bg="#3c4048", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(6, 2))
        nav = ttk.Frame(mid)
        nav.pack(fill="x", padx=6, pady=(2, 6))
        self.prev_btn = ttk.Button(nav, text="◀ 上一頁", style="Tool.TButton",
                                   command=lambda: self.flip(-1), state="disabled")
        self.prev_btn.pack(side="left")
        self.page_var = tk.StringVar(value="—")
        ttk.Label(nav, textvariable=self.page_var,
                  font=("Microsoft JhengHei", 9)).pack(side="left", expand=True)
        self.next_btn = ttk.Button(nav, text="下一頁 ▶", style="Tool.TButton",
                                   command=lambda: self.flip(1), state="disabled")
        self.next_btn.pack(side="right")

        # 右：設定
        right = ttk.LabelFrame(self, text=" 浮水印設定 ")
        right.place(x=880, y=10, width=290, height=640)
        pad = dict(padx=12, pady=(8, 0), sticky="we")

        ttk.Label(right, text="浮水印文字", style="Lab.TLabel").grid(row=0, **pad)
        self.text_var = tk.StringVar(value=DEFAULT_TEXT)
        e = ttk.Entry(right, textvariable=self.text_var, font=("Microsoft JhengHei", 10))
        e.grid(row=1, **pad)

        ttk.Label(right, text="樣式", style="Lab.TLabel").grid(row=2, **pad)
        self.style_var = tk.StringVar(value="tile")
        rf = ttk.Frame(right)
        rf.grid(row=3, **pad)
        ttk.Radiobutton(rf, text="滿頁平鋪", value="tile", variable=self.style_var).pack(side="left", expand=True)
        ttk.Radiobutton(rf, text="居中大水印", value="center", variable=self.style_var).pack(side="left", expand=True)

        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="自動字號（跟隨頁面大小）", variable=self.auto_var,
                        command=self.on_auto_toggle).grid(row=4, **pad)
        self.size_var = tk.DoubleVar(value=30)
        self.size_scale = ttk.Scale(right, from_=12, to=90, variable=self.size_var,
                                    command=lambda v: self._on_change())
        self.size_scale.grid(row=5, **pad)
        self.size_val = tk.StringVar(value="30 pt")
        ttk.Label(right, textvariable=self.size_val, style="Val.TLabel").grid(row=6, padx=12, sticky="w")

        ttk.Label(right, text="不透明度", style="Lab.TLabel").grid(row=7, **pad)
        self.op_var = tk.DoubleVar(value=12)
        ttk.Scale(right, from_=5, to=50, variable=self.op_var,
                  command=lambda v: self._on_change()).grid(row=8, **pad)
        self.op_val = tk.StringVar(value="12 %")
        ttk.Label(right, textvariable=self.op_val, style="Val.TLabel").grid(row=9, padx=12, sticky="w")

        ttk.Label(right, text="角度", style="Lab.TLabel").grid(row=10, **pad)
        self.ang_var = tk.DoubleVar(value=38)
        ttk.Scale(right, from_=0, to=90, variable=self.ang_var,
                  command=lambda v: self._on_change()).grid(row=11, **pad)
        self.ang_val = tk.StringVar(value="38 °")
        ttk.Label(right, textvariable=self.ang_val, style="Val.TLabel").grid(row=12, padx=12, sticky="w")

        ttk.Label(right, text="顏色", style="Lab.TLabel").grid(row=13, **pad)
        self.color_box = ttk.Combobox(right, values=list(COLORS.keys()),
                                      state="readonly", font=("Microsoft JhengHei", 9))
        self.color_box.current(0)
        self.color_box.grid(row=14, **pad)

        ttk.Label(right, text="平鋪密度", style="Lab.TLabel").grid(row=15, **pad)
        self.den_var = tk.DoubleVar(value=100)
        self.den_scale = ttk.Scale(right, from_=60, to=200, variable=self.den_var,
                                   command=lambda v: self._on_change())
        self.den_scale.grid(row=16, **pad)
        self.den_val = tk.StringVar(value="100 %")
        ttk.Label(right, textvariable=self.den_val, style="Val.TLabel").grid(row=17, padx=12, sticky="w")

        self.apply_btn = ttk.Button(right, text="套用並儲存", style="Big.TButton",
                                    command=self.on_apply)
        self.apply_btn.grid(row=18, padx=12, pady=(14, 2), sticky="we")
        ttk.Label(right, text="輸出：存在原檔旁，檔名加「浮水印」；原檔不會被改動。",
                  style="Hint.TLabel", wraplength=250).grid(row=19, padx=12, pady=(4, 8), sticky="w")
        right.columnconfigure(0, weight=1)

        # 底部狀態列
        self.status_var = tk.StringVar(value="就緒")
        status = ttk.Label(self, textvariable=self.status_var, relief="sunken",
                           anchor="w", font=("Microsoft JhengHei", 8))
        status.place(x=10, y=656, width=1160, height=22)
        font_name = os.path.basename(self.fontfile) if self.fontfile else "未找到中文字體！"
        self.status_var.set("就緒｜浮水印字體：" + font_name)
        if not self.fontfile:
            messagebox.showwarning("PDF 浮水印工具", "找不到可用的中文字體，浮水印文字可能無法顯示。")

        if DND_FILES:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self.on_drop)

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
            self.canvas.create_text(cw / 2, ch / 2, fill="#c8ccd4",
                                    font=("Microsoft JhengHei", 12),
                                    text="把 PDF 拖進視窗，或按左邊「新增 PDF」\n\n任何設定改動都會即時預覽")
            return
        if self.doc is None:
            self.page_var.set("—")
            self.canvas.create_text(cw / 2, ch / 2, fill="#e8a0a0",
                                    font=("Microsoft JhengHei", 11),
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
                                    font=("Microsoft JhengHei", 10),
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
