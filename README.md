# 本地视频下载器 · B站 / 抖音

一个完全跑在本机的视频解析下载工具：**本地网页界面 + 本地 HTTP 服务**，不上传任何数据，不需要注册账号，粘贴链接就能解析、选清晰度、下载到本地。

> 当前支持：哔哩哔哩（含 UP 主多 P 视频）、抖音（单条视频）。

## 特性

- **纯本地运行**：`python app.py` 启动一个 `127.0.0.1` 服务，浏览器打开即用
- **B站**：分享链接 / BV 号 / 多 P 视频，可选 1080P、720P、480P、360P、仅音频
- **抖音**：分享短链、`douyin.com/video/…`、整段分享文本都能识别
- **批量解析**：一次粘贴多条链接或整段分享文案
- **下载队列**：并发下载、实时进度 / 速度 / 剩余时间、取消任务、清除记录
- **不挑环境**：界面只用原生 HTML/CSS/JS，后端只用 Python 标准库
- **中文界面**，暗色主题，无广告、无捆绑

## 快速开始

需要 Python 3.10+（Windows 上安装时记得勾选 *Add python.exe to PATH*）。

```bash
git clone https://github.com/Thcnc/bili-douyin-dl.git
cd bili-douyin-dl
python scripts/fetch_deps.py --with-ffmpeg   # 下载 yt-dlp 和 ffmpeg 到 bin/
python app.py                                # 自动打开 http://127.0.0.1:8765/
```

或者直接双击 `run.bat`（Windows）。

不想装 Python？下载 [Releases](https://github.com/Thcnc/bili-douyin-dl/releases) 里的 `BiliDouyinDL-win64.zip`，解压后双击里面的 `BiliDouyinDL.exe` 即可：内置 yt-dlp 和 ffmpeg，不需要任何环境依赖，也不联网下载组件。

> 注：**单文件** exe（`--onefile`）每次启动都要把自己解压到临时目录，某些机器（安全软件、TEMP 不可写）会报 `could not create temporary directory`。所以默认发布**文件夹版**，启动快且更可靠。

启动后：

1. 把视频链接粘贴到输入框（可以一次粘多条）；
2. 点「解析链接」，选择清晰度；
3. 点「下载」，文件保存在设置里的下载目录（默认 `~/Videos/VideoDownloader`）。

## 抖音需要一次性的 Cookie 设置

抖音对未登录的网页请求有风控（`Uifid Not Found` / `Fresh cookies … are needed`）。程序会依次尝试分享页、公开接口，最后交给 yt-dlp；若仍失败：

1. 用本机浏览器打开一次 <https://www.douyin.com/>（不用登录也可以）；
2. 打开程序的「设置 → Cookie 来源（本机浏览器）」，选择你用的浏览器（Edge / Chrome / Firefox …），保存；
3. 重新解析抖音链接即可。

也可以把浏览器导出的 `cookies.txt` 填到「cookies.txt 路径」。B站 1080P（大会员清晰度）同样可以在设置里填 `SESSDATA` 等 Cookie 后解锁。

## 打包成 exe

```bash
python -m pip install pyinstaller
python scripts/build_exe.py             # 文件夹版 dist/BiliDouyinDL/（推荐）
python scripts/build_exe.py --onefile   # 单文件版 dist/BiliDouyinDL.exe（启动慢，可能被安全软件拦截）
```

打包前请确保 `bin/yt-dlp.exe`、`bin/ffmpeg/ffmpeg.exe` 已就位（`python scripts/fetch_deps.py --with-ffmpeg` 会自动放好），它们会被一起打进 exe，用户机器上无需再下载。

## 命令行参数

```bash
python app.py --port 9000      # 换端口
python app.py --no-browser     # 启动后不自动开浏览器
python app.py --host 0.0.0.0   # 给局域网其它设备用（默认只监听本机）
```

## 项目结构

```
bili-douyin-dl/
├─ app.py                  # 入口：起服务 + 打开浏览器
├─ run.bat                 # Windows 一键启动
├─ scripts/fetch_deps.py   # 下载 yt-dlp / ffmpeg 到 bin/
├─ scripts/build_exe.py    # PyInstaller 打包成 exe
├─ vdl/
│  ├─ server.py            # 本地 HTTP API + 静态文件服务（标准库）
│  ├─ downloader.py        # 下载队列、进度解析、取消
│  ├─ config.py            # 设置持久化、依赖探测
│  ├─ ytdlp.py             # yt-dlp 封装（元数据 / Cookie 参数）
│  ├─ utils.py             # HTTP、文件命名、系统工具
│  └─ platforms/
│     ├─ bilibili.py       # B站解析（view / pagelist 接口）
│     └─ douyin.py         # 抖音解析（分享页 → 公开接口 → yt-dlp）
└─ web/                    # 前端（原生 JS）
```

## 常见问题

**B站下载很慢或提示需要登录？**
1080P 及以上需要登录 Cookie；在设置里填入浏览器里 `bilibili.com` 的 Cookie（至少 `SESSDATA`）即可。

**抖音解析失败？**
按上面「抖音需要一次性的 Cookie 设置」操作；仍失败时通常是链接已删除或作品为图文。

**下载的文件在哪里？**
点右上角「下载目录」按钮会直接在资源管理器里打开。

**会被封号吗？**
程序只读取公开页面、以普通浏览器身份请求，不调用登录态接口、不批量刷接口；正常个人使用即可。请遵守平台条款。

## 免责声明

本项目仅供个人学习、技术研究与**自己作品的备份**使用。请勿用于批量抓取、二次分发或任何侵犯版权与平台条款的用途；由此产生的责任由使用者自行承担。

## License

[MIT](LICENSE)
