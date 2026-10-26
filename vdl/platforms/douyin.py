"""Douyin (抖音) link parsing.

Douyin's web API is protected by an ``a_bogus`` signature, so this parser walks
the public share page instead: the page embeds ``window._ROUTER_DATA`` with the
full aweme payload, including a playable, watermark-free stream id.

Supported inputs:
  * https://v.douyin.com/xxxxxxx/      (share short link)
  * https://www.douyin.com/video/123   (desktop link)
  * https://www.iesdouyin.com/share/video/123/
  * a whole share text pasted from the app
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from ..utils import MOBILE_UA, http_request
from .base import QUALITY_PRESETS, ParseError, VideoItem

SHORT_HOSTS = ("v.douyin.com", "v.iesdouyin.com")
HOSTS = ("douyin.com", "iesdouyin.com")
URL_RE = re.compile(r"https?://[^\s，。<>\"']+")
ID_RE = re.compile(r"/(?:video|note|slides)/(\d{5,})")
MODAL_RE = re.compile(r"[?&]modal_id=(\d{5,})")
ROUTER_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)
PLAY_API = "https://www.iesdouyin.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0"


def matches(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def extract_url(text: str) -> str:
    match = URL_RE.search(text or "")
    if not match:
        raise ParseError("没有找到抖音链接，请粘贴完整分享文本")
    return match.group(0).rstrip(".,;)")


def _headers(cookie: str = "") -> dict:
    headers = {
        "User-Agent": MOBILE_UA,
        "Referer": "https://www.douyin.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def _resolve(url: str, cookie: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in SHORT_HOSTS):
        resp = http_request(url, headers=_headers(cookie), read_body=False)
        return resp.url
    return url


def _video_id(url: str) -> str:
    match = ID_RE.search(url) or MODAL_RE.search(url)
    if not match:
        raise ParseError("未识别出抖音作品 ID，请使用视频分享链接")
    return match.group(1)


def _fetch_share_page(video_id: str, cookie: str) -> dict:
    page_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    resp = http_request(page_url, headers=_headers(cookie))
    if resp.status != 200:
        raise ParseError(f"抖音页面请求失败（HTTP {resp.status}）")
    match = ROUTER_RE.search(resp.text)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except ValueError:
        return {}


def _fetch_item_api(video_id: str, cookie: str) -> dict:
    api = f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={video_id}"
    try:
        resp = http_request(api, headers=_headers(cookie))
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return {}
    items = payload.get("item_list") or []
    return items[0] if items else {}


def _pick_item(router: dict, video_id: str) -> dict:
    loader = router.get("loaderData") or {}
    for value in loader.values():
        if isinstance(value, dict):
            info = value.get("videoInfoRes") or {}
            items = info.get("item_list") or []
            if items:
                return items[0]
    return {}


def _best_stream(video: dict) -> tuple[str, int]:
    """Return (watermark-free play url, approximate size)."""
    uri = (video.get("play_addr") or {}).get("uri") or ""
    best_size = 0
    for rate in video.get("bit_rate") or []:
        addr = rate.get("play_addr") or {}
        if addr.get("url_list") and (rate.get("bit_rate") or 0) > 0:
            # keep the uri of the highest bitrate variant, but always fetch
            # through the official play endpoint so no watermark is applied
            uri = uri or addr.get("uri", "")
    if uri:
        return PLAY_API.format(uri=uri), best_size
    for key in ("play_addr", "play_addr_h264", "download_addr"):
        urls = ((video.get(key) or {}).get("url_list")) or []
        if urls:
            return urls[0], best_size
    return "", 0


def parse(url: str, cookie: str = "") -> list[VideoItem]:
    url = extract_url(url)
    url = _resolve(url, cookie)
    video_id = _video_id(url)

    item = _pick_item(_fetch_share_page(video_id, cookie), video_id) or _fetch_item_api(
        video_id, cookie
    )

    if item.get("images"):
        raise ParseError("这是图文作品，暂不支持下载")

    play_url = ""
    if item:
        play_url, _ = _best_stream(item.get("video") or {})

    if not item or not play_url:
        return [_from_ytdlp(video_id)]

    video = item.get("video") or {}
    cover = ""
    for key in ("cover", "dynamic_cover", "origin_cover"):
        urls = ((video.get(key) or {}).get("url_list")) or []
        if urls:
            cover = urls[0]
            break

    author = (item.get("author") or {}).get("nickname", "")
    title = (item.get("desc") or "抖音视频").strip() or "抖音视频"
    duration = int((video.get("duration") or 0) / 1000)

    return [
        VideoItem(
            platform="douyin",
            video_id=video_id,
            title=title,
            author=author,
            cover=cover,
            duration=duration,
            page_url=f"https://www.douyin.com/video/{video_id}",
            extra={"play_url": play_url, "aweme_id": video_id},
            qualities=QUALITY_PRESETS["douyin"],
        )
    ]


def _from_ytdlp(video_id: str) -> VideoItem:
    """Fallback path: let yt-dlp fetch the metadata (it handles the signature)."""
    from .. import ytdlp

    try:
        info = ytdlp.fetch_info(f"https://www.douyin.com/video/{video_id}")
    except ParseError as exc:
        detail = str(exc).rstrip("。")
        raise ParseError(
            f"{detail}；抖音有访问风控，可在「设置 → Cookie 来源」选择本机浏览器"
            "（先在浏览器打开一次 douyin.com），或指定导出的 cookies.txt 后重试。"
        )
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]
    data = ytdlp.item_from_info(info, "douyin")
    data["extra"].update({"aweme_id": video_id, "use_ytdlp": True})
    data["qualities"] = QUALITY_PRESETS["douyin"]
    if not data["video_id"]:
        data["video_id"] = video_id
    return VideoItem(**data)
