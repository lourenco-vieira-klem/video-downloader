#!/usr/bin/env python3
"""Gera icon.ico a partir do logo do app (mesmo desenho do AppMark da GUI)."""

from pathlib import Path

from PIL import Image, ImageDraw

# Salva sempre em <raiz>/assets/icon.ico, independente do diretório atual.
SAIDA = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"

ACCENT1 = (139, 92, 246)   # #8b5cf6
ACCENT2 = (236, 72, 153)   # #ec4899


def _gradient(size):
    img = Image.new("RGB", (size, 1))
    px = img.load()
    for x in range(size):
        t = x / max(1, size - 1)
        px[x, 0] = tuple(int(ACCENT1[i] + (ACCENT2[i] - ACCENT1[i]) * t)
                         for i in range(3))
    return img.resize((size, size))


def mark(size):
    ss = 4
    S = size * ss
    img = _gradient(S).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=int(0.22 * S), fill=255)
    img.putalpha(mask)
    d = ImageDraw.Draw(img)
    cx = S / 2
    lw = max(2, int(0.05 * S))
    white = (255, 255, 255, 255)
    d.line([(cx, S * 0.26), (cx, S * 0.58)], fill=white, width=lw, joint="curve")
    d.line([(cx - S * 0.13, S * 0.45), (cx, S * 0.58)], fill=white, width=lw)
    d.line([(cx + S * 0.13, S * 0.45), (cx, S * 0.58)], fill=white, width=lw)
    d.line([(S * 0.28, S * 0.74), (S * 0.72, S * 0.74)], fill=white, width=lw)
    return img.resize((size, size), Image.LANCZOS)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = mark(256)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    base.save(SAIDA, sizes=[(s, s) for s in sizes])
    print(f"{SAIDA} gerado")


if __name__ == "__main__":
    main()
