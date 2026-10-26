"""Download the external tools the app needs (yt-dlp, optionally ffmpeg).

Usage:
    python scripts/fetch_deps.py                # yt-dlp only (~30 MB)
    python scripts/fetch_deps.py --with-ffmpeg  # also ffmpeg (~90 MB)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"

YTDLP_URLS = [
    "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://ghfast.top/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
    "https://gh-proxy.com/https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe",
]
FFMPEG_URLS = [
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://ghfast.top/https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip",
]


def _progress(done: int, total: int) -> None:
    if total <= 0:
        return
    percent = min(100, done * 100 // total)
    sys.stdout.write(f"\r  {percent:3d}%  {done / 1048576:.1f}/{total / 1048576:.1f} MB")
    sys.stdout.flush()


def _download_once(url: str, tmp: Path) -> None:
    offset = tmp.stat().st_size if tmp.exists() else 0
    headers = {"User-Agent": "Mozilla/5.0"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        if offset and resp.status != 206:
            offset = 0  # server ignored the range request, restart
            tmp.unlink(missing_ok=True)
        total = int(resp.headers.get("Content-Length") or 0) + offset
        done = offset
        mode = "ab" if offset else "wb"
        with open(tmp, mode) as fh:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                _progress(done, total)


def download(urls, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_error = ""
    for attempt in range(6):
        url = urls[attempt % len(urls)]
        try:
            print(f"下载 {url}（第 {attempt + 1} 次）")
            _download_once(url, tmp)
            if dest.exists():
                dest.unlink()
            tmp.replace(dest)
            print()
            return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            print(f"\n  中断：{last_error}，正在重试…")
            time.sleep(1.5)
    raise SystemExit(f"下载失败：{last_error}")


def fetch_ytdlp() -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    dest = BIN / "yt-dlp.exe"
    download(YTDLP_URLS, dest)
    try:
        proc = subprocess.run([str(dest), "--version"], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        proc = None
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        dest.unlink(missing_ok=True)
        raise SystemExit("yt-dlp 下载后无法运行，请检查网络后重试")
    print(f"yt-dlp 已就绪: {dest}（{proc.stdout.decode(errors='replace').strip()}）")


def fetch_ffmpeg() -> None:
    BIN.mkdir(parents=True, exist_ok=True)
    archive = BIN / "ffmpeg.zip"
    download(FFMPEG_URLS, archive)
    print("解压 ffmpeg ...")
    target = BIN / "ffmpeg"
    if target.exists():
        shutil.rmtree(target)
    with zipfile.ZipFile(archive) as zf:
        names = [n for n in zf.namelist() if n.endswith("bin/ffmpeg.exe")]
        if not names:
            raise SystemExit("压缩包里没有找到 ffmpeg.exe")
        prefix = names[0][: -len("bin/ffmpeg.exe")]
        for member in zf.namelist():
            if member.startswith(prefix) and (
                member.endswith("ffmpeg.exe") or member.endswith("ffprobe.exe")
            ):
                zf.extract(member, BIN)
    extracted = next(BIN.glob("ffmpeg-*/bin/ffmpeg.exe"), None)
    if extracted:
        target.mkdir(exist_ok=True)
        for exe in extracted.parent.iterdir():
            shutil.copy2(exe, target / exe.name)
    archive.unlink(missing_ok=True)
    print(f"ffmpeg 已就绪: {target / 'ffmpeg.exe'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 yt-dlp / ffmpeg")
    parser.add_argument("--with-ffmpeg", action="store_true", help="同时下载 ffmpeg（合并高清音视频需要）")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    fetch_ytdlp()
    if args.with_ffmpeg:
        fetch_ffmpeg()
    else:
        print("提示: B站 1080P/大会员清晰度需要 ffmpeg 合并音视频，可加 --with-ffmpeg 下载")


if __name__ == "__main__":
    main()
