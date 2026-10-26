"""Bilibili link parsing.

Uses the public web API for metadata (fast, no signature needed) and hands the
actual download to yt-dlp, which already understands DASH streams, multi-part
videos and cookie based quality upgrades.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from ..utils import DESKTOP_UA, http_request
from .base import QUALITY_PRESETS, ParseError, VideoItem

API_VIEW = "https://api.bilibili.com/x/web-interface/view"

HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn", "bilibili.tv")
BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)
SHORT_HOSTS = ("b23.tv", "bili2233.cn")


def matches(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def _headers(cookie: str = "") -> dict:
    headers = {
        "User-Agent": DESKTOP_UA,
        "Referer": "https://www.bilibili.com/",
        "Origin": "https://www.bilibili.com",
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


def resolve(url: str, cookie: str = "") -> str:
    """Expand b23.tv style short links into the canonical bilibili URL."""
    host = (urlparse(url).hostname or "").lower()
    if host in SHORT_HOSTS or host.endswith("." + SHORT_HOSTS[0]):
        try:
            resp = http_request(url, headers=_headers(cookie), read_body=False)
            return resp.url
        except Exception as exc:  # noqa: BLE001
            raise ParseError(f"短链展开失败：{exc}") from exc
    return url


def _video_id(url: str, cookie: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    match = BV_RE.search(parsed.path) or BV_RE.search(parsed.query)
    if match:
        return match.group(1)
    av = AV_RE.search(parsed.path)
    if av:
        return "av" + av.group(1)
    if "aid" in query:
        return "av" + query["aid"][0]
    if "bvid" in query:
        return query["bvid"][0]
    raise ParseError("未在链接中找到 BV 号 / av 号")


def parse(url: str, cookie: str = "") -> list[VideoItem]:
    url = resolve(url, cookie)
    video_id = _video_id(url, cookie)
    param = "aid" if video_id.startswith("av") else "bvid"
    api = f"{API_VIEW}?{param}={video_id[2:] if param == 'aid' else video_id}"
    try:
        resp = http_request(api, headers=_headers(cookie))
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"B站接口请求失败：{exc}") from exc

    if payload.get("code") != 0:
        raise ParseError(f"B站接口返回错误：{payload.get('message') or payload.get('code')}")

    data = payload["data"]
    title = data.get("title") or "未命名视频"
    cover = data.get("pic") or ""
    if cover.startswith("//"):
        cover = "https:" + cover
    author = (data.get("owner") or {}).get("name", "")
    duration = int(data.get("duration") or 0)
    pages = data.get("pages") or []

    if len(pages) <= 1:
        return [
            VideoItem(
                platform="bilibili",
                video_id=data.get("bvid") or video_id,
                title=title,
                author=author,
                cover=cover,
                duration=duration,
                page_url=f"https://www.bilibili.com/video/{data.get('bvid') or video_id}",
                extra={"aid": data.get("aid"), "cid": (pages[0]["cid"] if pages else data.get("cid"))},
                qualities=QUALITY_PRESETS["bilibili"],
            )
        ]

    items: list[VideoItem] = []
    bvid = data.get("bvid") or video_id
    for page in pages:
        part = page.get("part") or f"P{page.get('page')}"
        items.append(
            VideoItem(
                platform="bilibili",
                video_id=f"{bvid}-p{page.get('page')}",
                title=f"{title} · P{page.get('page')} {part}",
                author=author,
                cover=cover,
                duration=int(page.get("duration") or 0),
                page_url=f"https://www.bilibili.com/video/{bvid}?p={page.get('page')}",
                page=int(page.get("page") or 0),
                extra={"aid": data.get("aid"), "cid": page.get("cid"), "bvid": bvid},
                qualities=QUALITY_PRESETS["bilibili"],
            )
        )
    return items
