<div align="center">

# 🎬 YouTube Downloader

**Baixe vídeos e playlists do YouTube preservando _todas_ as faixas de áudio (idiomas) e _todas_ as legendas em um único arquivo `.mkv`.**

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)
![yt-dlp](https://img.shields.io/badge/yt--dlp-powered-FF0000?logo=youtube&logoColor=white)
![Tkinter](https://img.shields.io/badge/GUI-Tkinter-2C5BB4)
![Platform](https://img.shields.io/badge/OS-Windows-0078D6?logo=windows&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

</div>

---

Interface gráfica (tema escuro) **e** linha de comando para baixar vídeos ou
**playlists completas**, mantendo as múltiplas dublagens e legendas embutidas —
no player (VLC, MPV…) você troca de idioma de áudio/legenda direto no menu.

> ![Screenshot da GUI](docs/screenshot.png)
>
> _Substitua `docs/screenshot.png` por uma captura da interface._

## ✨ Destaques

- 🎧 **Multi-áudio**: preserva todas as dublagens (uma faixa por idioma, a melhor de cada).
- 💬 **Multi-legenda**: embute todas as legendas, com filtro por idioma e suporte a legendas automáticas.
- 📦 **Playlists completas**, organizadas em subpastas pelo nome da playlist.
- 🖥️ **GUI em Tkinter** com widgets customizados (renderizados via Pillow): botões e switches arredondados, barra de progresso com gradiente e console colorido em tempo real.
- ⌨️ **CLI** completa para automação.
- ♻️ Downloads interrompidos são **retomados automaticamente**; um vídeo com erro não interrompe o resto da playlist.
- 🔍 Localiza o **Deno** automaticamente após instalar (sem reiniciar o terminal).

## Por que `.mkv`?

O container MKV (Matroska) é o único formato amplamente suportado que guarda
**múltiplas faixas de áudio + múltiplas legendas** no mesmo arquivo. O MP4 é
limitado nesse aspecto.

## 🧰 Stack

| Tecnologia | Papel |
|------------|-------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Extração e download do YouTube |
| [FFmpeg](https://ffmpeg.org/) | _Mux_ das faixas de áudio/legenda no `.mkv` |
| [Deno](https://deno.com/) | Runtime JS exigido pelo YouTube para extrair os formatos |
| [Tkinter](https://docs.python.org/3/library/tkinter.html) + [Pillow](https://python-pillow.org/) | Interface gráfica e renderização dos componentes |
| [PyInstaller](https://pyinstaller.org/) | Empacotamento em `.exe` autossuficiente |

## 📁 Estrutura do projeto

```
YOUTUBE_DOWNLOADER/
├── src/
│   ├── youtube_downloader.py   # núcleo + CLI (lógica de download e opções do yt-dlp)
│   └── gui.py                  # interface gráfica (Tkinter), reusa o núcleo
├── scripts/
│   └── generate_icon.py        # gera assets/icon.ico a partir do logo do app
├── assets/
│   └── icon.ico                # ícone usado no build do .exe
├── Run GUI.bat                 # atalho Windows para abrir a GUI pela venv
├── YouTube Downloader.spec     # receita do PyInstaller
├── requirements.txt
├── LICENSE
└── README.md
```

## ⚙️ Pré-requisitos

1. **Python 3.8+**
2. **FFmpeg** no `PATH` (faz o _mux_ das faixas):
   - Windows: `winget install Gyan.FFmpeg`
   - macOS: `brew install ffmpeg`
   - Linux: `sudo apt install ffmpeg`
3. **Deno** (runtime JavaScript) — **obrigatório**: o YouTube passou a exigir
   execução de JS para extrair os vídeos. Sem ele você verá _"This video is not available"_.
   - Windows: `winget install DenoLand.Deno`
   - macOS/Linux: `curl -fsSL https://deno.land/install.sh | sh`

## 🚀 Instalação

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 🖱️ Interface gráfica (GUI)

```powershell
.venv\Scripts\python.exe src\gui.py
```

Ou dê **duplo-clique em `Run GUI.bat`** (Windows).

Na janela você cola as URLs (uma por linha), escolhe a pasta de destino, os
idiomas de legenda e a qualidade, e acompanha o progresso e o log em tempo real.

## 💻 Uso (linha de comando)

```bash
# Vídeo único
python src/youtube_downloader.py "https://www.youtube.com/watch?v=VIDEO_ID"

# Playlist completa, salvando em outra pasta
python src/youtube_downloader.py "https://www.youtube.com/playlist?list=PLAYLIST_ID" -o "D:/Videos"

# Só alguns idiomas de legenda
python src/youtube_downloader.py URL --langs pt,en,es

# Incluir legendas automáticas (geradas por IA do YouTube)
python src/youtube_downloader.py URL --auto-subs

# Limitar qualidade a 1080p
python src/youtube_downloader.py URL --quality "bv*[height<=1080]"

# Apenas áudio (todas as trilhas) -> .mka
python src/youtube_downloader.py URL --audio-only
```

### Opções

| Flag | Descrição | Padrão |
|------|-----------|--------|
| `-o, --output` | Pasta de destino | pasta `Downloads` do usuário |
| `--langs` | Idiomas de legenda (`pt,en,es` ou `all`) | `all` |
| `--auto-subs` | Inclui legendas automáticas | desligado |
| `--audio-only` | Baixa só o áudio (todas as trilhas) | desligado |
| `--quality` | Seletor de vídeo do yt-dlp | `bv*` (melhor) |

## 📦 Gerar o executável (.exe)

O `.exe` final é **autossuficiente**: os binários do FFmpeg, FFprobe e Deno são
embutidos e extraídos para uma pasta temporária em tempo de execução.

1. Coloque `ffmpeg.exe`, `ffprobe.exe` e `deno.exe` numa pasta `build_bin/`
   (não versionada — veja o `.gitignore`).
2. Gere o ícone (opcional): `python scripts/generate_icon.py`
3. Faça o build:

```powershell
pip install pyinstaller
pyinstaller "YouTube Downloader.spec"
```

O executável é gerado em `dist/`.

## 🩹 Solução de problemas

| Mensagem de erro | Causa e solução |
|------------------|-----------------|
| `This video is not available` em **todos** os vídeos, ou `No supported JavaScript runtime could be found` | Falta o **Deno**. Instale com `winget install DenoLand.Deno` e reabra o programa. |
| `This video is not available` em **apenas alguns** vídeos de uma playlist | Esses vídeos estão realmente bloqueados (copyright/região — `playability status: UNPLAYABLE`). Nenhum downloader consegue baixá-los; o restante da playlist baixa normalmente. |
| `Some formats may be missing` / `n challenge solving failed` | O yt-dlp precisa baixar o _challenge solver_ (EJS). O app já passa `remote_components: ["ejs:github"]` automaticamente para resolver isso. |

## 📝 Observações

- Vídeos com várias dublagens terão **uma faixa por idioma** no arquivo final,
  cada uma marcada nos metadados (selecionável no player). É escolhida a melhor
  versão de cada idioma — não as variantes redundantes de codec/bitrate.
- A GUI e o empacotamento `.exe` são voltados a **Windows**; o núcleo CLI é
  multiplataforma.

## ⚖️ Aviso legal

Ferramenta para fins educacionais e de uso pessoal. Respeite os Termos de
Serviço do YouTube e a legislação de direitos autorais aplicável. Baixe apenas
conteúdo que você tem o direito de baixar.

## 📄 Licença

Distribuído sob a licença [MIT](LICENSE).
