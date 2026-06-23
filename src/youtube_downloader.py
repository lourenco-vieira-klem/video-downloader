#!/usr/bin/env python3
import argparse
import os
import shutil
import sys
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit(
        "Erro: o pacote 'yt-dlp' não está instalado.\n"
        "Instale com:  pip install -r requirements.txt"
    )


def default_downloads_dir() -> Path:
    return Path.home() / "Downloads"


def check_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        sys.exit(
            "Erro: FFmpeg não foi encontrado no PATH.\n"
            "Ele é obrigatório para embutir múltiplas faixas de áudio e legendas.\n\n"
            "Windows:  winget install Gyan.FFmpeg\n"
            "          (ou baixe em https://www.gyan.dev/ffmpeg/builds/)\n"
            "macOS:    brew install ffmpeg\n"
            "Linux:    sudo apt install ffmpeg"
        )


def ensure_js_runtime() -> bool:
    if shutil.which("deno") or shutil.which("node") or shutil.which("bun"):
        return True

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path(os.environ.get("USERPROFILE", "")) / ".deno" / "bin",
    ]
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        candidates += list(pkgs.glob("DenoLand.Deno_*"))

    for directory in candidates:
        if directory and (directory / "deno.exe").exists():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            return True
    return False


def build_options(dest: Path, langs: str, auto_subs: bool,
                  audio_only: bool, quality: str) -> dict:
    ensure_js_runtime()

    sub_langs = ["all"] if langs.strip().lower() == "all" else \
        [s.strip() for s in langs.split(",") if s.strip()]

    audio_selectors = [
        "mergeall[vcodec=none][acodec^=opus][abr>100][format_id!*=drc]",
        "mergeall[vcodec=none][format_id!*=drc]",
        "bestaudio",
    ]

    if audio_only:
        fmt = "/".join(audio_selectors)
    else:
        fmt = "/".join(f"{quality}+{a}" for a in audio_selectors) + "/best"

    options = {
        "remote_components": ["ejs:github"],

        "format": fmt,
        "allow_multiple_audio_streams": True,
        "allow_multiple_video_streams": False,
        "merge_output_format": "mkv",

        "writesubtitles": True,
        "writeautomaticsub": auto_subs,
        "subtitleslangs": sub_langs,

        "outtmpl": {
            "default": str(dest / "%(playlist_title,Vídeos)s/%(title)s [%(id)s].%(ext)s"),
        },
        "ignoreerrors": True,
        "continuedl": True,
        "writethumbnail": True,

        "postprocessors": [
            {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
            {"key": "EmbedThumbnail", "already_have_thumbnail": False},
        ],

        "quiet": False,
        "no_warnings": False,
    }

    if audio_only:
        options["merge_output_format"] = "mka"
        options["postprocessors"] = [
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
        ]
        options["writethumbnail"] = False

    return options


def download(urls: list[str], options: dict) -> int:
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.download(urls)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa vídeos/playlists do YouTube com TODAS as faixas de "
                    "áudio e legendas em um único arquivo .mkv.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="+", help="Uma ou mais URLs (vídeo ou playlist).")
    parser.add_argument("-o", "--output", default=None,
                        help="Pasta de destino (padrão: a pasta Downloads do usuário).")
    parser.add_argument("--langs", default="all",
                        help="Idiomas de legenda separados por vírgula (ex.: pt,en,es) "
                             "ou 'all' para todos (padrão: all).")
    parser.add_argument("--auto-subs", action="store_true",
                        help="Inclui também legendas geradas automaticamente.")
    parser.add_argument("--audio-only", action="store_true",
                        help="Baixa apenas o áudio (todas as trilhas) em .mka.")
    parser.add_argument("--quality", default="bv*",
                        help="Seletor de vídeo do yt-dlp (padrão: bv* = melhor vídeo). "
                             "Ex.: 'bv*[height<=1080]' para limitar a 1080p.")

    args = parser.parse_args()

    check_ffmpeg()

    dest = (Path(args.output).expanduser() if args.output
            else default_downloads_dir()).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    print(f"📂 Destino: {dest}")
    print(f"🎬 URLs: {len(args.urls)}")
    print(f"🗣️  Legendas: {args.langs}"
          f"{' (+ automáticas)' if args.auto_subs else ''}")
    print(f"🎧 Modo: {'somente áudio' if args.audio_only else 'vídeo + áudios + legendas'}\n")

    options = build_options(
        dest=dest,
        langs=args.langs,
        auto_subs=args.auto_subs,
        audio_only=args.audio_only,
        quality=args.quality,
    )

    code = download(args.urls, options)

    if code == 0:
        print("\n✅ Concluído com sucesso!")
    else:
        print("\n⚠️  Finalizado com alguns erros (verifique os logs acima).")
    sys.exit(code)


if __name__ == "__main__":
    main()
