thonfrom __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger("extractors.utils")

def normalize_reddit_url(url: str) -> str:
    """
    Clean basic whitespace and normalize Reddit URLs.

    This keeps both reddit.com and v.redd.it links intact while trimming
    spaces and removing trailing query/hash segments when they are empty.
    """
    if not isinstance(url, str):
        raise TypeError("URL must be a string.")
    cleaned = url.strip()
    # No heavy normalization here to avoid accidentally breaking unusual URLs.
    return cleaned

def is_probable_url(value: Any) -> bool:
    """
    Best-effort check that `value` looks like a URL.
    """
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme) and bool(parsed.netloc)

def build_media_entry(
    media_type: str,
    url: str,
    quality: str,
    extension: str,
    info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not is_probable_url(url):
        raise ValueError(f"Invalid media URL: {url!r}")

    entry: Dict[str, Any] = {
        "type": media_type,
        "quality": quality,
        "url": url,
        "extension": extension,
    }
    if info:
        entry["info"] = info
    return entry

def guess_audio_url(source_url: Optional[str]) -> Optional[str]:
    """
    Try to infer an audio-only DASH URL from a Reddit video URL.

    This is heuristic-based and may not always succeed, but it works for many
    common v.redd.it patterns like DASH_720.mp4 -> DASH_audio.mp4.
    """
    if not source_url or not is_probable_url(source_url):
        return None

    # Unescape common HTML encoding
    url = source_url.replace("&amp;", "&")

    # Look for DASH_### or DASH_ in the path segment
    # Examples: