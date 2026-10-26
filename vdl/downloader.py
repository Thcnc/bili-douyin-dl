"""Download task queue.

Bilibili is downloaded through yt-dlp (DASH video+audio merging, multi-part
support, cookie based quality). Douyin is a plain progressive MP4, so it is
streamed directly to disk with Range-free chunked writes.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .utils import MOBILE_UA, human_bytes, sanitize_filename, unique_path

PROGRESS_TEMPLATE = (
    "download:%(progress.downloaded_bytes)s/%(progress.total_bytes)s/"
    "%(progress.total_bytes_estimate)s/%(progress.speed)s/%(progress.eta)s"
)

QUALITY_FORMAT = {
    "best": "bv*+ba/b",
    "1080p": "bv*[height<=1080]+ba/b[height<=1080]/bv*+ba/b",
    "720p": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
    "480p": "bv*[height<=480]+ba/b[height<=480]/bv*+ba/b",
    "360p": "bv*[height<=360]+ba/b[height<=360]/bv*+ba/b",
    "audio": "ba/b",
}


@dataclass
class Task:
    id: str
    platform: str
    video_id: str
    title: str
    author: str = ""
    cover: str = ""
    duration: int = 0
    page_url: str = ""
    quality: str = "best"
    page: int = 0
    extra: Dict = field(default_factory=dict)
    status: str = "queued"
    progress: float = 0.0
    speed: Optional[float] = None
    eta: Optional[int] = None
    total_bytes: Optional[int] = None
    filepath: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _process: Optional[subprocess.Popen] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "video_id": self.video_id,
            "title": self.title,
            "author": self.author,
            "cover": self.cover,
            "duration": self.duration,
            "page_url": self.page_url,
            "quality": self.quality,
            "status": self.status,
            "progress": round(self.progress, 1),
            "speed": self.speed,
            "speed_text": human_bytes(self.speed) + "/s" if self.speed else "",
            "eta": self.eta,
            "total_bytes": self.total_bytes,
            "size_text": human_bytes(self.total_bytes) if self.total_bytes else "",
            "filepath": self.filepath,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class DownloadManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(int(config.get("concurrency") or 2))

    # ------------------------------------------------------------------ API
    def submit(self, item: dict, quality: str = "best") -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            platform=item["platform"],
            video_id=item.get("video_id", ""),
            title=item.get("title") or "未命名视频",
            author=item.get("author", ""),
            cover=item.get("cover", ""),
            duration=int(item.get("duration") or 0),
            page_url=item.get("page_url", ""),
            quality=quality,
            page=int(item.get("page") or 0),
            extra=item.get("extra") or {},
        )
        with self._lock:
            self._tasks[task.id] = task
        threading.Thread(target=self._run, args=(task,), daemon=True).start()
        return task

    def list(self) -> List[dict]:
        with self._lock:
            tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks]

    def get(self, task_id: str) -> Optional[Task]:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if not task or task.status in ("done", "error", "canceled"):
            return False
        task._cancel.set()
        proc = task._process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        task.status = "canceled"
        task.finished_at = time.time()
        return True

    def remove(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in ("queued", "downloading", "processing"):
                return False
            del self._tasks[task_id]
            return True

    def clear_finished(self) -> None:
        with self._lock:
            for key in [k for k, t in self._tasks.items() if t.status in ("done", "error", "canceled")]:
                del self._tasks[key]

    # ------------------------------------------------------------- internal
    def _run(self, task: Task) -> None:
        with self._semaphore:
            if task._cancel.is_set():
                return
            task.status = "downloading"
            try:
                if task.platform == "bilibili":
                    self._download_bilibili(task)
                elif task.platform == "douyin":
                    self._download_douyin(task)
                else:
                    raise RuntimeError(f"未知平台：{task.platform}")
                if task._cancel.is_set():
                    task.status = "canceled"
                else:
                    task.status = "done"
                    task.progress = 100.0
            except Exception as exc:  # noqa: BLE001
                if task._cancel.is_set():
                    task.status = "canceled"
                else:
                    task.status = "error"
                    task.error = str(exc)
            finally:
                task.speed = None
                task.eta = None
                task.finished_at = time.time()

    # ----------------------------------------------------------- bilibili
    def _cookie_file(self, cookie: str, domain: str) -> Optional[str]:
        cookie = (cookie or "").strip()
        if not cookie:
            return None
        handle, path = tempfile.mkstemp(suffix=".txt", prefix="vdl-cookies-")
        os.close(handle)
        lines = ["# Netscape HTTP Cookie File"]
        for part in cookie.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            lines.append("\t".join([domain, "TRUE", "/", "FALSE", "4102444800", name.strip(), value.strip()]))
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def _download_bilibili(self, task: Task) -> None:
        self._download_with_ytdlp(
            task,
            QUALITY_FORMAT.get(task.quality, QUALITY_FORMAT["best"]),
            playlist_item=task.page,
        )

    def _download_with_ytdlp(
        self, task: Task, fmt: str, playlist_item: int = 0, page_url: str = ""
    ) -> None:
        ytdlp = config.find_ytdlp()
        if not ytdlp:
            raise RuntimeError("未找到 yt-dlp，请运行 scripts/fetch_deps.py 或在设置中指定路径")

        out_dir = config.download_dir()
        out_tmpl = str(out_dir / config.get("filename_template"))
        report_fd, report_name = tempfile.mkstemp(prefix="vdl-report-", suffix=".txt")
        os.close(report_fd)
        report = Path(report_name)
        cookie = config.get("bilibili_cookie") if task.platform == "bilibili" else ""
        cookie_file = self._cookie_file(cookie, ".bilibili.com")
        ffmpeg = config.find_ffmpeg()

        cmd = [
            ytdlp,
            "--newline",
            "--no-warnings",
            "--no-color",
            "--windows-filenames",
            "--trim-filenames",
            "120",
            "--concurrent-fragments",
            "4",
            "--progress-template",
            PROGRESS_TEMPLATE,
            "--print-to-file",
            "after_move:filepath",
            str(report),
            "-f",
            fmt,
            "-o",
            out_tmpl,
        ]
        if ffmpeg:
            cmd[1:1] = ["--ffmpeg-location", os.path.dirname(ffmpeg)]
        if cookie_file:
            cmd[1:1] = ["--cookies", cookie_file]
        else:
            cmd[1:1] = config.ytdlp_cookie_args()
        if playlist_item:
            cmd[1:1] = ["--playlist-items", str(playlist_item)]
        cmd.append(page_url or task.page_url or f"https://www.bilibili.com/video/{task.video_id}")

        try:
            self._run_process(task, cmd, on_line=self._parse_ytdlp_progress)
            if not task._cancel.is_set():
                task.filepath = self._read_reported_path(report, out_dir)
        finally:
            report.unlink(missing_ok=True)
            if cookie_file:
                Path(cookie_file).unlink(missing_ok=True)
        if task._cancel.is_set():
            return
        task.status = "processing"
        if not task.filepath:
            raise RuntimeError("下载完成但未找到输出文件")

    def _read_reported_path(self, report: Path, out_dir: Path) -> str:
        try:
            lines = [line.strip() for line in report.read_text(encoding="utf-8").splitlines() if line.strip()]
            if lines:
                return lines[-1]
        except OSError:
            pass
        newest = sorted(out_dir.glob("**/*"), key=lambda p: p.stat().st_mtime, reverse=True)
        return str(newest[0]) if newest else ""

    def _parse_ytdlp_progress(self, task: Task, line: str) -> None:
        if not line.startswith("download:"):
            return
        payload = line[len("download:") :].split("/")
        if len(payload) < 5:
            return
        downloaded, total, estimate, speed, eta = payload[:5]
        try:
            total_bytes = int(float(total)) if total not in ("NA", "None") else int(float(estimate))
        except (TypeError, ValueError):
            total_bytes = 0
        try:
            done_bytes = int(float(downloaded))
        except (TypeError, ValueError):
            done_bytes = 0
        if total_bytes > 0:
            task.total_bytes = total_bytes
            task.progress = min(99.0, done_bytes / total_bytes * 100)
        try:
            task.speed = float(speed) if speed not in ("NA", "None") else None
        except ValueError:
            task.speed = None
        try:
            task.eta = int(float(eta)) if eta not in ("NA", "None") else None
        except ValueError:
            task.eta = None

    # ------------------------------------------------------------- douyin
    def _download_douyin(self, task: Task) -> None:
        url = (task.extra or {}).get("play_url")
        if url and not task.extra.get("use_ytdlp"):
            try:
                self._download_douyin_direct(task, url)
                return
            except Exception:  # noqa: BLE001 - CDN links expire, retry via yt-dlp
                if task._cancel.is_set():
                    return
        fmt = "ba/b" if task.quality == "audio" else "bv*+ba/b"
        self._download_with_ytdlp(task, fmt, page_url=task.page_url)

    def _download_douyin_direct(self, task: Task, url: str) -> None:
        out_dir = config.download_dir()
        name = sanitize_filename(f"{task.title} [{task.video_id}]") + ".mp4"
        dest = unique_path(out_dir / name)
        partial = dest.with_suffix(".mp4.part")

        headers = {
            "User-Agent": MOBILE_UA,
            "Referer": "https://www.douyin.com/",
            "Accept": "*/*",
        }
        cookie = config.get("douyin_cookie")
        if cookie:
            headers["Cookie"] = cookie

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as resp, open(partial, "wb") as fh:
                total = int(resp.headers.get("Content-Length") or 0)
                task.total_bytes = total or None
                done = 0
                start = time.time()
                while True:
                    if task._cancel.is_set():
                        return
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    elapsed = time.time() - start
                    if total:
                        task.progress = min(99.0, done / total * 100)
                    task.speed = done / elapsed if elapsed > 0.5 else None
                    task.eta = int((total - done) / task.speed) if total and task.speed else None
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        if task._cancel.is_set():
            partial.unlink(missing_ok=True)
            return
        partial.replace(dest)
        task.filepath = str(dest)

    # --------------------------------------------------------------- utils
    def _run_process(self, task: Task, cmd: List[str], on_line=None) -> None:
        creation = 0
        if os.name == "nt":
            creation = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creation,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        task._process = proc
        assert proc.stdout is not None
        errors: List[str] = []
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if line.startswith("ERROR:"):
                errors.append(line)
                errors = errors[-3:]
            if line and on_line:
                on_line(task, line)
            if task._cancel.is_set():
                proc.terminate()
                break
        proc.wait()
        if proc.returncode not in (0, None) and not task._cancel.is_set():
            detail = " | ".join(errors) or "无错误输出"
            raise RuntimeError(f"下载失败（退出码 {proc.returncode}）：{detail}")
