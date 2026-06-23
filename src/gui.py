#!/usr/bin/env python3
"""
GUI (Tkinter) para o YouTube Downloader — layout redesenhado.

Interface gráfica em tema escuro para baixar vídeos e playlists do YouTube
preservando TODAS as faixas de áudio e legendas num único arquivo .mkv.

O visual reproduz o redesign (cards, switches, badge de contagem, barra de
progresso com pílula de status e console colorido) dentro das possibilidades
do Tkinter.

Execute com:
    python gui.py
ou, usando a venv:
    .venv\\Scripts\\python.exe gui.py
"""

import os
import queue
import shutil
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox


def _registrar_binarios_embutidos():
    """Quando rodando como .exe (PyInstaller), os binários embutidos
    (ffmpeg, ffprobe, deno) são extraídos para uma pasta temporária.
    Adicionamos essa pasta ao PATH para que o shutil.which e o yt-dlp os
    encontrem — deixando o executável totalmente autossuficiente."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")


_registrar_binarios_embutidos()

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

from youtube_downloader import garantir_runtime_js, montar_opcoes


# --------------------------------------------------------------------- paleta
# Aproximações em hex das cores OKLCH do redesign (tema escuro roxo/rosa).
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

# Mapeia o rótulo amigável da qualidade para o seletor do yt-dlp.
QUALIDADES = {
    "Melhor disponível (bv*)": "bv*",
    "2160p (4K)":              "bv*[height<=2160]",
    "1080p":                   "bv*[height<=1080]",
    "720p":                    "bv*[height<=720]",
    "480p":                    "bv*[height<=480]",
}


# ----------------------------------------------------------------- utilidades
def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _lerp(c1: str, c2: str, t: float) -> str:
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(a[i] + (b[i] - a[i]) * t for i in range(3))


def _brighten(h: str, f: float) -> str:
    """f>0 clareia, f<0 escurece."""
    return _lerp(h, "#ffffff" if f >= 0 else "#000000", abs(f))


_SS = 4  # fator de supersampling para anti-aliasing dos cantos


def _gradient_image(w: int, h: int, c1: str, c2: str) -> "Image.Image":
    """Gera um gradiente horizontal c1→c2 como imagem RGB."""
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
    """Retângulo arredondado com gradiente e bordas suavizadas (anti-aliased)."""
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


# ----------------------------------------------------------------- componentes
class RoundedButton(tk.Canvas):
    """Botão arredondado com cantos suavizados (renderizado via Pillow)."""

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
    """Interruptor estilo iOS com cantos e knob suavizados (Pillow)."""

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
    """Barra de progresso arredondada e suavizada com gradiente."""

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
    """Logo: quadrado arredondado com gradiente e seta de download (Pillow)."""

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


# ------------------------------------------------------------------ infra log
class LoggerGUI:
    """Logger do yt-dlp que envia mensagens para a fila da GUI."""

    def __init__(self, fila: queue.Queue):
        self.fila = fila

    def debug(self, msg):
        if msg.startswith("[debug]"):
            return
        self.fila.put(("log", msg))

    def info(self, msg):
        self.fila.put(("log", msg))

    def warning(self, msg):
        self.fila.put(("log", "⚠  " + msg))

    def error(self, msg):
        self.fila.put(("log", "✕ ERROR " + msg))


# --------------------------------------------------------------------- App
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.geometry("760x880")
        self.minsize(680, 760)
        self.configure(bg=C["bg_page"])

        self.fila: queue.Queue = queue.Queue()
        self.thread_download: threading.Thread | None = None
        self.cancelar = threading.Event()
        self._downloading = False
        self._pulse_on = True

        self._init_fonts()
        self._montar_widgets()
        self._verificar_ffmpeg()
        self._verificar_runtime_js()
        self._update_link_count()
        self.after(100, self._processar_fila)
        self._pulse()

    # ----------------------------------------------------------------- fontes
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
    def _montar_widgets(self):
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

        # ---- Card: Opções --------------------------------------------------
        c_opt = self._card(root)
        c_opt.pack(fill="x", pady=(0, 16))
        opt = tk.Frame(c_opt, bg=C["surface"])
        opt.pack(fill="x", padx=20, pady=18)

        # Pasta de destino
        self._lbl(opt, "Pasta de destino", self.f_small_b).pack(anchor="w",
                                                                pady=(0, 7))
        dest = tk.Frame(opt, bg=C["surface"])
        dest.pack(fill="x", pady=(0, 14))
        self.var_destino = tk.StringVar(value=str(Path.cwd() / "downloads"))
        e_dest = self._entry(dest, self.var_destino)
        e_dest.pack(side="left", fill="x", expand=True, ipady=6)
        RoundedButton(dest, "Procurar", self._escolher_pasta, icon="🗁",
                      fill=C["surface2"], fg=C["text_mut"], font=self.f_ui,
                      height=34, pad_x=14, border=C["border"]).pack(
                          side="left", padx=(8, 0))

        # Grid 2 colunas
        grid = tk.Frame(opt, bg=C["surface"])
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="g")
        grid.columnconfigure(1, weight=1, uniform="g")

        # Qualidade
        f_q = tk.Frame(grid, bg=C["surface"])
        f_q.grid(row=0, column=0, sticky="ew", padx=(0, 7), pady=(0, 12))
        self._lbl(f_q, "Qualidade do vídeo", self.f_small_b).pack(anchor="w",
                                                                  pady=(0, 7))
        self.var_quality = tk.StringVar(value="Melhor disponível (bv*)")
        om = tk.OptionMenu(f_q, self.var_quality, *QUALIDADES.keys())
        om.config(bg=C["surface2"], fg=C["text"], activebackground=C["surface"],
                  activeforeground=C["text"], font=self.f_ui, relief="flat",
                  bd=0, highlightthickness=1, highlightbackground=C["border"],
                  anchor="w", padx=12, pady=6, indicatoron=0)
        om["menu"].config(bg=C["surface2"], fg=C["text"], bd=0,
                          activebackground=C["accent1"], activeforeground="white")
        om.pack(fill="x")

        # Idiomas de legenda
        f_l = tk.Frame(grid, bg=C["surface"])
        f_l.grid(row=0, column=1, sticky="ew", padx=(7, 0), pady=(0, 12))
        self._lbl(f_l, "Idiomas de legenda", self.f_small_b).pack(anchor="w",
                                                                  pady=(0, 7))
        self.var_langs = tk.StringVar(value="all")
        self._entry(f_l, self.var_langs).pack(fill="x", ipady=6)

        # Switch: legendas automáticas
        self.sw_auto = self._switch_row(
            grid, "Legendas automáticas", "Geradas pelo YouTube")
        self.sw_auto["frame"].grid(row=1, column=0, sticky="ew", padx=(0, 7))

        # Switch: apenas áudio
        self.sw_audio = self._switch_row(
            grid, "Apenas áudio", "Extrai .mka sem vídeo")
        self.sw_audio["frame"].grid(row=1, column=1, sticky="ew", padx=(7, 0))

        # ---- Ações ---------------------------------------------------------
        actions = tk.Frame(root, bg=C["bg_page"])
        actions.pack(fill="x", pady=(0, 16))
        self.btn_baixar = RoundedButton(
            actions, "Baixar", self._iniciar_download, icon="⭳",
            colors=(C["accent1"], C["accent2"]), font=self.f_ui_b, pad_x=24)
        self.btn_baixar.pack(side="left")
        self.btn_cancelar = RoundedButton(
            actions, "Cancelar", self._cancelar, icon="✕", fill=C["surface2"],
            fg=C["text"], font=self.f_ui_b, border=C["border"])
        self.btn_cancelar.pack(side="left", padx=10)
        self.btn_cancelar.set_enabled(False)
        RoundedButton(actions, "Abrir pasta", self._abrir_pasta, icon="🗁",
                      fill=C["surface2"], fg=C["text"], font=self.f_ui_b,
                      border=C["border"]).pack(side="right")

        # ---- Card: Progresso ----------------------------------------------
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
        RoundedButton(chead, "Limpar", self._limpar_log, fill="#191820",
                      fg=C["text_dim"], font=self.f_small, height=26, pad_x=10,
                      border=C["border_soft"]).pack(side="right", padx=(0, 12),
                                                    pady=7)
        RoundedButton(chead, "Copiar", self._copiar_log, fill="#191820",
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

    def _verificar_ffmpeg(self):
        if shutil.which("ffmpeg") is None:
            self._log("⚠  FFmpeg não encontrado no PATH. Ele é obrigatório "
                      "para juntar áudios e legendas.", "yellow")
            messagebox.showwarning(
                "FFmpeg ausente",
                "O FFmpeg não foi encontrado no PATH.\n\n"
                "Instale com:  winget install Gyan.FFmpeg\n"
                "Sem ele não é possível embutir múltiplas faixas.")

    def _verificar_runtime_js(self):
        if garantir_runtime_js():
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

    def _escolher_pasta(self):
        pasta = filedialog.askdirectory(initialdir=self.var_destino.get())
        if pasta:
            self.var_destino.set(pasta)

    def _abrir_pasta(self):
        destino = Path(self.var_destino.get())
        destino.mkdir(parents=True, exist_ok=True)
        os.startfile(destino)  # Windows

    def _copiar_log(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_log.get("1.0", "end"))

    def _limpar_log(self):
        self.txt_log["state"] = "normal"
        self.txt_log.delete("1.0", "end")
        self.txt_log["state"] = "disabled"

    def _classificar(self, msg: str) -> str:
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
        self.txt_log.insert("end", msg + "\n", tag or self._classificar(msg))
        self.txt_log.see("end")
        self.txt_log["state"] = "disabled"

    def _set_status(self, texto: str, cor: str, bg: str, downloading: bool):
        self._downloading = downloading
        self.lbl_status_pill.config(text=texto, fg=_brighten(cor, 0.2), bg=bg)
        self.dot_pulse.config(fg=cor, bg=bg)
        self.lbl_status_pill.master.config(bg=bg)

    def _pulse(self):
        if self._downloading:
            self._pulse_on = not self._pulse_on
            self.dot_pulse.config(
                fg=C["green"] if self._pulse_on else "#1f3a2e")
        self.after(700, self._pulse)

    # ------------------------------------------------------------ download
    def _iniciar_download(self):
        urls = [u.strip() for u in self.txt_urls.get("1.0", "end").splitlines()
                if u.strip()]
        if not urls:
            messagebox.showerror("Sem URL", "Informe ao menos uma URL.")
            return

        destino = Path(self.var_destino.get()).expanduser()
        destino.mkdir(parents=True, exist_ok=True)

        opcoes = montar_opcoes(
            destino=destino,
            langs=self.var_langs.get(),
            auto_subs=self.sw_auto["switch"].get(),
            apenas_audio=self.sw_audio["switch"].get(),
            qualidade=QUALIDADES.get(self.var_quality.get(), "bv*"),
        )
        opcoes["logger"] = LoggerGUI(self.fila)
        opcoes["progress_hooks"] = [self._hook_progresso]
        opcoes["quiet"] = True
        opcoes["no_warnings"] = False

        self.cancelar.clear()
        self.btn_baixar.set_enabled(False)
        self.btn_cancelar.set_enabled(True)
        self.bar.set(0)
        self.lbl_pct.config(text="0%")
        self._set_status("Baixando", C["green"], "#1f3a2e", True)
        self.lbl_prog_title.config(text="Preparando…")
        self._log(f"▶ Iniciando {len(urls)} download(s)…", "cyan")

        self.thread_download = threading.Thread(
            target=self._worker, args=(urls, opcoes), daemon=True)
        self.thread_download.start()

    def _worker(self, urls, opcoes):
        try:
            with yt_dlp.YoutubeDL(opcoes) as ydl:
                ydl.download(urls)
            self.fila.put(("done", "✅ Concluído!"))
        except yt_dlp.utils.DownloadCancelled:
            self.fila.put(("done", "✖ Cancelado pelo usuário."))
        except Exception as e:  # noqa: BLE001
            self.fila.put(("done", f"❌ Erro: {e}"))

    def _hook_progresso(self, d):
        if self.cancelar.is_set():
            raise yt_dlp.utils.DownloadCancelled()
        self.fila.put(("progress", d))

    def _cancelar(self):
        self.cancelar.set()
        self._set_status("Cancelando", C["yellow"], "#3a341f", False)

    # --------------------------------------------------- loop de mensagens
    def _processar_fila(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == "log":
                    self._log(dado)
                elif tipo == "progress":
                    self._atualizar_progresso(dado)
                elif tipo == "done":
                    self._finalizar(dado)
        except queue.Empty:
            pass
        self.after(100, self._processar_fila)

    def _atualizar_progresso(self, d):
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            baixado = d.get("downloaded_bytes", 0)
            if total:
                pct = baixado / total * 100
                self.bar.set(pct)
                self.lbl_pct.config(text=f"{pct:.0f}%")
            nome = Path(d.get("filename", "")).name
            self.lbl_prog_title.config(text=nome or "Baixando…")
            vel = d.get("_speed_str", "").strip()
            eta = d.get("_eta_str", "").strip()
            tam = ""
            if total:
                tam = f"{baixado / 1048576:.0f} / {total / 1048576:.0f} MB"
            partes = [p for p in (vel, f"faltam {eta}" if eta else "", tam) if p]
            self.lbl_meta.config(text="    ·    ".join(partes) or "—")
        elif status == "finished":
            self.bar.set(100)
            self.lbl_pct.config(text="100%")
            self._set_status("Processando", C["cyan"], "#1f323a", True)
            self.lbl_prog_title.config(text="Juntando faixas (FFmpeg)…")
            self._log(f"✓ Baixado: {Path(d.get('filename', '')).name}", "green")

    def _finalizar(self, msg):
        sucesso = msg.startswith("✅")
        self._log(msg, "green" if sucesso else "red")
        self.btn_baixar.set_enabled(True)
        self.btn_cancelar.set_enabled(False)
        if sucesso:
            self.bar.set(100)
            self.lbl_pct.config(text="100%")
            self._set_status("Concluído", C["green"], "#1f3a2e", False)
            self.lbl_prog_title.config(text="Todos os downloads finalizados")
        else:
            self._set_status("Parado", C["red"], "#3a2020", False)
            self.lbl_prog_title.config(text=msg)


if __name__ == "__main__":
    App().mainloop()
