#!/usr/bin/env python3
"""Descarga videos de YouTube eligiendo la calidad."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "descargas"


class MissingFfmpeg(RuntimeError):
    """El entorno no tiene el binario de ffmpeg."""


class DownloadCancelled(Exception):
    """El usuario detuvo la descarga."""

QUALITIES: list[tuple[str, str]] = [
    ("best", "Mejor calidad disponible"),
    ("2160", "2160p (4K)"),
    ("1440", "1440p (2K)"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("480", "480p"),
    ("360", "360p"),
    ("audio", "Solo audio (MP3)"),
]


def format_for(quality: str) -> str:
    """Traduce una calidad elegida al selector de formatos de yt-dlp."""
    if quality == "best":
        return "bv*+ba/b"
    if quality == "audio":
        return "bestaudio/best"
    if quality.isdigit():
        height = int(quality)
        return f"bv*[height<={height}]+ba/b[height<={height}]"
    return quality


def ffmpeg_location() -> str | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    path = imageio_ffmpeg.get_ffmpeg_exe()
    return path if path else None


def deno_path() -> str | None:
    local = ROOT / ".tools" / "deno"
    if local.is_file():
        return str(local)
    return shutil.which("deno")


class DownloadLogger:
    def debug(self, msg: str) -> None:
        return

    def info(self, msg: str) -> None:
        return

    def warning(self, msg: str) -> None:
        text = str(msg)
        if "Python version 3.10" in text:
            return
        print(text, file=sys.stderr)

    def error(self, msg: str) -> None:
        print(str(msg), file=sys.stderr)


def human_size(num: int | float | None) -> str:
    if not num:
        return "?"
    size = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def human_duration(seconds: int | float | None) -> str:
    if not seconds:
        return "?"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def base_opts(playlist: bool) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "noplaylist": not playlist,
        "windowsfilenames": True,
        "logger": DownloadLogger(),
    }
    ffmpeg = ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    deno = deno_path()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}
    return opts


def probe(url: str, playlist: bool) -> dict:
    opts = base_opts(playlist)
    opts["skip_download"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        raise DownloadError("No se pudo leer el video.")
    if info.get("_type") == "playlist":
        entries = [entry for entry in (info.get("entries") or []) if entry]
        if len(entries) == 1:
            return entries[0]
        return info
    return info


def print_video(info: dict) -> None:
    if info.get("_type") == "playlist":
        count = info.get("playlist_count") or len(info.get("entries") or [])
        print(f"\nLista: {info.get('title') or 'sin título'}")
        print(f"Videos: {count}")
        return
    print(f"\nTítulo:   {info.get('title') or 'sin título'}")
    print(f"Canal:    {info.get('channel') or info.get('uploader') or '?'}")
    print(f"Duración: {human_duration(info.get('duration'))}")


def print_formats(info: dict) -> None:
    formats = info.get("formats") or []
    if not formats:
        print("Este resultado no tiene formatos individuales.")
        return
    print()
    print(f"{'ID':<8} {'EXT':<6} {'RESOLUCIÓN':<14} {'FPS':<5} {'TAMAÑO':<10} AUDIO")
    print("-" * 62)
    for fmt in formats:
        if fmt.get("format_id") in {"none"}:
            continue
        protocol = fmt.get("protocol") or ""
        if "m3u8" in protocol:
            continue
        note = (fmt.get("format_note") or "").lower()
        if "storyboard" in note or fmt.get("vcodec") == "images":
            continue
        video = fmt.get("vcodec") not in (None, "none")
        audio = fmt.get("acodec") not in (None, "none")
        if not video and not audio:
            continue
        height = fmt.get("height")
        width = fmt.get("width")
        if video and height and width:
            resolution = f"{width}x{height}"
        elif video:
            resolution = fmt.get("resolution") or "video"
        else:
            resolution = "audio"
        fps = fmt.get("fps")
        fps_text = str(int(fps)) if isinstance(fps, (int, float)) else "-"
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        audio_text = "sí" if audio else "no"
        print(
            f"{fmt.get('format_id', '?'):<8} "
            f"{(fmt.get('ext') or '?'):<6} "
            f"{resolution:<14} "
            f"{fps_text:<5} "
            f"{human_size(size):<10} "
            f"{audio_text}"
        )
    print("\nPuedes elegir un ID, o dos unidos con + (video+audio), por ejemplo 137+140.")


def choose_quality(info: dict) -> str | None:
    print("\nCalidad:")
    for index, (_key, label) in enumerate(QUALITIES, start=1):
        print(f"  {index}. {label}")
    print("  9. Ver formatos de este video y elegir uno")
    raw = ask("Elige un número, una calidad o un ID de formato: ")
    if raw.lower() in {"q", "salir", "exit"}:
        return None
    if raw == "9" or raw.lower() in {"listar", "formatos", "l"}:
        print_formats(info)
        picked = ask("ID de formato (o Enter para cancelar): ")
        return picked or None
    if raw.isdigit() and 1 <= int(raw) <= len(QUALITIES):
        return QUALITIES[int(raw) - 1][0]
    known = {key for key, _label in QUALITIES}
    if raw.lower() in known:
        return raw.lower()
    if raw:
        return raw
    return None


def collect_paths(info: dict | None, fallback: list[str]) -> list[Path]:
    """Rutas finales que sí existen después de unir pistas o extraer audio."""
    found: list[Path] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        if not raw:
            return
        path = Path(raw)
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen or not path.is_file():
            return
        seen.add(key)
        found.append(path)

    def walk(node: dict | None) -> None:
        if not node:
            return
        if node.get("_type") == "playlist":
            for entry in node.get("entries") or []:
                walk(entry)
            return
        for item in node.get("requested_downloads") or []:
            add(item.get("filepath") or item.get("filename"))
        add(node.get("filepath"))

    walk(info)
    if not found:
        for raw in fallback:
            add(raw)
    return found


def download(
    url: str,
    quality: str,
    output_dir: Path,
    playlist: bool,
    on_progress=None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    def hook(status: dict) -> None:
        if on_progress:
            on_progress(status)
        state = status.get("status")
        if on_progress is None and state == "downloading":
            percent = (status.get("_percent_str") or "").strip()
            speed = (status.get("_speed_str") or "").strip()
            eta = (status.get("_eta_str") or "").strip()
            print(f"\r  {percent}  {speed}  queda {eta}    ", end="", flush=True)
        elif on_progress is None and state == "finished":
            print("\n  Descarga terminada. Uniendo pistas si hace falta...")
        if state == "finished" and status.get("filename"):
            saved.append(status["filename"])

    opts = base_opts(playlist)
    opts.update(
        {
            "format": format_for(quality),
            "outtmpl": str(output_dir / "%(title).200B [%(id)s].%(ext)s"),
            "progress_hooks": [hook],
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
            "quiet": True,
            "noprogress": True,
            "no_warnings": on_progress is not None,
        }
    )
    if quality != "audio":
        opts["merge_output_format"] = "mp4"
    else:
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]

    if not ffmpeg_location():
        raise MissingFfmpeg(
            "Falta ffmpeg. Instálalo en el entorno con: "
            ".venv/bin/pip install -r requirements.txt"
        )

    if on_progress is None:
        print(f"\nDescargando en calidad «{quality}» hacia {output_dir}")
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    paths = collect_paths(info, saved)
    if on_progress is None:
        if paths:
            for path in paths:
                print(f"Listo: {path}")
        else:
            print(f"Listo. Revisa la carpeta {output_dir}")
    return paths


def ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0) from None


def interactive(output_dir: Path, playlist: bool, preset_url: str | None = None) -> None:
    print("Descargas de YouTube. Escribe q para salir.")
    while True:
        url = preset_url or ask("\nURL del video: ")
        preset_url = None
        if url.lower() in {"q", "salir", "exit"}:
            return
        if not url:
            continue
        try:
            info = probe(url, playlist)
        except DownloadError as exc:
            print(f"No se pudo leer esa URL: {exc}")
            continue
        print_video(info)
        if info.get("_type") == "playlist" and not playlist:
            print("La URL es una lista. Vuelve a ejecutar con --playlist para bajarla completa.")
            continue
        quality = choose_quality(info)
        if not quality:
            continue
        try:
            download(url, quality, output_dir, playlist)
        except DownloadCancelled:
            print("Descarga cancelada.")
        except MissingFfmpeg as exc:
            print(exc)
        except DownloadError as exc:
            print(f"Falló la descarga: {exc}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Descarga videos de YouTube con la calidad que elijas."
    )
    parser.add_argument("url", nargs="?", help="URL del video. Sin URL, entra al modo interactivo.")
    parser.add_argument(
        "-c",
        "--calidad",
        help="best, 2160, 1440, 1080, 720, 480, 360, audio, o un ID de yt-dlp",
    )
    parser.add_argument(
        "-o",
        "--salida",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Carpeta de destino (por defecto: ./descargas)",
    )
    parser.add_argument(
        "-l",
        "--listar",
        action="store_true",
        help="Muestra los formatos disponibles y no descarga",
    )
    parser.add_argument(
        "--playlist",
        action="store_true",
        help="Si la URL es una lista, descarga todos los videos",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.salida.expanduser().resolve()

    if not args.url:
        interactive(output_dir, args.playlist)
        return 0

    try:
        if args.listar or not args.calidad:
            info = probe(args.url, args.playlist)
            print_video(info)
            if args.listar:
                print_formats(info)
                return 0
            quality = choose_quality(info)
            if not quality:
                return 0
        else:
            quality = args.calidad.lower() if args.calidad.lower() in {k for k, _ in QUALITIES} else args.calidad
        download(args.url, quality, output_dir, args.playlist)
    except DownloadCancelled:
        print("Descarga cancelada.")
        return 1
    except MissingFfmpeg as exc:
        print(exc, file=sys.stderr)
        return 1
    except DownloadError as exc:
        print(f"Falló la descarga: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
