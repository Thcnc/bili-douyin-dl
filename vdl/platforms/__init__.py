"""Platform registry and link detection."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from . import bilibili, douyin
from .base import ParseError, VideoItem

PARSERS = {"bilibili": bilibili, "douyin": douyin}
_LINK_RE = re.compile(r"https?://[^\s，。、；<>\"']+")


def detect(url: str) -> str:
    for name, module in PARSERS.items():
        if module.matches(url):
            return name
    raise ParseError("暂不支持该链接（目前支持 B站、抖音）")


def parse_many(text: str, cookies: Dict[str, str] | None = None) -> Tuple[List[VideoItem], List[dict]]:
    """Parse every link found in ``text`` and return (items, errors)."""
    cookies = cookies or {}
    urls = _LINK_RE.findall(text or "")
    if not urls:
        raise ParseError("请粘贴 B站 或抖音的视频链接")

    items: List[VideoItem] = []
    errors: List[dict] = []
    seen: set[str] = set()
    for raw in urls:
        url = raw.rstrip(".,;)]}")
        if url in seen:
            continue
        seen.add(url)
        try:
            platform = detect(url)
            parsed = PARSERS[platform].parse(url, cookies.get(platform, ""))
            items.extend(parsed)
        except ParseError as exc:
            errors.append({"url": url, "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            errors.append({"url": url, "message": f"解析异常：{exc}"})
    return items, errors
