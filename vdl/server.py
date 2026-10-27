"""Local HTTP API + static file server (standard library only)."""

from __future__ import annotations

import json
import mimetypes
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import config
from .downloader import DownloadManager
from .platforms import parse_many
from .utils import open_folder

MAX_BODY = 1 * 1024 * 1024


class Application:
    def __init__(self) -> None:
        self.manager = DownloadManager()
        self.lock = threading.Lock()

    def state(self) -> Dict[str, Any]:
        return {
            "settings": config.all_settings(),
            "tasks": self.manager.list(),
            "deps": {
                "ytdlp": config.find_ytdlp(),
                "ffmpeg": config.find_ffmpeg(),
                "ytdlp_error": config.ytdlp_failure(),
                "frozen": config.FROZEN,
            },
        }


APP = Application()


class Handler(BaseHTTPRequestHandler):
    server_version = "VideoDL/1.0"

    # ---------------------------------------------------------------- utils
    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _path(self) -> Tuple[str, Dict[str, list]]:
        parsed = urllib.parse.urlparse(self.path)
        return urllib.parse.unquote(parsed.path), urllib.parse.parse_qs(parsed.query)

    # --------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802
        path, _ = self._path()
        try:
            if path == "/":
                return self._serve_file(config.WEB_DIR / "index.html")
            if path == "/api/state":
                return self._json({"ok": True, **APP.state()})
            if path.startswith("/static/"):
                return self._serve_file(config.WEB_DIR / path[len("/static/") :])
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            return self._error("Not found", 404)
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), 500)

    def do_POST(self) -> None:  # noqa: N802
        path, _ = self._path()
        try:
            if path == "/api/parse":
                return self._handle_parse()
            if path == "/api/download":
                return self._handle_download()
            if path == "/api/settings":
                return self._handle_settings()
            if path == "/api/open-folder":
                return self._handle_open()
            if path == "/api/tasks/clear":
                APP.manager.clear_finished()
                return self._json({"ok": True, "tasks": APP.manager.list()})
            return self._error("Not found", 404)
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), 500)

    def do_DELETE(self) -> None:  # noqa: N802
        path, _ = self._path()
        parts = [p for p in path.split("/") if p]
        try:
            if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                task_id = parts[2]
                if APP.manager.cancel(task_id):
                    return self._json({"ok": True})
                if APP.manager.remove(task_id):
                    return self._json({"ok": True})
                return self._error("任务不存在或仍在运行", 404)
            return self._error("Not found", 404)
        except Exception as exc:  # noqa: BLE001
            return self._error(str(exc), 500)

    # -------------------------------------------------------------- handlers
    def _handle_parse(self) -> None:
        data = self._body()
        text = (data.get("text") or "").strip()
        if not text:
            return self._error("请粘贴视频链接")
        cookies = {
            "bilibili": config.get("bilibili_cookie"),
            "douyin": config.get("douyin_cookie"),
        }
        items, errors = parse_many(text, cookies)
        return self._json(
            {
                "ok": bool(items),
                "items": [item.to_dict() for item in items],
                "errors": errors,
            }
        )

    def _handle_download(self) -> None:
        data = self._body()
        item = data.get("item") or {}
        quality = data.get("quality") or "best"
        if not isinstance(item, dict) or not item.get("platform") or not item.get("title"):
            return self._error("缺少视频信息，请先解析")
        task = APP.manager.submit(item, quality)
        return self._json({"ok": True, "task": task.to_dict()})

    def _handle_settings(self) -> None:
        data = self._body()
        updated = config.update(data)
        return self._json({"ok": True, "settings": updated})

    def _handle_open(self) -> None:
        open_folder(config.download_dir())
        return self._json({"ok": True, "path": str(config.download_dir())})

    def _serve_file(self, file_path: Path) -> None:
        root = config.WEB_DIR.resolve()
        target = file_path.resolve()
        if root not in target.parents and target != root:
            return self._error("Forbidden", 403)
        if not target.is_file():
            return self._error("Not found", 404)
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript",):
            content_type += "; charset=utf-8"
        self._send(200, target.read_bytes(), content_type)


def serve(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd
