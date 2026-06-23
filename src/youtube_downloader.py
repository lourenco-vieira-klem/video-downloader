#!/usr/bin/env python3
"""
YouTube Downloader — baixa vídeos e playlists do YouTube preservando
TODAS as faixas de áudio (idiomas) e TODAS as legendas em um único arquivo .mkv.

Requisitos:
    - Python 3.8+
    - yt-dlp   (pip install -r requirements.txt)
    - FFmpeg   (precisa estar instalado e no PATH do sistema)

Uso:
    python youtube_downloader.py "https://www.youtube.com/watch?v=..."
    python youtube_downloader.py "https://www.youtube.com/playlist?list=..." -o "D:/Videos"
    python youtube_downloader.py URL --langs pt,en,es        # só esses idiomas
    python youtube_downloader.py URL --auto-subs             # inclui legendas automáticas
"""

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


def checar_ffmpeg() -> None:
    """Garante que o FFmpeg está disponível — é ele que junta áudio/legendas."""
    if shutil.which("ffmpeg") is None:
        sys.exit(
            "Erro: FFmpeg não foi encontrado no PATH.\n"
            "Ele é obrigatório para embutir múltiplas faixas de áudio e legendas.\n\n"
            "Windows:  winget install Gyan.FFmpeg\n"
            "          (ou baixe em https://www.gyan.dev/ffmpeg/builds/)\n"
            "macOS:    brew install ffmpeg\n"
            "Linux:    sudo apt install ffmpeg"
        )


def garantir_runtime_js() -> bool:
    """
    O YouTube exige um runtime JS (Deno) para extrair os formatos.
    Sem ele, o yt-dlp falha com 'This video is not available'.

    Procura o 'deno' no PATH e, se não achar, tenta localizá-lo nos
    diretórios padrão do winget e o adiciona ao PATH desta sessão —
    assim não é preciso reiniciar o terminal/PC após instalar.
    Retorna True se um runtime foi encontrado.
    """
    if shutil.which("deno") or shutil.which("node") or shutil.which("bun"):
        return True

    # Locais comuns de instalação do Deno no Windows (winget / instalador oficial).
    candidatos = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links",
        Path(os.environ.get("USERPROFILE", "")) / ".deno" / "bin",
    ]
    # Pacote específico do winget (caminho com hash).
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if pkgs.is_dir():
        candidatos += list(pkgs.glob("DenoLand.Deno_*"))

    for diretorio in candidatos:
        if diretorio and (diretorio / "deno.exe").exists():
            os.environ["PATH"] = str(diretorio) + os.pathsep + os.environ.get("PATH", "")
            return True
    return False


def montar_opcoes(destino: Path, langs: str, auto_subs: bool,
                  apenas_audio: bool, qualidade: str) -> dict:
    """Monta o dicionário de opções do yt-dlp."""

    garantir_runtime_js()

    # Lista de idiomas de legenda: 'all' por padrão, ou os escolhidos pelo usuário.
    sub_langs = ["all"] if langs.strip().lower() == "all" else \
        [s.strip() for s in langs.split(",") if s.strip()]

    # Seletor de áudio: queremos UMA faixa por idioma (a melhor), e não todas
    # as variantes de codec/bitrate do mesmo idioma. Vídeos com dublagem
    # multilíngue expõem cada idioma em ~4 formatos (opus em 3 bitrates + aac);
    # 'mergeall' puro pegaria tudo (dezenas de faixas redundantes) e o merge
    # final ficava pesado/falhava.
    #
    # Estratégia (cada item é uma tentativa; '/' = fallback se a anterior falhar):
    #   1) melhor opus por idioma (abr>100 = faixa "high"), excluindo cópias DRC;
    #   2) se não houver opus, qualquer áudio sem DRC (1 por idioma na prática);
    #   3) por fim, o melhor áudio único.
    melhores_audios = [
        "mergeall[vcodec=none][acodec^=opus][abr>100][format_id!*=drc]",
        "mergeall[vcodec=none][format_id!*=drc]",
        "bestaudio",
    ]

    if apenas_audio:
        formato = "/".join(melhores_audios)
    else:
        # Junta o vídeo escolhido com cada tentativa de áudio, em cascata.
        formato = "/".join(f"{qualidade}+{a}" for a in melhores_audios) + "/best"

    opcoes = {
        # ---- Extração do YouTube ----
        # Baixa o "challenge solver" (EJS) necessário, junto com o runtime JS
        # (Deno), para resolver as assinaturas e não perder formatos.
        "remote_components": ["ejs:github"],

        # ---- Seleção de formato ----
        "format": formato,
        "allow_multiple_audio_streams": True,   # permite >1 faixa de áudio
        "allow_multiple_video_streams": False,
        "merge_output_format": "mkv",           # MKV suporta N áudios + N legendas

        # ---- Legendas ----
        "writesubtitles": True,                 # baixa legendas "oficiais"
        "writeautomaticsub": auto_subs,         # legendas geradas automaticamente
        "subtitleslangs": sub_langs,

        # ---- Saída / organização ----
        "outtmpl": {
            "default": str(destino / "%(playlist_title,Vídeos)s/%(title)s [%(id)s].%(ext)s"),
        },
        "ignoreerrors": True,                    # não para a playlist por causa de 1 vídeo
        "continuedl": True,                      # retoma downloads interrompidos
        "writethumbnail": True,

        # ---- Pós-processamento (mux final) ----
        "postprocessors": [
            {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
            {"key": "EmbedThumbnail", "already_have_thumbnail": False},
        ],

        # ---- Logs ----
        "quiet": False,
        "no_warnings": False,
    }

    if apenas_audio:
        # Para somente-áudio, MKA é o container apropriado para várias trilhas.
        opcoes["merge_output_format"] = "mka"
        opcoes["postprocessors"] = [
            {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True},
        ]
        opcoes["writethumbnail"] = False

    return opcoes


def baixar(urls: list[str], opcoes: dict) -> int:
    """Executa o download. Retorna o código de saída do yt-dlp."""
    with yt_dlp.YoutubeDL(opcoes) as ydl:
        return ydl.download(urls)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Baixa vídeos/playlists do YouTube com TODAS as faixas de "
                    "áudio e legendas em um único arquivo .mkv.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("urls", nargs="+", help="Uma ou mais URLs (vídeo ou playlist).")
    parser.add_argument("-o", "--output", default="downloads",
                        help="Pasta de destino (padrão: ./downloads).")
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

    checar_ffmpeg()

    destino = Path(args.output).expanduser().resolve()
    destino.mkdir(parents=True, exist_ok=True)

    print(f"📂 Destino: {destino}")
    print(f"🎬 URLs: {len(args.urls)}")
    print(f"🗣️  Legendas: {args.langs}"
          f"{' (+ automáticas)' if args.auto_subs else ''}")
    print(f"🎧 Modo: {'somente áudio' if args.audio_only else 'vídeo + áudios + legendas'}\n")

    opcoes = montar_opcoes(
        destino=destino,
        langs=args.langs,
        auto_subs=args.auto_subs,
        apenas_audio=args.audio_only,
        qualidade=args.quality,
    )

    codigo = baixar(args.urls, opcoes)

    if codigo == 0:
        print("\n✅ Concluído com sucesso!")
    else:
        print("\n⚠️  Finalizado com alguns erros (verifique os logs acima).")
    sys.exit(codigo)


if __name__ == "__main__":
    main()
