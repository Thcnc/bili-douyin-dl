"""Runtime configuration, persisted to settings.json next to the app."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

FROZEN = bool(getattr(sys, "frozen", False))

# Where the read-only resources (web UI, bundled tools) live.  Inside a
# PyInstaller build this is the unpacked temp folder (``_MEIPASS``).
RESOURCE_DIR = (
    Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    if FROZEN
    else Path(__file__).resolve().parent.parent
)

# Where user data (settings.json) may be written.
APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "bili-douyin-dl" if FROZEN else RESOURCE_DIR

WEB_DIR = RESOURCE_DIR / "web"
BIN_DIR = RESOURCE_DIR / "bin"
SETTINGS_PATH = APP_DIR / "settings.json"

if FROZEN:
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

DEFAULTS: Dict[str, Any] = {
    "download_dir": str(Path.home() / "Videos" / "VideoDownloader"),
    "concurrency": 2,
    "ytdlp_path": "",
    "ffmpeg_path": "",
    "bilibili_cookie": "",
    "douyin_cookie": "",
    "cookie_browser": "",
    "cookie_file": "",
    "filename_template": "%(title)s [%(id)s].%(ext)s",
}

COOKIE_BROWSERS = ("", "chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi", "safari")


def _read_settings() -> Dict[str, Any]:
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged = dict(DEFAULTS)
                merged.update({k: v for k, v in data.items() if k in DEFAULTS})
                return merged
        except (OSError, ValueError):
            pass
    return dict(DEFAULTS)


_settings = _read_settings()


def get(key: str) -> Any:
    return _settings.get(key, DEFAULTS.get(key))


def all_settings() -> Dict[str, Any]:
    """Settings safe to expose to the browser (cookies masked)."""
    data = dict(_settings)
    for key in ("bilibili_cookie", "douyin_cookie"):
        value = data.get(key) or ""
        data[key] = ""
        data[key + "_set"] = bool(value)
    return data


def update(patch: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in patch.items():
        if key not in DEFAULTS or key.endswith("_set"):
            continue
        if key == "concurrency":
            try:
                value = max(1, min(6, int(value)))
            except (TypeError, ValueError):
                continue
        if key == "cookie_browser" and value not in COOKIE_BROWSERS:
            value = ""
        _settings[key] = value
    SETTINGS_PATH.write_text(
        json.dumps(_settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return all_settings()


def ytdlp_cookie_args() -> list:
    """yt-dlp arguments that let it reuse cookies from a local browser."""
    args = []
    browser = (get("cookie_browser") or "").strip()
    if browser:
        args += ["--cookies-from-browser", browser]
    path = (get("cookie_file") or "").strip()
    if path and Path(path).is_file():
        args += ["--cookies", path]
    return args


_PYI_ENV_PREFIXES = ("_PYI_", "_MEIPASS")


def child_env() -> Dict[str, str]:
    """Environment for the bundled tools.

    Our own exe is a PyInstaller build, and yt-dlp.exe is *also* a PyInstaller
    onefile.  PyInstaller exports ``_PYI_*`` / ``_MEIPASS`` variables to child
    processes; a nested onefile inheriting them tries to reuse the parent's
    unpacked folder and dies with "Failed to create parent directory
    structure".  Dropping them makes the child unpack itself normally.

    The temp directory is also redirected into our own app-data folder: if the
    system ``%TEMP%`` is not writable for a spawned process, yt-dlp dies with
    "Could not create temporary directory!" before it can do anything useful.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(_PYI_ENV_PREFIXES)}
    if not _temp_writable(env.get("TEMP") or env.get("TMP") or ""):
        tmp = APP_DIR / "tmp"
        if _temp_writable(str(tmp)):
            env["TMP"] = env["TEMP"] = env["TMPDIR"] = str(tmp)
    return env


def _temp_writable(path: str) -> bool:
    if not path:
        return False
    try:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".vdl_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _first_existing(candidates) -> str:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return ""


_ytdlp_cache: Dict[str, str] = {}
_ytdlp_failure: Dict[str, str] = {}


def _ytdlp_works(exe: str) -> bool:
    if exe in _ytdlp_cache:
        return bool(_ytdlp_cache[exe])
    ok = False
    detail = ""
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=child_env(),
        )
        ok = proc.returncode == 0 and bool(proc.stdout.strip())
        if not ok:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            detail = err.splitlines()[-1] if err else f"退出码 {proc.returncode}"
    except (OSError, subprocess.SubprocessError) as exc:
        detail = f"{type(exc).__name__}: {exc}"
    _ytdlp_cache[exe] = "ok" if ok else ""
    if not ok:
        _ytdlp_failure[exe] = detail
    return ok


def ytdlp_failure() -> str:
    """Why the bundled yt-dlp was rejected, for the UI to show."""
    for exe, detail in reversed(list(_ytdlp_failure.items())):
        return f"{Path(exe).name}: {detail}"
    return ""


def find_ytdlp() -> str:
    candidates = [
        os.environ.get("VDL_YTDLP"),
        get("ytdlp_path"),
        BIN_DIR / "yt-dlp.exe",
        BIN_DIR / "yt-dlp",
        APP_DIR / ".venv" / "Scripts" / "yt-dlp.exe",
        APP_DIR / ".venv" / "bin" / "yt-dlp",
        Path(sys.executable).parent / "Scripts" / "yt-dlp.exe",
        shutil.which("yt-dlp"),
    ]
    for candidate in candidates:
        exe = _first_existing([candidate])
        if exe and _ytdlp_works(exe):
            return exe
    return ""


def find_ffmpeg() -> str:
    configured = get("ffmpeg_path")
    if configured and Path(configured).is_file():
        return configured
    for bundled in (BIN_DIR / "ffmpeg.exe", BIN_DIR / "ffmpeg" / "ffmpeg.exe", BIN_DIR / "ffmpeg"):
        if bundled.is_file():
            return str(bundled)
    which = shutil.which("ffmpeg")
    if which:
        return which
    # ffmpeg is often installed as a pip package next to the interpreter
    for base in {
        Path(os.path.dirname(os.__file__)).parent,
        Path.home() / "AppData" / "Local" / "Programs" / "Python",
    }:
        for candidate in base.glob("**/ffmpeg*/bin/ffmpeg.exe"):
            return str(candidate)
    return ""


def download_dir() -> Path:
    """Return the output directory, creating it and falling back if it is not writable."""
    candidates = [Path(get("download_dir")).expanduser()]
    candidates.append(Path(__file__).resolve().parent.parent / "downloads")
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return path.resolve()
        except OSError:
            continue
    return candidates[-1]
