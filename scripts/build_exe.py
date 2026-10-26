"""Build a single-file Windows executable with PyInstaller.

    python -m pip install pyinstaller
    python scripts/build_exe.py            # onefile exe in dist/
    python scripts/build_exe.py --onedir   # portable folder instead

The exe bundles the web UI, yt-dlp and ffmpeg, so the result runs on a machine
without Python installed and without any first-run downloads.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "BiliDouyinDL"
BIN = ROOT / "bin"
ICON = ROOT / "assets" / "app.ico"


def main() -> None:
    parser = argparse.ArgumentParser(description="打包为独立 exe")
    parser.add_argument("--onedir", action="store_true", help="打包成文件夹（启动更快）")
    args = parser.parse_args()

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("缺少 PyInstaller，请先运行： python -m pip install pyinstaller")

    datas = [(ROOT / "web", "web")]
    ytdlp = BIN / "yt-dlp.exe"
    if ytdlp.is_file():
        datas.append((ytdlp, "bin"))
    else:
        print("警告: 未找到 bin/yt-dlp.exe，打包后需要用户自行安装 yt-dlp")

    ffmpeg = BIN / "ffmpeg" / "ffmpeg.exe"
    if not ffmpeg.is_file():
        ffmpeg = BIN / "ffmpeg.exe"
    if ffmpeg.is_file():
        datas.append((ffmpeg, "bin/ffmpeg"))
        ffprobe = ffmpeg.with_name("ffprobe.exe")
        if ffprobe.is_file() and os.environ.get("VDL_BUNDLE_FFPROBE") == "1":
            datas.append((ffprobe, "bin/ffmpeg"))
        print(f"打包 ffmpeg: {ffmpeg}")
    else:
        print("警告: 未找到 ffmpeg（bin/ffmpeg/ffmpeg.exe），打包后高清（DASH）合并会不可用")

    dist = ROOT / "dist"
    target = dist / (NAME + ("" if args.onedir else ".exe"))
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    elif target.exists():
        target.unlink()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir" if args.onedir else "--onefile",
        "--windowed",
        "--name",
        NAME,
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
    ]
    if ICON.is_file():
        cmd += ["--icon", str(ICON)]
    for src, dest in datas:
        cmd += ["--add-data", f"{src}{';' if sys.platform == 'win32' else ':'}{dest}"]
    cmd.append(str(ROOT / "app.py"))

    print(" ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    target = ROOT / "dist" / (NAME if args.onedir else NAME + ".exe")
    size = (
        sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        if target.is_dir()
        else target.stat().st_size
    )
    print(f"\n完成: {target}  ({size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
