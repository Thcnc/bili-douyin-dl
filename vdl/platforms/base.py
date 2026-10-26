"""Shared data structures for platform parsers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class VideoItem:
    platform: str
    video_id: str
    title: str
    author: str = ""
    cover: str = ""
    duration: int = 0
    page_url: str = ""
    page: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)
    qualities: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ParseError(Exception):
    """Raised when a link cannot be understood or a platform API rejects it."""


QUALITY_PRESETS = {
    "bilibili": [
        {"id": "best", "label": "最高画质"},
        {"id": "1080p", "label": "1080P"},
        {"id": "720p", "label": "720P"},
        {"id": "480p", "label": "480P"},
        {"id": "360p", "label": "360P"},
        {"id": "audio", "label": "仅音频 (m4a)"},
    ],
    "douyin": [{"id": "best", "label": "原画 (无水印)"}],
}
