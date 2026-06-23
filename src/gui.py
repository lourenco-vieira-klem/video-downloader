#!/usr/bin/env python3
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox


def _register_embedded_binaries():
    # When running as a frozen .exe (PyInstaller), the embedded binaries
    # (ffmpeg, ffprobe, deno) are extracted to a temp folder. Add it to PATH so
    # shutil.which and yt-dlp find them, making the executable self-contained.
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")


_register_embedded_binaries()

try:
    import yt_dlp
except ImportError:
    raise SystemExit(
        "yt-dlp não instalado. Ative a venv e rode: pip install -r requirements.txt"
    )

try:
    from PIL import Image, ImageDraw, ImageTk
except ImportError:
    raise SystemExit(
        "Pillow não instalado. Ative a venv e rode: pip install -r requirements.txt"
    )

from youtube_downloader import (
    build_options,
    default_downloads_dir,
    ensure_js_runtime,
)


# --------------------------------------------------------------------- palette
# Hex approximations of the redesign's OKLCH colors (dark purple/pink theme).
C = {
    "bg_page":      "#141318",
    "bg_window":    "#1d1c24",
    "surface":      "#26242f",
    "surface2":     "#2e2c3a",
    "border":       "#3a3848",
    "border_soft":  "#322f3e",
    "text":         "#f3f2f6",
    "text_mut":     "#aaa7b8",
    "text_dim":     "#7c7989",
    "green":        "#5dd9a0",
    "red":          "#f4796b",
    "cyan":         "#7fd8e8",
    "yellow":       "#f1d36b",
    "console_bg":   "#121117",
    "accent1":      "#8b5cf6",
    "accent2":      "#ec4899",
}

# Maps a friendly quality label to the yt-dlp selector.
QUALITIES = {
    "Melhor disponível (bv*)": "bv*",
    "2160p (4K)":              "bv*[height<=2160]",
    "1080p":                   "bv*[height<=1080]",
    "720p":                    "bv*[height<=720]",
    "480p":                    "bv*[height<=480]",
}


# ----------------------------------------------------------------- utilities
def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lerp(c1: str, c2: str, t: float) -> str:
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(a[i] + (b[i] - a[i]) * t for i in range(3))


def _brighten(h: str, f: float) -> str:
    # f>0 lightens, f<0 darkens.
    return _lerp(h, "#ffffff" if f >= 0 else "#000000", abs(f))


_SS = 4  # supersampling factor for corner anti-aliasing


def _gradient_image(w: int, h: int, c1: str, c2: str) -> "Image.Image":
    # Horizontal c1->c2 gradient as an RGB image.
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    if c1 == c2:
        return Image.new("RGB", (w, h), a)
    row = Image.new("RGB", (w, 1))
    px = row.load()
    for x in range(w):
        t = x / max(1, w - 1)
        px[x, 0] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    return row.resize((w, h))


def _round_rect_photo(w, h, r, c1, c2, border=None):
    # Rounded rectangle with gradient and anti-aliased edges.
    ss = _SS
    W, H, R = w * ss, h * ss, int(r * ss)
    grad = _gradient_image(W, H, c1, c2).convert("RGBA")
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=255)
    grad.putalpha(mask)
    if border:
        ImageDraw.Draw(grad).rounded_rectangle(
            [0, 0, W - 1, H - 1], radius=R, outline=_hex_to_rgb(border) + (255,),
            width=max(1, ss))
    return ImageTk.PhotoImage(grad.resize((w, h), Image.LANCZOS))


# ----------------------------------------------------------------- components
class RoundedButton(tk.Canvas):
    # Rounded button with anti-aliased corners (rendered via Pillow).

    def __init__(self, master, text, command, *, colors=None, fill=None,
                 fg="white", font=None, icon=None, height=40, pad_x=20,
                 min_width=0, border=None):
        bg = master["bg"]
        super().__init__(master, height=height, bg=bg, highlightthickness=0, bd=0)
        self._command = command
        self._text = text
        self._icon = icon
        self._fg = fg
        self._font = font
        self._height = height
        self._radius = 11
        self._border = border
        self._enabled = True
        self._hover = False
        self._imgs = {}

        if colors:
            self._c1, self._c2 = colors
        else:
            self._c1 = self._c2 = fill or C["surface2"]

        label = (icon + "  " if icon else "") + text
        tw = (font.measure(label) if font else len(label) * 8)
        self._cw = max(min_width, tw + 2 * pad_x)
        self.config(width=self._cw)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.after(0, self._render)

    def _image(self, key):
        if key not in self._imgs:
            if key == "disabled":
                c1 = c2 = C["surface"]
            elif key == "hover":
                c1 = _brighten(self._c1, 0.08)
                c2 = _brighten(self._c2, 0.08)
            else:
                c1, c2 = self._c1, self._c2
            self._imgs[key] = _round_rect_photo(
                self._cw, self._height, self._radius, c1, c2,
                border=self._border)
        return self._imgs[key]

    def _render(self):
        self.delete("all")
        key = "disabled" if not self._enabled else (
            "hover" if self._hover else "normal")
        self.create_image(0, 0, anchor="nw", image=self._image(key))
        fg = C["text_dim"] if not self._enabled else self._fg
        label = (self._icon + "  " if self._icon else "") + self._text
        self.create_text(self._cw / 2, self._height / 2, text=label,
                         fill=fg, font=self._font)

    def _on_enter(self, _):
        if self._enabled:
            self._hover = True
            self.config(cursor="hand2")
            self._render()

    def _on_leave(self, _):
        self._hover = False
        self.config(cursor="")
        self._render()

    def _on_press(self, _):
        if self._enabled:
            self.move("all", 0, 1)

    def _on_release(self, _):
        if self._enabled:
            self._render()
            if self._command:
                self._command()

    def set_enabled(self, value: bool):
        self._enabled = value
        self._hover = False
        self._render()


class ToggleSwitch(tk.Canvas):
    # iOS-style switch with anti-aliased corners and knob (Pillow).

    W, H = 44, 24

    def __init__(self, master, command=None, value=False):
        super().__init__(master, width=self.W, height=self.H,
                         bg=master["bg"], highlightthickness=0, bd=0)
        self._on = value
        self._command = command
        self._imgs = {}
        self.bind("<Button-1>", self._toggle)
        self.config(cursor="hand2")
        self.after(0, self._render)

    def _build(self, on):
        ss = _SS
        W, H = self.W * ss, self.H * ss
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if on:
            track = _gradient_image(
                W, H, C["accent1"], C["accent2"]).convert("RGBA")
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, W - 1, H - 1], radius=H // 2, fill=255)
            track.putalpha(mask)
            img = Image.alpha_composite(img, track)
        else:
            ImageDraw.Draw(img).rounded_rectangle(
                [0, 0, W - 1, H - 1], radius=H // 2,
                fill=_hex_to_rgb(C["border"]) + (255,))
        m = 2.5 * ss
        kr = H - 2 * m
        kx = (W - m - kr) if on else m
        ImageDraw.Draw(img).ellipse(
            [kx, m, kx + kr, m + kr], fill=(255, 255, 255, 255))
        return ImageTk.PhotoImage(img.resize((self.W, self.H), Image.LANCZOS))

    def _render(self):
        if self._on not in self._imgs:
            self._imgs[self._on] = self._build(self._on)
        self.delete("all")
        self.create_image(0, 0, anchor="nw", image=self._imgs[self._on])

    def _toggle(self, _=None):
        self._on = not self._on
        self._render()
        if self._command:
            self._command(self._on)

    def get(self) -> bool:
        return self._on


class GradientBar(tk.Canvas):
    # Rounded, anti-aliased gradient progress bar.

    def __init__(self, master, height=10):
        super().__init__(master, height=height, bg=master["bg"],
                         highlightthickness=0, bd=0)
        self._h = height
        self._pct = 0.0
        self._photo = None
        self.bind("<Configure>", lambda e: self._render())

    def set(self, pct: float):
        self._pct = max(0.0, min(100.0, pct))
        self._render()

    def _render(self):
        self.delete("all")
        w = self.winfo_width()
        if w <= 1:
            return
        ss = _SS
        W, H, R = w * ss, self._h * ss, (self._h * ss) // 2
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle(
            [0, 0, W - 1, H - 1], radius=R,
            fill=_hex_to_rgb(C["surface2"]) + (255,))
        fw = int(W * self._pct / 100)
        if fw > R:
            grad = _gradient_image(
                W, H, C["accent1"], C["accent2"]).convert("RGBA")
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                [0, 0, fw - 1, H - 1], radius=R, fill=255)
            grad.putalpha(mask)
            img = Image.alpha_composite(img, grad)
        self._photo = ImageTk.PhotoImage(img.resize((w, self._h), Image.LANCZOS))
        self.create_image(0, 0, anchor="nw", image=self._photo)


class AppMark(tk.Canvas):
    # Logo: rounded square with gradient and a download arrow (Pillow).

    def __init__(self, master, size=46):
        super().__init__(master, width=size, height=size, bg=master["bg"],
                         highlightthickness=0, bd=0)
        ss = _SS
        S = size * ss
        img = _gradient_image(S, S, C["accent1"], C["accent2"]).convert("RGBA")
        mask = Image.new("L", (S, S), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, S - 1, S - 1], radius=int(13 * ss), fill=255)
        img.putalpha(mask)
        d = ImageDraw.Draw(img)
        cx = S / 2
        lw = max(2, int(2.2 * ss))
        white = (255, 255, 255, 255)
        d.line([(cx, S * 0.26), (cx, S * 0.58)], fill=white, width=lw,
               joint="curve")
        d.line([(cx - S * 0.13, S * 0.45), (cx, S * 0.58)], fill=white, width=lw)
        d.line([(cx + S * 0.13, S * 0.45), (cx, S * 0.58)], fill=white, width=lw)
        d.line([(S * 0.28, S * 0.74), (S * 0.72, S * 0.74)], fill=white, width=lw)
        self._photo = ImageTk.PhotoImage(img.resize((size, size), Image.LANCZOS))
        self.create_image(0, 0, anchor="nw", image=self._photo)


# ------------------------------------------------------------------ logging
class GuiLogger:
    # yt-dlp logger that forwards messages to the GUI queue.

    def __init__(self, msg_queue: queue.Queue):
        self.msg_queue = msg_queue

    def debug(self, msg):
        if msg.startswith("[debug]"):
            return
        self.msg_queue.put(("log", msg))

    def info(self, msg):
        self.msg_queue.put(("log", msg))

    def warning(self, msg):
        self.msg_queue.put(("log", "⚠  " + msg))

    def error(self, msg):
        self.msg_queue.put(("log", "✕ ERROR " + msg))


# --------------------------------------------------------------------- App
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("760x880")
        self.minsize(680, 760)
        self.configure(bg=C["bg_page"])

        self.msg_queue: queue.Queue = queue.Queue()
        self.download_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self._downloading = False
        self._pulse_on = True

        self._init_fonts()
        self._build_widgets()
        self._check_ffmpeg()
        self._check_js_runtime()
        self._update_link_count()
        self.after(100, self._process_queue)
        self._pulse()

    # ----------------------------------------------------------------- fonts
    def _init_fonts(self):
        self.f_ui = tkfont.Font(family="Segoe UI", size=10)
        self.f_ui_b = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_small = tkfont.Font(family="Segoe UI", size=9)
        self.f_small_b = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self.f_title = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        self.f_mono = tkfont.Font(family="Consolas", size=10)
        self.f_pct = tkfont.Font(family="Segoe UI", size=14, weight="bold")

    # -------------------------------------------------------------- builders
    def _card(self, parent):
        return tk.Frame(parent, bg=C["surface"], highlightthickness=1,
                        highlightbackground=C["border_soft"], bd=0)

    def _entry(self, parent, textvariable):
        e = tk.Entry(parent, textvariable=textvariable, bg=C["surface2"],
                     fg=C["text"], insertbackground=C["text"], relief="flat",
                     font=self.f_mono, highlightthickness=1, bd=0,
                     highlightbackground=C["border"], highlightcolor=C["accent1"])
        return e

    def _lbl(self, parent, text, font=None, fg=None):
        return tk.Label(parent, text=text, bg=parent["bg"],
                        fg=fg or C["text"], font=font or self.f_ui)

    # ----------------------------------------------------------------- layout
    def _build_widgets(self):
        root = tk.Frame(self, bg=C["bg_page"])
        root.pack(fill="both", expand=True, padx=26, pady=24)

        # ---- Header --------------------------------------------------------
        head = tk.Frame(root, bg=C["bg_page"])
        head.pack(fill="x", pady=(0, 18))
        AppMark(head).pack(side="left")
        htxt = tk.Frame(head, bg=C["bg_page"])
        htxt.pack(side="left", padx=14)
        self._lbl(htxt, "YouTube Downloader", self.f_title).pack(anchor="w")
        self._lbl(htxt, "Baixe vídeos, áudio e legendas em lote",
                  self.f_small, C["text_mut"]).pack(anchor="w")

        # ---- Card: Links ---------------------------------------------------
        c_links = self._card(root)
        c_links.pack(fill="x", pady=(0, 16))
        inner = tk.Frame(c_links, bg=C["surface"])
        inner.pack(fill="x", padx=20, pady=18)

        row = tk.Frame(inner, bg=C["surface"])
        row.pack(fill="x", pady=(0, 10))
        self._lbl(row, "Links do YouTube", self.f_ui_b).pack(side="left")
        self.lbl_badge = tk.Label(row, text="0 links", bg="#2c2640",
                                  fg=_brighten(C["accent1"], 0.35),
                                  font=self.f_small_b, padx=9, pady=2)
        self.lbl_badge.pack(side="right")

        self.txt_urls = tk.Text(inner, height=4, wrap="none", bg=C["surface2"],
                                fg=C["cyan"], insertbackground=C["text"],
                                relief="flat", font=self.f_mono,
                                highlightthickness=1, bd=0, padx=12, pady=10,
                                highlightbackground=C["border"],
                                highlightcolor=C["accent1"])
        self.txt_urls.pack(fill="x")
        self.txt_urls.bind("<KeyRelease>", lambda e: self._update_link_count())
        self.txt_urls.bind("<<Paste>>",
                           lambda e: self.after(10, self._update_link_count))
        self._lbl(inner, "Um link por linha — playlists são expandidas "
                  "automaticamente", self.f_small, C["text_dim"]).pack(
                      anchor="w", pady=(9, 0))

        # ---- Card: Options -------------------------------------------------
        c_opt = self._card(root)
        c_opt.pack(fill="x", pady=(0, 16))
        opt = tk.Frame(c_opt, bg=C["surface"])
        opt.pack(fill="x", padx=20, pady=18)

        # Destination folder
        self._lbl(opt, "Pasta de destino", self.f_small_b).pack(anchor="w",
                                                                pady=(0, 7))
        dest = tk.Frame(opt, bg=C["surface"])
        dest.pack(fill="x", pady=(0, 14))
        self.var_dest = tk.StringVar(value=str(default_downloads_dir()))
        e_dest = self._entry(dest, self.var_dest)
        e_dest.pack(side="left", fill="x", expand=True, ipady=6)
        RoundedButton(dest, "Procurar", self._choose_folder, icon="🗁",
                      fill=C["surface2"], fg=C["text_mut"], font=self.f_ui,
                      height=34, pad_x=14, border=C["border"]).pack(
                          side="left", padx=(8, 0))

        # 2-column grid
        grid = tk.Frame(opt, bg=C["surface"])
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="g")
        grid.columnconfigure(1, weight=1, uniform="g")

        # Quality
        f_q = tk.Frame(grid, bg=C["surface"])
        f_q.grid(row=0, column=0, sticky="ew", padx=(0, 7), pady=(0, 12))
        self._lbl(f_q, "Qualidade do vídeo", self.f_small_b).pack(anchor="w",
                                                                  pady=(0, 7))
        self.var_quality = tk.StringVar(value="Melhor disponível (bv*)")
        om = tk.OptionMenu(f_q, self.var_quality, *QUALITIES.keys())
        om.config(bg=C["surface2"], fg=C["text"], activebackground=C["surface"],
                  activeforeground=C["text"], font=self.f_ui, relief="flat",
                  bd=0, highlightthickness=1, highlightbackground=C["border"],
                  anchor="w", padx=12, pady=6, indicatoron=0)
        om["menu"].config(bg=C["surface2"], fg=C["text"], bd=0,
                          activebackground=C["accent1"], activeforeground="white")
        om.pack(fill="x")

        # Subtitle languages
        f_l = tk.Frame(grid, bg=C["surface"])
        f_l.grid(row=0, column=1, sticky="ew", padx=(7, 0), pady=(0, 12))
        self._lbl(f_l, "Idiomas de legenda", self.f_small_b).pack(anchor="w",
                                                                  pady=(0, 7))
        self.var_langs = tk.StringVar(value="all")
        self._entry(f_l, self.var_langs).pack(fill="x", ipady=6)

        # Switch: automatic subtitles
        self.sw_auto = self._switch_row(
            grid, "Legendas automáticas", "Geradas pelo YouTube")
        self.sw_auto["frame"].grid(row=1, column=0, sticky="ew", padx=(0, 7))

        # Switch: audio only
        self.sw_audio = self._switch_row(
            grid, "Apenas áudio", "Extrai .mka sem vídeo")
        self.sw_audio["frame"].grid(row=1, column=1, sticky="ew", padx=(7, 0))

        # ---- Actions -------------------------------------------------------
        actions = tk.Frame(root, bg=C["bg_page"])
        actions.pack(fill="x", pady=(0, 16))
        self.btn_download = RoundedButton(
            actions, "Baixar", self._start_download, icon="⭳",
            colors=(C["accent1"], C["accent2"]), font=self.f_ui_b, pad_x=24)
        self.btn_download.pack(side="left")
        self.btn_cancel = RoundedButton(
            actions, "Cancelar", self._cancel, icon="✕", fill=C["surface2"],
            fg=C["text"], font=self.f_ui_b, border=C["border"])
        self.btn_cancel.pack(side="left", padx=10)
        self.btn_cancel.set_enabled(False)
        RoundedButton(actions, "Abrir pasta", self._open_folder, icon="🗁",
                      fill=C["surface2"], fg=C["text"], font=self.f_ui_b,
                      border=C["border"]).pack(side="right")

        # ---- Card: Progress ------------------------------------------------
        c_prog = self._card(root)
        c_prog.pack(fill="x", pady=(0, 16))
        prog = tk.Frame(c_prog, bg=C["surface"])
        prog.pack(fill="x", padx=20, pady=18)

        top = tk.Frame(prog, bg=C["surface"])
        top.pack(fill="x", pady=(0, 12))
        pill = tk.Frame(top, bg="#1f3a2e")
        pill.pack(side="left")
        self.dot_pulse = tk.Label(pill, text="●", bg="#1f3a2e",
                                  fg=C["green"], font=self.f_small)
        self.dot_pulse.pack(side="left", padx=(9, 4), pady=2)
        self.lbl_status_pill = tk.Label(pill, text="Pronto", bg="#1f3a2e",
                                        fg=_brighten(C["green"], 0.2),
                                        font=self.f_small_b, padx=0, pady=2)
        self.lbl_status_pill.pack(side="left", padx=(0, 10))

        self.lbl_prog_title = tk.Label(top, text="Aguardando início…",
                                       bg=C["surface"], fg=C["text"],
                                       font=self.f_ui, anchor="w")
        self.lbl_prog_title.pack(side="left", fill="x", expand=True, padx=12)
        self.lbl_pct = tk.Label(top, text="0%", bg=C["surface"], fg=C["text"],
                                font=self.f_pct)
        self.lbl_pct.pack(side="right")

        self.bar = GradientBar(prog)
        self.bar.pack(fill="x", pady=(0, 12))

        self.lbl_meta = tk.Label(prog, text="—", bg=C["surface"],
                                 fg=C["text_mut"], font=self.f_small_b,
                                 anchor="w")
        self.lbl_meta.pack(fill="x")

        # ---- Card: Console -------------------------------------------------
        c_con = tk.Frame(root, bg=C["console_bg"], highlightthickness=1,
                         highlightbackground=C["border_soft"], bd=0)
        c_con.pack(fill="both", expand=True)

        chead = tk.Frame(c_con, bg="#191820")
        chead.pack(fill="x")
        tk.Label(chead, text="●  Registro", bg="#191820", fg=C["text_mut"],
                 font=self.f_small_b).pack(side="left", padx=15, pady=10)
        RoundedButton(chead, "Limpar", self._clear_log, fill="#191820",
                      fg=C["text_dim"], font=self.f_small, height=26, pad_x=10,
                      border=C["border_soft"]).pack(side="right", padx=(0, 12),
                                                    pady=7)
        RoundedButton(chead, "Copiar", self._copy_log, fill="#191820",
                      fg=C["text_dim"], font=self.f_small, height=26, pad_x=10,
                      border=C["border_soft"]).pack(side="right", padx=4, pady=7)

        cbody = tk.Frame(c_con, bg=C["console_bg"])
        cbody.pack(fill="both", expand=True)
        self.txt_log = tk.Text(cbody, height=8, wrap="word", state="disabled",
                               bg=C["console_bg"], fg=C["text_dim"],
                               relief="flat", font=self.f_mono, bd=0,
                               padx=15, pady=12, spacing1=2, spacing3=2,
                               highlightthickness=0)
        self.txt_log.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(cbody, command=self.txt_log.yview)
        sb.pack(side="right", fill="y")
        self.txt_log["yscrollcommand"] = sb.set

        for tag, col in (("cyan", C["cyan"]), ("green", C["green"]),
                         ("red", C["red"]), ("yellow", C["yellow"]),
                         ("mut", C["text_mut"]), ("dim", C["text_dim"])):
            self.txt_log.tag_config(tag, foreground=col)

    def _switch_row(self, parent, title, sub):
        f = tk.Frame(parent, bg=C["surface2"], highlightthickness=1,
                     highlightbackground=C["border"], bd=0)
        inner = tk.Frame(f, bg=C["surface2"])
        inner.pack(fill="x", padx=13, pady=9)
        txt = tk.Frame(inner, bg=C["surface2"])
        txt.pack(side="left")
        tk.Label(txt, text=title, bg=C["surface2"], fg=C["text"],
                 font=self.f_small_b).pack(anchor="w")
        tk.Label(txt, text=sub, bg=C["surface2"], fg=C["text_dim"],
                 font=self.f_small).pack(anchor="w")
        sw = ToggleSwitch(inner)
        sw.pack(side="right")
        return {"frame": f, "switch": sw}

    # -------------------------------------------------------------- helpers
    def _update_link_count(self):
        n = len([u for u in self.txt_urls.get("1.0", "end").splitlines()
                 if u.strip()])
        self.lbl_badge.config(text=f"{n} link" + ("s" if n != 1 else ""))

    def _check_ffmpeg(self):
        if shutil.which("ffmpeg") is None:
            self._log("⚠  FFmpeg não encontrado no PATH. Ele é obrigatório "
                      "para juntar áudios e legendas.", "yellow")
            messagebox.showwarning(
                "FFmpeg ausente",
                "O FFmpeg não foi encontrado no PATH.\n\n"
                "Instale com:  winget install Gyan.FFmpeg\n"
                "Sem ele não é possível embutir múltiplas faixas.")

    def _check_js_runtime(self):
        if ensure_js_runtime():
            self._log("✓ Runtime JS (Deno) detectado — extração do YouTube OK.",
                      "green")
        else:
            self._log("⚠  Runtime JS (Deno) não encontrado. O YouTube exige um "
                      "para extrair os vídeos.", "yellow")
            messagebox.showwarning(
                "Runtime JS ausente (Deno)",
                "O yt-dlp precisa de um runtime JavaScript (Deno) para extrair "
                "vídeos do YouTube. Sem ele, aparece 'This video is not "
                "available'.\n\n"
                "Instale com:  winget install DenoLand.Deno\n"
                "e reabra este programa.")

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.var_dest.get())
        if folder:
            self.var_dest.set(folder)

    def _open_folder(self):
        dest = Path(self.var_dest.get())
        dest.mkdir(parents=True, exist_ok=True)
        os.startfile(dest)  # Windows

    def _copy_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_log.get("1.0", "end"))

    def _clear_log(self):
        self.txt_log["state"] = "normal"
        self.txt_log.delete("1.0", "end")
        self.txt_log["state"] = "disabled"

    def _classify(self, msg: str) -> str:
        m = msg.strip()
        low = m.lower()
        if m.startswith("✕") or "error" in low and "✓" not in m:
            return "red"
        if m.startswith("✓") or "finished" in low or "has already been" in low \
                or "concluí" in low:
            return "green"
        if m.startswith("⚠") or "warning" in low:
            return "yellow"
        if "%" in m and "[download]" in low:
            return "yellow"
        if m.startswith("[youtube") or m.startswith("[info") \
                or m.startswith("[download"):
            return "cyan"
        return "dim"

    def _log(self, msg: str, tag: str | None = None):
        self.txt_log["state"] = "normal"
        self.txt_log.insert("end", msg + "\n", tag or self._classify(msg))
        self.txt_log.see("end")
        self.txt_log["state"] = "disabled"

    def _set_status(self, text: str, color: str, bg: str, downloading: bool):
        self._downloading = downloading
        self.lbl_status_pill.config(text=text, fg=_brighten(color, 0.2), bg=bg)
        self.dot_pulse.config(fg=color, bg=bg)
        self.lbl_status_pill.master.config(bg=bg)

    def _pulse(self):
        if self._downloading:
            self._pulse_on = not self._pulse_on
            self.dot_pulse.config(
                fg=C["green"] if self._pulse_on else "#1f3a2e")
        self.after(700, self._pulse)

    # ------------------------------------------------------------ download
    def _start_download(self):
        urls = [u.strip() for u in self.txt_urls.get("1.0", "end").splitlines()
                if u.strip()]
        if not urls:
            messagebox.showerror("Sem URL", "Informe ao menos uma URL.")
            return

        dest = Path(self.var_dest.get()).expanduser()
        dest.mkdir(parents=True, exist_ok=True)

        options = build_options(
            dest=dest,
            langs=self.var_langs.get(),
            auto_subs=self.sw_auto["switch"].get(),
            audio_only=self.sw_audio["switch"].get(),
            quality=QUALITIES.get(self.var_quality.get(), "bv*"),
        )
        options["logger"] = GuiLogger(self.msg_queue)
        options["progress_hooks"] = [self._progress_hook]
        options["quiet"] = True
        options["no_warnings"] = False

        self.cancel_event.clear()
        self.btn_download.set_enabled(False)
        self.btn_cancel.set_enabled(True)
        self.bar.set(0)
        self.lbl_pct.config(text="0%")
        self._set_status("Baixando", C["green"], "#1f3a2e", True)
        self.lbl_prog_title.config(text="Preparando…")
        self._log(f"▶ Iniciando {len(urls)} download(s)…", "cyan")

        self.download_thread = threading.Thread(
            target=self._worker, args=(urls, options), daemon=True)
        self.download_thread.start()

    def _worker(self, urls, options):
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download(urls)
            self.msg_queue.put(("done", "✅ Concluído!"))
        except yt_dlp.utils.DownloadCancelled:
            self.msg_queue.put(("done", "✖ Cancelado pelo usuário."))
        except Exception as e:  # noqa: BLE001
            self.msg_queue.put(("done", f"❌ Erro: {e}"))

    def _progress_hook(self, d):
        if self.cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled()
        self.msg_queue.put(("progress", d))

    def _cancel(self):
        self.cancel_event.set()
        self._set_status("Cancelando", C["yellow"], "#3a341f", False)

    # --------------------------------------------------- message loop
    def _process_queue(self):
        try:
            while True:
                kind, data = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(data)
                elif kind == "progress":
                    self._update_progress(data)
                elif kind == "done":
                    self._finish(data)
        except queue.Empty:
            pass
        self.after(100, self._process_queue)

    def _update_progress(self, d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                pct = downloaded / total * 100
                self.bar.set(pct)
                self.lbl_pct.config(text=f"{pct:.0f}%")
            name = Path(d.get("filename", "")).name
            self.lbl_prog_title.config(text=name or "Baixando…")
            speed = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            size = ""
            if total:
                size = f"{downloaded / 1048576:.0f} / {total / 1048576:.0f} MB"
            parts = [p for p in (speed, f"faltam {eta}" if eta else "", size) if p]
            self.lbl_meta.config(text="    ·    ".join(parts) or "—")
        elif status == "finished":
            self.bar.set(100)
            self.lbl_pct.config(text="100%")
            self._set_status("Processando", C["cyan"], "#1f323a", True)
            self.lbl_prog_title.config(text="Juntando faixas (FFmpeg)…")
            self._log(f"✓ Baixado: {Path(d.get('filename', '')).name}", "green")

    def _finish(self, msg):
        success = msg.startswith("✅")
        self._log(msg, "green" if success else "red")
        self.btn_download.set_enabled(True)
        self.btn_cancel.set_enabled(False)
        if success:
            self.bar.set(100)
            self.lbl_pct.config(text="100%")
            self._set_status("Concluído", C["green"], "#1f3a2e", False)
            self.lbl_prog_title.config(text="Todos os downloads finalizados")
        else:
            self._set_status("Parado", C["red"], "#3a2020", False)
            self.lbl_prog_title.config(text=msg)


if __name__ == "__main__":
    App().mainloop()
