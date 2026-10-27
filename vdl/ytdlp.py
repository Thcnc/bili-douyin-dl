"""Thin wrapper around the bundled yt-dlp executable.

Used as a fallback for Douyin (whose web API is gated behind a signed request)
and as the shared downloader for Bilibili / quality selection.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List

from . import config
from .platforms.base import ParseError


def executable() -> str:
    exe = config.find_ytdlp()
    if not exe:
        raise ParseError("未找到 yt-dlp，请运行 python scripts/fetch_deps.py 或在设置中指定路径")
    return exe


def base_args() -> List[str]:
    """Common flags: quiet, cookies, ffmpeg location."""
    args: List[str] = [executable(), "--no-warnings", "--no-color"]
    ffmpeg = config.find_ffmpeg()
    if ffmpeg:
        args[1:1] = ["--ffmpeg-location", os.path.dirname(ffmpeg)]
    args += config.ytdlp_cookie_args()
    return args


def fetch_info(url: str, timeout: int = 120) -> Dict[str, Any]:
    """Return yt-dlp's metadata JSON for one URL."""
    cmd = base_args() + ["--no-playlist", "-J", url]
    creation = 0
    if os.name == "nt":
        creation = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creation,
            env=config.child_env(),
        )
    except subprocess.TimeoutExpired:
        raise ParseError("yt-dlp 解析超时，请稍后重试")
    if proc.returncode != 0 or not proc.stdout.strip():
        lines = [line.strip() for line in (proc.stderr or "").splitlines() if line.strip()]
        detail = next((line for line in reversed(lines) if line.startswith("ERROR")), "")
        detail = detail or (lines[-1] if lines else f"退出码 {proc.returncode}")
        raise ParseError(f"yt-dlp 解析失败：{detail}")
    try:
        return json.loads(proc.stdout)
    except ValueError:
        raise ParseError("yt-dlp 返回的数据无法解析")


def item_from_info(info: Dict[str, Any], platform: str) -> Dict[str, Any]:
    """Normalise a yt-dlp info dict into our VideoItem kwargs."""
    title = (info.get("title") or info.get("description") or "视频").strip() or "视频"
    return {
        "platform": platform,
        "video_id": str(info.get("id") or ""),
        "title": title,
        "author": info.get("uploader") or info.get("channel") or "",
        "cover": info.get("thumbnail") or "",
        "duration": int(info.get("duration") or 0),
        "page_url": info.get("webpage_url") or "",
        "page": 0,
        "extra": {"use_ytdlp": True},
    }
