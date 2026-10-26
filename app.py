"""Local video downloader for Bilibili and Douyin.

Run ``python app.py`` and open the printed URL in a browser.
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vdl import config  # noqa: E402
from vdl.server import serve  # noqa: E402


def _free_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit("没有可用端口，请用 --port 指定")


def _log_line(message: str) -> None:
    """Append a line to app.log when running as a windowed exe (no console)."""
    if not config.FROZEN:
        return
    try:
        log_path = config.APP_DIR / "app.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except OSError:
        pass


def _log_fatal(exc: BaseException) -> None:
    """Write the traceback to a log file and tell the user (windowed exe has no console)."""
    import traceback

    detail = "".join(traceback.format_exception(exc))
    log_path = None
    for candidate in (config.APP_DIR / "app.log", Path(sys.executable).parent / "app.log"):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with open(candidate, "a", encoding="utf-8") as fh:
                fh.write(detail + "\n")
            log_path = candidate
            break
        except OSError:
            continue
    try:
        import ctypes

        message = f"启动失败：{exc}\n\n详细日志：{log_path}" if log_path else f"启动失败：{exc}"
        ctypes.windll.user32.MessageBoxW(None, message, "视频下载器", 0x10)
    except Exception:  # noqa: BLE001
        print(detail)


def main() -> None:
    parser = argparse.ArgumentParser(description="B站 / 抖音 本地视频下载器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    if sys.stdout is None:  # windowed (--noconsole) builds
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    port = _free_port(args.host, args.port)
    try:
        httpd = serve(args.host, port)
    except OSError:
        port = _free_port(args.host, port + 1)
        httpd = serve(args.host, port)
    url = f"http://{args.host}:{port}/"

    missing = []
    if not config.find_ytdlp():
        missing.append("yt-dlp（运行 python scripts/fetch_deps.py）")
    if not config.find_ffmpeg():
        missing.append("ffmpeg（B站高清需要合并音视频）")

    _log_line(f"启动 pid={os.getpid()} url={url} ytdlp={config.find_ytdlp() or '-'} ffmpeg={config.find_ffmpeg() or '-'}")

    print("=" * 56)
    print("  B站 / 抖音 视频下载器")
    print(f"  界面地址: {url}")
    print(f"  下载目录: {config.download_dir()}")
    if missing:
        print("  缺少依赖: " + "、".join(missing))
    print("  按 Ctrl+C 退出")
    print("=" * 56)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        httpd.server_close()
        _log_line("正常退出")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        _log_fatal(exc)
        raise
