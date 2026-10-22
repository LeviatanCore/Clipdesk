# Clipdesk

![Tested](https://img.shields.io/badge/tested-yes-22c55e?style=flat-square)
![Good Practices](https://img.shields.io/badge/good%20practices-yes-3b82f6?style=flat-square)
![Docker](https://img.shields.io/badge/docker-ready-2496ed?style=flat-square&logo=docker&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab?style=flat-square&logo=python&logoColor=white)

> Part of an open-source toolkit for **streamers, video editors, and content creators** — built to simplify workflows, automate repetitive tasks, and make content creation easier.

**Clipdesk** is a local web app (and CLI) that pulls online video into your machine for editing, VODs, archives, or offline review. Choose quality (up to 4K), extract MP3, or pick a specific format ID.

If you request a resolution the source does not have, Clipdesk picks the highest one that does not exceed it.

**Use only with content you have the right to download.**

---

## Why this exists

Creators often need a clean local copy of a clip before it hits the timeline. Clipdesk keeps that step simple:

- Paste a link, pick quality, save to a folder
- Run it in Docker or on your machine
- Optional CLI for scripts and batch jobs

No account required. Files stay on your computer.

## Features

- Modern local web UI with progress, cancel, and saved-file list
- Quality presets up to 4K, plus MP3 audio extraction
- Playlist support
- Docker-ready with a bind-mounted downloads folder
- On WSL/Windows: pick a destination folder with the native Explorer dialog
- CLI for power users and automation
- ffmpeg and Deno are handled for you (no system install required in most setups)

## Requirements

- **Docker** (recommended), or
- **Python 3.10+** and internet access

On WSL, **Explore folder** opens the modern Windows folder picker. Inside Docker that control is hidden — files go to the mounted volume.

## Quick start (Docker)

```bash
docker compose up --build -d
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

Downloads land in `./descargas` (mounted as `/downloads` in the container).

```bash
# Logs
docker compose logs -f

# Stop
docker compose down
```

### Save to another host folder

Edit `docker-compose.yml`:

```yaml
volumes:
  - ./descargas:/downloads
```

Examples:

```yaml
- ./my-videos:/downloads
- /mnt/c/Users/you/Videos:/downloads
- /mnt/c/Users/you/Downloads:/downloads
```

Then:

```bash
docker compose up -d
```

### Custom port

```bash
PORT=9000 docker compose up --build -d
```

### Docker without Compose

```bash
docker build -t clipdesk .
docker run --rm -p 8765:8765 \
  -e DOCKER=1 \
  -e DOWNLOAD_DIR=/downloads \
  -v "$PWD/descargas:/downloads" \
  clipdesk
```

## Quick start (local)

```bash
./web
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

First run creates `.venv`, installs dependencies, and downloads Deno into `.tools/deno`. ffmpeg comes from `imageio-ffmpeg`.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `HOST` | `127.0.0.1` locally / `0.0.0.0` in Docker | Bind address |
| `PORT` | `8765` | HTTP port |
| `DOWNLOAD_DIR` | `./descargas` | Output folder |
| `DOCKER` | auto | Set `1` to force Docker mode (no Windows folder picker) |

```bash
HOST=127.0.0.1 PORT=8765 DOWNLOAD_DIR=~/Videos ./web
```

## Using the web app

1. Paste a video URL and click **Continuar**
2. Choose where to save (local: destination cards or **Explorar carpeta**; Docker: mounted volume)
3. Pick a quality and click **Descargar**
4. Watch progress; finished files appear under **Archivos guardados**

Qualities: `best`, `2160`, `1440`, `1080`, `720`, `480`, `360`, `audio`.

You can also pass a format ID such as `137+140`.

## CLI

```bash
./descargar
./descargar "https://example.com/watch?v=VIDEO"
./descargar "https://example.com/watch?v=VIDEO" -c 1080
./descargar "https://example.com/watch?v=VIDEO" -c audio
./descargar "https://example.com/watch?v=VIDEO" -l
./descargar "https://example.com/playlist?list=LIST" --playlist -c 720
./descargar "URL" -c 1080 -o ~/Videos
```

| Flag | Description |
|---|---|
| `-c` / `--calidad` | `best`, `2160`, `1440`, `1080`, `720`, `480`, `360`, `audio`, or a format ID |
| `-o` / `--salida` | Output directory |
| `-l` / `--listar` | List formats without downloading |
| `--playlist` | Download the full playlist |

## Project layout

```text
clipdesk/
├── app.py                 # Flask web server
├── download.py            # Download engine
├── descargar              # CLI launcher
├── web                    # Local web launcher
├── templates/             # HTML
├── static/                # CSS / JS
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── descargas/             # Default output (gitignored)
└── README.md
```

## API overview

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/api/meta` | Qualities, destination, browse availability |
| `POST` | `/api/info` | Fetch title, channel, thumbnail |
| `POST` | `/api/download` | Start a download |
| `GET` | `/api/jobs` | Status and progress |
| `POST` | `/api/jobs/<id>/cancel` | Cancel the active job |
| `GET` | `/api/files` | List files in the destination |
| `GET` | `/files/<name>` | Download a file through the browser |
| `POST` | `/api/browse` | Open Windows folder picker (local/WSL only) |

## Maintenance notes

- In Docker there is no OS folder picker: mount the folder you want.
- Only one download runs at a time.
- For playlists, enable the checkbox or use `--playlist` in the CLI.
- If a site changes and format detection breaks, update dependencies:

```bash
# Local
.venv/bin/pip install -U -r requirements.txt

# Docker
docker compose build --no-cache
docker compose up -d
```

## Contributing

This project is meant to grow with creators and builders who care about practical tooling.

Ideas, bug reports, and pull requests are welcome — especially around UX for editors, batch workflows, and safer defaults for local setups.

## Responsible use

Clipdesk is for personal and legitimate workflows with content you are allowed to download. Respect the source platform’s terms and applicable law. The maintainers do not endorse copyright infringement.
