#!/usr/bin/env python3
"""Interfaz web local para descargar videos de YouTube."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from yt_dlp.utils import DownloadError

from download import (
    DEFAULT_OUTPUT,
    QUALITIES,
    ROOT,
    DownloadCancelled,
    MissingFfmpeg,
    download,
    human_duration,
    human_size,
    probe,
)

app = Flask(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _in_docker() -> bool:
    return _env_bool("DOCKER") or Path("/.dockerenv").exists()


def _resolve_download_dir() -> Path:
    raw = os.environ.get("DOWNLOAD_DIR", "").strip()
    if not raw:
        return DEFAULT_OUTPUT.resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


OUTPUT_DIR = _resolve_download_dir()
HOST = os.environ.get("HOST", "0.0.0.0" if _in_docker() else "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_ACTIVE = {"starting", "downloading", "merging"}
_SKIP_SUFFIXES = {".part", ".ytdl", ".tmp", ".temp"}
_SKIP_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


def _quality_payload() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in QUALITIES]


def _public_job(job: dict) -> dict:
    return {
        "id": job["id"],
        "title": job["title"],
        "quality": job["quality"],
        "status": job["status"],
        "percent": job["percent"],
        "speed": job["speed"],
        "eta": job["eta"],
        "index": job["index"],
        "count": job["count"],
        "error": job["error"],
        "output": job["output"],
        "files": job["files"],
    }


def _read_json() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _clean_url(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > 2000:
        return None
    if not (url.startswith("https://") or url.startswith("http://")):
        return None
    return url


def _clean_quality(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    quality = raw.strip()
    if not quality or len(quality) > 40:
        return None
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+._-")
    if any(char not in allowed for char in quality):
        return None
    return quality


def _active_job() -> dict | None:
    for job in _jobs.values():
        if job["status"] in _ACTIVE:
            return job
    return None


def _remember(job: dict) -> None:
    _jobs[job["id"]] = job
    finished = [item for item in _jobs.values() if item["status"] not in _ACTIVE]
    finished.sort(key=lambda item: item["created"])
    while len(_jobs) > 24 and finished:
        oldest = finished.pop(0)
        _jobs.pop(oldest["id"], None)


def _browse_available() -> bool:
    return not _in_docker() and shutil.which("powershell.exe") is not None


def _allowed_roots() -> list[Path]:
    if _in_docker():
        roots = [OUTPUT_DIR.resolve(), Path("/downloads").resolve()]
    else:
        roots = [
            Path.home().resolve(),
            ROOT.resolve(),
            OUTPUT_DIR.resolve(),
            Path("/tmp"),
            Path("/mnt"),
        ]
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _within_allowed(path: Path) -> bool:
    for root in _allowed_roots():
        try:
            path.relative_to(root)
        except ValueError:
            continue
        else:
            return True
    return False


def _resolve_output(raw: object) -> tuple[Path | None, str | None]:
    """Acepta una carpeta del usuario, de Windows vía /mnt, o la carpeta del proyecto."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return OUTPUT_DIR.resolve(), None
    if not isinstance(raw, str):
        return None, "La carpeta no es válida."
    text = raw.strip()
    if len(text) > 500 or "\x00" in text or "\n" in text:
        return None, "La carpeta no es válida."
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    try:
        path = path.resolve()
    except OSError:
        return None, "No se pudo leer esa carpeta."
    if not _within_allowed(path):
        if _in_docker():
            return None, "En Docker solo se puede guardar en la carpeta montada (/downloads)."
        return None, "Elige una carpeta dentro de tu usuario, del proyecto o de /mnt/c."
    if path.exists() and not path.is_dir():
        return None, "Esa ruta es un archivo. Elige una carpeta."
    return path, None


def _wsl_to_windows(path: Path) -> str | None:
    match = re.fullmatch(r"/mnt/([a-zA-Z])(?:/(.*))?", str(path))
    if not match:
        return None
    rest = (match.group(2) or "").replace("/", "\\")
    drive = match.group(1).upper()
    return f"{drive}:\\{rest}" if rest else f"{drive}:\\"


def _windows_to_wsl(path: str) -> str | None:
    text = path.strip().strip('"')
    match = re.fullmatch(r"([A-Za-z]):[\\/](.*)", text)
    if not match:
        return None
    rest = match.group(2).replace("\\", "/").strip("/")
    drive = match.group(1).lower()
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


def _decode_process_output(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or (len(raw) > 3 and raw[1] == 0):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


# Selector moderno del Explorador (IFileOpenDialog + FOS_PICKFOLDERS),
# no el diálogo viejo "Browse For Folder".
_BROWSE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class ModernFolderPicker
{
    private const uint FOS_PICKFOLDERS = 0x00000020;
    private const uint FOS_FORCEFILESYSTEM = 0x00000040;
    private const uint SIGDN_FILESYSPATH = 0x80058000;

    [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
    private class FileOpenDialog {}

    [ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileDialog
    {
        [PreserveSig] int Show(IntPtr parent);
        void SetFileTypes(uint cFileTypes, IntPtr rgFilterSpec);
        void SetFileTypeIndex(uint iFileType);
        void GetFileTypeIndex(out uint piFileType);
        void Advise(IntPtr pfde, out uint pdwCookie);
        void Unadvise(uint dwCookie);
        void SetOptions(uint fos);
        void GetOptions(out uint pfos);
        void SetDefaultFolder(IShellItem psi);
        void SetFolder(IShellItem psi);
        void GetFolder(out IShellItem ppsi);
        void GetCurrentSelection(out IShellItem ppsi);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string pszName);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string pszName);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string pszText);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string pszLabel);
        void GetResult(out IShellItem ppsi);
        void AddPlace(IShellItem psi, int fdap);
        void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string pszDefaultExtension);
        void Close(int hr);
        void SetClientGuid(ref Guid guid);
        void ClearClientData();
        void SetFilter(IntPtr pFilter);
    }

    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem
    {
        void BindToHandler(IntPtr pbc, ref Guid bhid, ref Guid riid, out IntPtr ppv);
        void GetParent(out IShellItem ppsi);
        void GetDisplayName(uint sigdnName, out IntPtr ppszName);
        void GetAttributes(uint sfgaoMask, out uint psfgaoAttribs);
        void Compare(IShellItem psi, uint hint, out int piOrder);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void SHCreateItemFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string pszPath,
        IntPtr pbc,
        ref Guid riid,
        out IShellItem ppv);

    public static string Pick(string title, string initial)
    {
        var dialog = (IFileDialog)new FileOpenDialog();
        uint options;
        dialog.GetOptions(out options);
        dialog.SetOptions(options | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
        if (!string.IsNullOrWhiteSpace(title))
        {
            dialog.SetTitle(title);
        }
        dialog.SetOkButtonLabel("Seleccionar carpeta");
        if (!string.IsNullOrWhiteSpace(initial))
        {
            try
            {
                Guid shellItemGuid = typeof(IShellItem).GUID;
                IShellItem item;
                SHCreateItemFromParsingName(initial, IntPtr.Zero, ref shellItemGuid, out item);
                dialog.SetFolder(item);
            }
            catch {}
        }
        int hr = dialog.Show(IntPtr.Zero);
        if (hr != 0)
        {
            return null;
        }
        IShellItem result;
        dialog.GetResult(out result);
        IntPtr psz;
        result.GetDisplayName(SIGDN_FILESYSPATH, out psz);
        string path = Marshal.PtrToStringUni(psz);
        Marshal.FreeCoTaskMem(psz);
        return path;
    }
}
'@
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$path = [ModernFolderPicker]::Pick('Elige donde guardar el video', $env:YDL_INITIAL)
if ($path) {
  [Console]::Out.WriteLine($path)
}
"""


def _browse_folder(initial: Path | None) -> tuple[Path | None, str | None, bool]:
    """Abre el selector de Windows. El tercer valor indica si el usuario canceló."""
    if not _browse_available():
        return None, "El explorador de carpetas solo está disponible fuera de Docker en WSL.", False
    powershell = shutil.which("powershell.exe")
    if not powershell:
        return None, "No encuentro el selector de carpetas de Windows.", False
    env = os.environ.copy()
    windows = _wsl_to_windows(initial) if initial is not None else None
    if windows:
        env["YDL_INITIAL"] = windows
    else:
        env.pop("YDL_INITIAL", None)
    try:
        proc = subprocess.run(
            [powershell, "-NoProfile", "-STA", "-Command", _BROWSE_SCRIPT],
            capture_output=True,
            env=env,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return None, "Se agotó el tiempo del selector de carpetas.", False
    except OSError:
        return None, "No pude abrir el selector de carpetas.", False
    chosen = _decode_process_output(proc.stdout).strip()
    if not chosen:
        if proc.returncode not in {0, None}:
            return None, "No pude abrir el selector de carpetas.", False
        return None, None, True
    wsl_path = _windows_to_wsl(chosen)
    if wsl_path is None:
        return None, "Elige una carpeta de un disco de este equipo, como C:.", False
    directory, error = _resolve_output(wsl_path)
    if error or directory is None:
        return None, error or "Esa carpeta no se puede usar.", False
    return directory, None, False


def _suggestions() -> list[dict[str, str]]:
    if _in_docker():
        candidates: list[tuple[str, Path]] = [("Descargas", OUTPUT_DIR)]
    else:
        candidates = [("Proyecto", OUTPUT_DIR)]
        home = Path.home()
        for label, path in (
            ("Videos", home / "Videos"),
            ("Descargas", home / "Descargas"),
            ("Downloads", home / "Downloads"),
        ):
            if path.is_dir():
                candidates.append((label, path))
        users = Path("/mnt/c/Users")
        if users.is_dir():
            entries = []
            try:
                for entry in users.iterdir():
                    try:
                        if entry.is_dir():
                            entries.append(entry)
                    except OSError:
                        continue
            except OSError:
                entries = []
            skip = {"public", "default", "default user", "all users"}
            preferred = home.name.lower()
            entries.sort(key=lambda entry: (entry.name.lower() != preferred, entry.name.lower()))
            for entry in entries:
                if entry.name.lower() in skip or entry.name.startswith("."):
                    continue
                added = False
                for label, folder in (
                    ("Videos de Windows", entry / "Videos"),
                    ("Descargas de Windows", entry / "Downloads"),
                ):
                    try:
                        exists = folder.is_dir()
                    except OSError:
                        exists = False
                    if exists:
                        candidates.append((label, folder))
                        added = True
                if added:
                    break
    seen: set[str] = set()
    rows = []
    for label, path in candidates:
        resolved = path.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        windows = _wsl_to_windows(resolved)
        rows.append(
            {
                "label": label,
                "path": key,
                "hint": windows or _friendly_path(resolved),
            }
        )
    return rows


def _friendly_path(path: Path) -> str:
    windows = _wsl_to_windows(path)
    if windows:
        return windows
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _safe_file(name: str, directory: Path) -> Path | None:
    if not name or name != Path(name).name:
        return None
    root = directory.resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root or not candidate.is_file():
        return None
    if candidate.suffix.lower() in _SKIP_SUFFIXES:
        return None
    return candidate


def _list_files(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    rows = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        if path.name.startswith(".") or path.name.lower() in _SKIP_NAMES:
            continue
        stat = path.stat()
        rows.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "size_label": human_size(stat.st_size),
                "modified": stat.st_mtime,
            }
        )
    rows.sort(key=lambda item: item["modified"], reverse=True)
    return rows[:100]


def _short_error(exc: BaseException) -> str:
    line = str(exc).splitlines()[0].strip() if str(exc).strip() else "Falló la descarga."
    return line[:300]


def _summarize(info: dict) -> dict:
    is_playlist = info.get("_type") == "playlist"
    count = None
    if is_playlist:
        count = info.get("playlist_count") or len(info.get("entries") or [])
    return {
        "title": info.get("title") or "Sin título",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": None if is_playlist else human_duration(info.get("duration")),
        "thumbnail": info.get("thumbnail") or "",
        "is_playlist": is_playlist,
        "count": count,
    }


def _apply_progress(job: dict, status: dict) -> None:
    state = status.get("status")
    info = status.get("info_dict") or {}
    title = info.get("title")
    if title:
        job["title"] = title
    if info.get("playlist_index"):
        job["index"] = info.get("playlist_index")
    count = info.get("n_entries") or info.get("playlist_count")
    if count:
        job["count"] = count
    if state == "downloading":
        downloaded = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        job["status"] = "downloading"
        job["percent"] = round(downloaded / total * 100, 1) if total else job["percent"]
        job["speed"] = (status.get("_speed_str") or "").strip()
        job["eta"] = (status.get("_eta_str") or "").strip()
    elif state == "finished":
        job["status"] = "merging"
        job["percent"] = 100
        job["speed"] = ""
        job["eta"] = ""


def _run_job(job_id: str, url: str, quality: str, playlist: bool, output_dir: Path) -> None:
    def on_progress(status: dict) -> None:
        with _lock:
            job = _jobs.get(job_id)
            if job is None or job.get("cancel"):
                raise DownloadCancelled()
            _apply_progress(job, status)

    try:
        paths = download(url, quality, output_dir, playlist, on_progress=on_progress)
        files = [{"name": path.name, "size_label": human_size(path.stat().st_size)} for path in paths if path.is_file()]
        with _lock:
            job = _jobs[job_id]
            if job.get("cancel"):
                job["status"] = "cancelled"
            else:
                job["status"] = "done"
                job["percent"] = 100
                job["speed"] = ""
                job["eta"] = ""
                job["files"] = files
    except DownloadCancelled:
        with _lock:
            _jobs[job_id]["status"] = "cancelled"
    except (DownloadError, MissingFfmpeg) as exc:
        with _lock:
            job = _jobs[job_id]
            if job.get("cancel"):
                job["status"] = "cancelled"
            else:
                job["status"] = "error"
                job["error"] = _short_error(exc)
    except Exception as exc:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "error"
            job["error"] = _short_error(exc)


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def meta():
    default = OUTPUT_DIR.resolve()
    return jsonify(
        {
            "output_dir": str(default),
            "output_hint": _friendly_path(default),
            "suggestions": _suggestions(),
            "qualities": _quality_payload(),
            "browse_enabled": _browse_available(),
            "docker": _in_docker(),
        }
    )


@app.post("/api/browse")
def browse():
    payload = _read_json()
    initial, _error = _resolve_output(payload.get("output"))
    directory, error, cancelled = _browse_folder(initial or OUTPUT_DIR)
    if error:
        return jsonify({"error": error}), 400
    if cancelled or directory is None:
        return jsonify({"cancelled": True})
    return jsonify(
        {
            "output_dir": str(directory),
            "output_hint": _friendly_path(directory),
            "label": "Carpeta elegida",
        }
    )


@app.get("/api/files")
def files():
    directory, error = _resolve_output(request.args.get("output"))
    if error or directory is None:
        return jsonify({"error": error or "La carpeta no es válida."}), 400
    return jsonify(
        {
            "output_dir": str(directory),
            "output_hint": _friendly_path(directory),
            "files": _list_files(directory),
        }
    )


@app.get("/files/<path:name>")
def file_download(name: str):
    directory, error = _resolve_output(request.args.get("output"))
    if error or directory is None:
        abort(404)
    path = _safe_file(name, directory)
    if path is None:
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.post("/api/info")
def info():
    payload = _read_json()
    url = _clean_url(payload.get("url"))
    if url is None:
        return jsonify({"error": "Pega un enlace que empiece por http:// o https://."}), 400
    playlist = bool(payload.get("playlist"))
    try:
        details = probe(url, playlist)
    except DownloadError as exc:
        return jsonify({"error": f"No se pudo leer esa URL. {exc}"}), 400
    except Exception as exc:
        return jsonify({"error": f"No se pudo leer esa URL. {exc}"}), 400
    body = _summarize(details)
    body["url"] = url
    return jsonify(body)


@app.get("/api/jobs")
def jobs():
    with _lock:
        rows = sorted(_jobs.values(), key=lambda item: item["created"], reverse=True)
        return jsonify({"jobs": [_public_job(job) for job in rows]})


@app.post("/api/download")
def start_download():
    payload = _read_json()
    url = _clean_url(payload.get("url"))
    quality = _clean_quality(payload.get("quality"))
    if url is None:
        return jsonify({"error": "El enlace no es válido."}), 400
    if quality is None:
        return jsonify({"error": "Elige una calidad."}), 400
    playlist = bool(payload.get("playlist"))
    title = payload.get("title") if isinstance(payload.get("title"), str) else ""
    output_dir, output_error = _resolve_output(payload.get("output"))
    if output_error or output_dir is None:
        return jsonify({"error": output_error or "La carpeta no es válida."}), 400
    with _lock:
        if _active_job() is not None:
            return jsonify({"error": "Ya hay una descarga en curso."}), 409
        job = {
            "id": uuid.uuid4().hex[:12],
            "url": url,
            "quality": quality,
            "title": title.strip() or "Video",
            "status": "starting",
            "percent": 0,
            "speed": "",
            "eta": "",
            "index": None,
            "count": None,
            "error": "",
            "output": str(output_dir),
            "files": [],
            "cancel": False,
            "created": time.time(),
        }
        _remember(job)
        job_id = job["id"]
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, url, quality, playlist, output_dir),
        daemon=True,
        name=f"download-{job_id}",
    )
    thread.start()
    with _lock:
        return jsonify({"job": _public_job(_jobs[job_id])})


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": "Esa descarga no existe."}), 404
        if job["status"] not in _ACTIVE:
            return jsonify({"job": _public_job(job)})
        job["cancel"] = True
        return jsonify({"job": _public_job(job)})


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Abre http://{HOST}:{PORT}")
    print(f"Los archivos se guardan en {OUTPUT_DIR.resolve()}")
    app.run(host=HOST, port=PORT, threaded=True)


if __name__ == "__main__":
    main()
