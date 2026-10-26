"""Small HTTP / filesystem helpers shared by the parsers and the downloader."""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
)

_ILLEGAL = re.compile(r'[\\/:*?"<>|\r\n\t\x00-\x1f]')


@dataclass
class Response:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        import json

        return json.loads(self.text)


def http_request(
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    method: str = "GET",
    data: Optional[bytes] = None,
    timeout: float = 20,
    read_body: bool = True,
) -> Response:
    """HTTP request with a browser-ish default UA. Raises HTTPError for >=400."""
    hdrs = {"User-Agent": DESKTOP_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read() if read_body else b""
            return Response(resp.status, resp.geturl(), dict(resp.headers), body)
    except urllib.error.HTTPError as exc:
        body = exc.read() if read_body else b""
        return Response(exc.code, exc.geturl() or url, dict(exc.headers or {}), body)


def sanitize_filename(name: str, max_length: int = 120) -> str:
    name = _ILLEGAL.sub(" ", name or "").strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "video"


def human_bytes(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def human_duration(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def unique_path(path: Path) -> Path:
    """Return a non-existing path by appending (1), (2), ... before the suffix."""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(1, 1000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    return path


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        import subprocess

        subprocess.Popen(["xdg-open", str(path)])
