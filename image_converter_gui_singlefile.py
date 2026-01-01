import io
import os
import time
import zipfile
import threading
import urllib.request
import webbrowser
from dataclasses import dataclass
from typing import Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageOps

MAX_WIDTH = 3840
MAX_HEIGHT = 2160

OUTPUTS = [
    ("PNG", "png"),
    ("JPG", "jpg"),
    ("JPEG", "jpeg"),
    ("WEBP", "webp"),
    ("BMP", "bmp"),
    ("TIFF", "tiff"),
    ("ICO (128x128)", "ico"),
    ("PDF (single)", "pdf"),
]

MODES = [
    ("Fit (คงสัดส่วน)", "fit"),
    ("Stretch (ยืดตามขนาด)", "stretch"),
    ("Fill (ครอปกลาง)", "fill"),
]


def ts_base() -> str:
    return time.strftime("%Y-%m-%dT%H-%M-%S", time.localtime())


def sanitize_name(name: str) -> str:
    keep = "._-"
    out = []
    for ch in name:
        if ch.isalnum() or ch in keep:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "image"


def parse_int_or_none(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        v = int(s)
        return v if v > 0 else None
    except ValueError:
        return None


def clamp_size(w: int, h: int) -> Tuple[int, int]:
    return min(w, MAX_WIDTH), min(h, MAX_HEIGHT)


@dataclass
class ImageEntry:
    label: str       # path or [URL] ...
    base_name: str
    image: Image.Image


def resize_image(im: Image.Image, width, height, mode: str) -> Image.Image:
    ow, oh = im.size
    w, h = width, height

    if w is None and h is None:
        tw, th = clamp_size(ow, oh)
        if (tw, th) == (ow, oh):
            return im.copy()
        return im.resize((tw, th), Image.LANCZOS)

    if mode == "stretch":
        if w is None and h is not None:
            w = max(1, round(ow * (h / oh)))
        if h is None and w is not None:
            h = max(1, round(oh * (w / ow)))
        tw, th = clamp_size(w or ow, h or oh)
        return im.resize((tw, th), Image.LANCZOS)

    if mode == "fit":
        box_w = min(w if w is not None else MAX_WIDTH, MAX_WIDTH)
        box_h = min(h if h is not None else MAX_HEIGHT, MAX_HEIGHT)
        scale = min(box_w / ow, box_h / oh)
        tw = max(1, round(ow * scale))
        th = max(1, round(oh * scale))
        return im.resize((tw, th), Image.LANCZOS)

    # fill
    box_w = min(w if w is not None else MAX_WIDTH, MAX_WIDTH)
    box_h = min(h if h is not None else MAX_HEIGHT, MAX_HEIGHT)
    scale = max(box_w / ow, box_h / oh)
    tw = max(1, round(ow * scale))
    th = max(1, round(oh * scale))
    resized = im.resize((tw, th), Image.LANCZOS)
    left = (tw - box_w) // 2
    top = (th - box_h) // 2
    return resized.crop((left, top, left + box_w, top + box_h))


def to_rgb_if_needed(im: Image.Image, ext: str) -> Image.Image:
    if ext in ("jpg", "jpeg", "bmp") and im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (0, 0, 0))
        rgba = im.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im


def make_ico_128(im: Image.Image) -> Image.Image:
    size = 128
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    fitted = ImageOps.contain(im.convert("RGBA"), (size, size), Image.LANCZOS)
    x = (size - fitted.size[0]) // 2
    y = (size - fitted.size[1]) // 2
    canvas.paste(fitted, (x, y), fitted)
    return canvas


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Converter (Single File)")
        self.geometry("720x380")
        self.minsize(680, 360)

        self.selected: Optional[ImageEntry] = None

        self.output_ext = tk.StringVar(value="png")
        self.quality = tk.DoubleVar(value=0.90)

        self.resize_w = tk.StringVar(value="")
        self.resize_h = tk.StringVar(value="")
        self.resize_mode = tk.StringVar(value="fit")

        self.selected_text = tk.StringVar(value="(ยังไม่ได้เลือกไฟล์)")

        self._build_ui()
        self._refresh_state()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)

        # Header
        header = ttk.Frame(root)
        header.pack(fill="x")
        ttk.Label(header, text="Image Converter", font=("Segoe UI", 14, "bold")).pack(side="left")
        ttk.Button(header, text="รายละเอียด", command=self.show_details).pack(side="right")

        ttk.Label(root, text="เลือกไฟล์ 1 ไฟล์เท่านั้น → ตั้งค่า → Convert", foreground="#555").pack(fill="x", pady=(2, 10))

        # Input box (small)
        input_box = ttk.LabelFrame(root, text="ไฟล์ (เลือกได้ทีละ 1)")
        input_box.pack(fill="x")

        row1 = ttk.Frame(input_box)
        row1.pack(fill="x", padx=8, pady=8)

        ttk.Button(row1, text="เลือกไฟล์...", command=self.pick_file).pack(side="left")
        ttk.Button(row1, text="ล้างไฟล์", command=self.clear_file).pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(input_box)
        row2.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(row2, text="ไฟล์ที่เลือก:").pack(side="left")

        self.sel_entry = ttk.Entry(row2, textvariable=self.selected_text, state="readonly")
        self.sel_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

        # URL row (optional)
        url_row = ttk.Frame(input_box)
        url_row.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(url_row, text="URL:").pack(side="left")
        self.url_entry = ttk.Entry(url_row)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(url_row, text="โหลดจาก URL", command=self.load_from_url).pack(side="left")

        # Settings
        settings = ttk.LabelFrame(root, text="ตั้งค่า")
        settings.pack(fill="x", pady=10)

        grid = ttk.Frame(settings)
        grid.pack(fill="x", padx=8, pady=8)

        ttk.Label(grid, text="Output:").grid(row=0, column=0, sticky="w")
        self.out_combo = ttk.Combobox(
            grid,
            values=[f"{name} (.{ext})" if ext != "ico" else "ICO (128x128)" for name, ext in OUTPUTS],
            state="readonly",
            width=18
        )
        self.out_combo.current(0)
        self.out_combo.grid(row=0, column=1, sticky="w", padx=(8, 18))
        self.out_combo.bind("<<ComboboxSelected>>", self._on_output_change)

        ttk.Label(grid, text="Quality:").grid(row=0, column=2, sticky="w")
        self.q_scale = ttk.Scale(grid, from_=0.10, to=1.0, variable=self.quality, command=self._update_quality_label)
        self.q_scale.grid(row=0, column=3, sticky="we", padx=(8, 8))
        grid.columnconfigure(3, weight=1)
        self.q_label = ttk.Label(grid, text=f"{self.quality.get():.2f}")
        self.q_label.grid(row=0, column=4, sticky="w")

        rrow = ttk.Frame(settings)
        rrow.pack(fill="x", padx=8, pady=(0, 8))

        ttk.Label(rrow, text="Resize (ว่างไว้ = ไม่ resize):").pack(side="left")

        ttk.Label(rrow, text="W").pack(side="left", padx=(10, 2))
        ttk.Entry(rrow, textvariable=self.resize_w, width=6).pack(side="left")
        ttk.Label(rrow, text="H").pack(side="left", padx=(8, 2))
        ttk.Entry(rrow, textvariable=self.resize_h, width=6).pack(side="left")

        ttk.Label(rrow, text="Mode").pack(side="left", padx=(10, 2))
        self.mode_combo = ttk.Combobox(rrow, values=[m[0] for m in MODES], state="readonly", width=16)
        self.mode_combo.pack(side="left")
        self.mode_combo.current(0)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        ttk.Label(settings, text=f"จำกัดขนาดสูงสุด {MAX_WIDTH}×{MAX_HEIGHT}", foreground="#666").pack(anchor="w", padx=8, pady=(0, 8))

        # Actions
        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(6, 0))

        self.btn_folder = ttk.Button(actions, text="Convert → บันทึกลงโฟลเดอร์", command=self.convert_to_folder, state="disabled")
        self.btn_folder.pack(side="left")

        self.btn_zip = ttk.Button(actions, text="Convert → บันทึกเป็น ZIP", command=self.convert_to_zip, state="disabled")
        self.btn_zip.pack(side="left", padx=8)

        self.status = ttk.Label(root, text="พร้อมใช้งาน", foreground="#555")
        self.status.pack(fill="x", pady=(10, 0))

    def show_details(self):
        # เปิดหน้าเว็บ (ปุ่มชื่อเดิม: รายละเอียด)
        webbrowser.open("https://thanawan230653.github.io/")

    def _set_status(self, text: str):
        self.status.config(text=text)

    def _update_quality_label(self, _=None):
        self.q_label.config(text=f"{self.quality.get():.2f}")

    def _on_mode_change(self, _=None):
        sel = self.mode_combo.get()
        for label, code in MODES:
            if sel == label:
                self.resize_mode.set(code)
                break

    def _on_output_change(self, _=None):
        idx = self.out_combo.current()
        ext = OUTPUTS[idx][1]
        self.output_ext.set(ext)
        if ext in ("ico", "pdf"):
            self.q_scale.state(["disabled"])
        else:
            self.q_scale.state(["!disabled"])

    def _refresh_state(self):
        has = self.selected is not None
        self.btn_folder.state(["!disabled"] if has else ["disabled"])
        self.btn_zip.state(["!disabled"] if has else ["disabled"])

    def clear_file(self):
        self.selected = None
        self.selected_text.set("(ยังไม่ได้เลือกไฟล์)")
        self._set_status("ล้างไฟล์แล้ว")
        self._refresh_state()

    def pick_file(self):
        path = filedialog.askopenfilename(
            title="เลือกไฟล์รูป (1 ไฟล์)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.ico"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            im = Image.open(path)
            im.load()
            name = os.path.basename(path)
            base = os.path.splitext(sanitize_name(name))[0]
            self.selected = ImageEntry(path, base, im.copy())
            self.selected_text.set(path)
            self._set_status("เลือกไฟล์แล้ว")
            self._refresh_state()
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"อ่านไฟล์ไม่สำเร็จ: {e}")

    def load_from_url(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("ผิดพลาด", "กรุณาใส่ URL รูปภาพ")
            return

        self._set_status("กำลังโหลดจาก URL...")

        def worker():
            try:
                with urllib.request.urlopen(url, timeout=20) as resp:
                    data = resp.read()
                im = Image.open(io.BytesIO(data))
                im.load()
                name_part = url.split("/")[-1].split("?")[0] or "url_image"
                name_part = sanitize_name(name_part)
                base = os.path.splitext(name_part)[0]
                self.selected = ImageEntry(f"[URL] {url}", base, im.copy())
                self.after(0, lambda: self.selected_text.set(f"[URL] {url}"))
                self.after(0, lambda: self._set_status("โหลดจาก URL แล้ว"))
                self.after(0, self._refresh_state)
            except Exception:
                self.after(0, lambda: messagebox.showerror("ผิดพลาด", "โหลดรูปจาก URL ไม่สำเร็จ (ลิงก์ไม่ใช่รูป/เน็ต/โดนบล็อก)"))
                self.after(0, lambda: self._set_status("พร้อมใช้งาน"))

        threading.Thread(target=worker, daemon=True).start()

    def _collect_resize(self):
        w = parse_int_or_none(self.resize_w.get())
        h = parse_int_or_none(self.resize_h.get())
        if w is not None:
            w = min(w, MAX_WIDTH)
        if h is not None:
            h = min(h, MAX_HEIGHT)
        mode = self.resize_mode.get() or "fit"
        return w, h, mode

    def _render(self):
        if not self.selected:
            raise RuntimeError("no input")

        idx = self.out_combo.current()
        ext = OUTPUTS[idx][1]
        self.output_ext.set(ext)

        w, h, mode = self._collect_resize()
        base_ts = ts_base()
        q = float(self.quality.get())

        ent = self.selected

        if ext == "ico":
            icon = make_ico_128(ent.image)
            buf = io.BytesIO()
            icon.save(buf, format="ICO", sizes=[(128, 128)])
            fn = f"{ent.base_name}_128x128_{base_ts}.ico"
            return fn, buf.getvalue()

        if ext == "pdf":
            out_im = resize_image(ent.image, w, h, mode)
            out_im = to_rgb_if_needed(out_im, "pdf").convert("RGB")
            buf = io.BytesIO()
            out_im.save(buf, format="PDF")
            size_hint = f"{w or 'auto'}x{h or 'auto'}"
            fn = f"{ent.base_name}_{size_hint}_{base_ts}.pdf"
            return fn, buf.getvalue()

        pil_format = {
            "png": "PNG",
            "jpg": "JPEG",
            "jpeg": "JPEG",
            "webp": "WEBP",
            "bmp": "BMP",
            "tiff": "TIFF",
        }[ext]

        save_kwargs = {}
        if ext in ("jpg", "jpeg"):
            save_kwargs["quality"] = max(1, min(95, int(q * 95)))
            save_kwargs["optimize"] = True
        if ext == "webp":
            save_kwargs["quality"] = max(1, min(100, int(q * 100)))

        out_im = resize_image(ent.image, w, h, mode)
        out_im = to_rgb_if_needed(out_im, ext)
        fn = f"{ent.base_name}_{out_im.width}x{out_im.height}_{base_ts}.{ext}"
        buf = io.BytesIO()
        out_im.save(buf, format=pil_format, **save_kwargs)
        return fn, buf.getvalue()

    def convert_to_folder(self):
        if not self.selected:
            return
        out_dir = filedialog.askdirectory(title="เลือกโฟลเดอร์ปลายทาง")
        if not out_dir:
            return
        try:
            self._set_status("กำลังแปลง...")
            fn, data = self._render()
            path = os.path.join(out_dir, fn)
            with open(path, "wb") as f:
                f.write(data)
            messagebox.showinfo("สำเร็จ", f"บันทึกแล้ว\n{path}")
            self._set_status("เสร็จแล้ว")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"แปลงไม่สำเร็จ: {e}")
            self._set_status("พร้อมใช้งาน")

    def convert_to_zip(self):
        if not self.selected:
            return
        default_name = f"converted_{ts_base()}.zip"
        out_path = filedialog.asksaveasfilename(
            title="บันทึก ZIP",
            defaultextension=".zip",
            initialfile=default_name,
            filetypes=[("ZIP", "*.zip")]
        )
        if not out_path:
            return
        try:
            self._set_status("กำลังแปลง...")
            fn, data = self._render()
            with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(fn, data)
            messagebox.showinfo("สำเร็จ", f"บันทึก ZIP แล้ว\n{out_path}")
            self._set_status("เสร็จแล้ว")
        except Exception as e:
            messagebox.showerror("ผิดพลาด", f"บันทึก ZIP ไม่สำเร็จ: {e}")
            self._set_status("พร้อมใช้งาน")


if __name__ == "__main__":
    Image.MAX_IMAGE_PIXELS = None
    App().mainloop()
