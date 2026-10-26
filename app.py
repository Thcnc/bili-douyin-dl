"""Local video downloader for Bilibili and Douyin.

Run ``python app.py`` and open the printed URL in a browser.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
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


def main() -> None:
    parser = argparse.ArgumentParser(description="B站 / 抖音 本地视频下载器")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

    port = _free_port(args.host, args.port)
    url = f"http://{args.host}:{port}/"
    httpd = serve(args.host, port)

    missing = []
    if not config.find_ytdlp():
        missing.append("yt-dlp（运行 python scripts/fetch_deps.py）")
    if not config.find_ffmpeg():
        missing.append("ffmpeg（B站高清需要合并音视频）")

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


if __name__ == "__main__":
    main()
