thonfrom __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from .utils_media import (
    build_media_entry,
    guess_audio_url,
    is_probable_url,
    normalize_reddit_url,
)

logger = logging.getLogger("extractors.reddit")

class RedditMediaExtractor:
    """
    Extracts media metadata from Reddit post URLs.

    The extractor focuses on v.redd.it posts but also handles standard images,
    GIFs, and gallery posts when possible.
    """

    def __init__(self, user_agent: str, timeout: float = 10.0) -> None:
        self.user_agent = user_agent
        self.timeout = timeout

    # --------------------------------------------------------------------- #
    # Public API                                                            #
    # --------------------------------------------------------------------- #
    def process_batch(self, urls: List[str]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for url in urls:
            try:
                results.append(self.extract(url))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error while extracting %s: %s", url, exc)
                results.append(
                    {
                        "url": url,
                        "result": {
                            "error": True,
                            "error_message": f"Unexpected error: {exc}",
                            "time_end": 0,
                            "type": "error",
                        },
                    }
                )
        return results

    def extract(self, url: str) -> Dict[str, Any]:
        start_time = time.perf_counter()
        norm_url = normalize_reddit_url(url)
        logger.debug("Normalized URL %s -> %s", url, norm_url)

        try:
            post_data = self._fetch_post_data(norm_url)
            media_payload = self._parse_post_data(post_data, original_url=norm_url)
            error = False
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to extract media from %s: %s", norm_url, exc)
            media_payload = {
                "error": True,
                "error_message": str(exc),
                "type": "error",
                "url": None,
                "source": "reddit",
                "title": None,
                "thumbnail": None,
                "medias": [],
            }
            error = True

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        media_payload["time_end"] = elapsed_ms
        media_payload["error"] = error

        return {
            "url": norm_url,
            "result": media_payload,
        }

    # --------------------------------------------------------------------- #
    # Internal helpers                                                      #
    # --------------------------------------------------------------------- #
    def _fetch_post_data(self, url: str) -> Dict[str, Any]:
        """
        Fetch the Reddit post JSON and return the post's data dictionary.
        """
        json_url = self._build_json_url(url)
        logger.debug("Fetching Reddit JSON from %s", json_url)

        headers = {"User-Agent": self.user_agent}
        resp = requests.get(json_url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()

        if not isinstance(payload, list) or not payload:
            raise ValueError("Unexpected JSON structure from Reddit API.")

        listing = payload[0]
        if "data" not in listing or "children" not in listing["data"]:
            raise ValueError("Malformed listing data from Reddit API.")

        children = listing["data"]["children"]
        if not children:
            raise ValueError("No post data found for the given URL.")

        post = children[0].get("data") or {}
        if not isinstance(post, dict):
            raise ValueError("Post data must be an object.")
        return post

    @staticmethod
    def _build_json_url(url: str) -> str:
        if url.endswith(".json"):
            return url
        if url.endswith("/"):
            return f"{url}.json"
        return f"{url}/.json"

    def _parse_post_data(self, post: Dict[str, Any], original_url: str) -> Dict[str, Any]:
        """
        Convert Reddit post JSON into our media structure.
        """
        title = post.get("title")
        permalink = post.get("permalink") or ""
        post_url = f"https://www.reddit.com{permalink}" if permalink else original_url

        raw_thumbnail = post.get("thumbnail")
        thumbnail = raw_thumbnail if is_probable_url(raw_thumbnail) else None

        medias: List[Dict[str, Any]] = []

        # Prefer explicit Reddit video when available
        if post.get("is_video"):
            logger.debug("Post %s detected as Reddit video.", post_url)
            video_medias = self._parse_reddit_video(post)
            medias.extend(video_medias)

        # Gallery posts (multiple images)
        if post.get("is_gallery"):
            logger.debug("Post %s detected as gallery.", post_url)
            gallery_medias = self._parse_gallery(post)
            medias.extend(gallery_medias)

        # Fallbacks: plain image or GIF from preview/url
        if not medias:
            simple_medias = self._parse_simple_media(post)
            medias.extend(simple_medias)

        media_type = "multiple" if len(medias) > 1 else "single"
        if not medias:
            media_type = "none"

        return {
            "url": post_url,
            "source": "reddit",
            "title": title,
            "thumbnail": thumbnail,
            "medias": medias,
            "type": media_type,
            "error": False,  # may be overridden by caller
        }

    # ------------------------------------------------------------------ #
    # Parsing strategies                                                 #
    # ------------------------------------------------------------------ #
    def _parse_reddit_video(self, post: Dict[str, Any]) -> List[Dict[str, Any]]:
        medias: List[Dict[str, Any]] = []

        secure_media = post.get("secure_media") or post.get("media") or {}
        reddit_video = secure_media.get("reddit_video") or {}

        fallback_url = reddit_video.get("fallback_url")
        dash_url = reddit_video.get("dash_url")
        height = reddit_video.get("height")
        width = reddit_video.get("width")
        bitrate_kbps = reddit_video.get("bitrate_kbps")

        if not fallback_url:
            logger.debug("Reddit video has no fallback_url; skipping video extraction.")
            return medias

        quality_label = f"{height}p" if height else "unknown"
        video_info: Dict[str, Any] = {
            "height": height,
            "width": width,
            "bitrate_kbps": bitrate_kbps,
            "dash_url": dash_url,
        }

        medias.append(
            build_media_entry(
                media_type="video",
                url=fallback_url,
                quality=quality_label,
                extension="mp4",
                info=video_info,
            )
        )

        # Try to infer audio URL from DASH manifest
        audio_url = guess_audio_url(dash_url or fallback_url)
        if audio_url:
            medias.append(
                build_media_entry(
                    media_type="audio",
                    url=audio_url,
                    quality="audio",
                    extension="mp3",
                    info={"source": "inferred_from_dash"},
                )
            )
        else:
            logger.debug("Could not infer separate audio URL for video %s", fallback_url)

        return medias

    def _parse_gallery(self, post: Dict[str, Any]) -> List[Dict[str, Any]]:
        medias: List[Dict[str, Any]] = []
        gallery_data = post.get("gallery_data")
        media_metadata = post.get("media_metadata") or {}

        if not isinstance(gallery_data, dict):
            return medias

        items = gallery_data.get("items") or []
        for item in items:
            if not isinstance(item, dict):
                continue
            media_id = item.get("media_id")
            if not media_id or media_id not in media_metadata:
                continue

            meta = media_metadata.get(media_id) or {}
            status = meta.get("status")
            if status != "valid":
                continue

            media_type = meta.get("e")  # "Image" or "AnimatedImage"
            source = (meta.get("s") or {}).get("u") or (meta.get("s") or {}).get("mp4")
            if not source or not is_probable_url(source):
                continue

            if media_type == "AnimatedImage":
                mtype = "video" if source.endswith(".mp4") else "image"
            else:
                mtype = "image"

            medias.append(
                build_media_entry(
                    media_type=mtype,
                    url=source,
                    quality="original",
                    extension=self._infer_extension_from_url(source),
                    info={"gallery": True},
                )
            )

        return medias

    def _parse_simple_media(self, post: Dict[str, Any]) -> List[Dict[str, Any]]:
        medias: List[Dict[str, Any]] = []

        post_hint = post.get("post_hint")
        url_overridden = post.get("url_overridden_by_dest") or post.get("url")

        # GIF via preview variants
        preview = post.get("preview") or {}
        images = preview.get("images") or []

        if images and isinstance(images, list):
            first = images[0] or {}
            variants = first.get("variants") or {}
            gif_variant = variants.get("gif") or variants.get("mp4")
            if isinstance(gif_variant, dict):
                source = (gif_variant.get("source") or {}).get("url")
                if is_probable_url(source):
                    medias.append(
                        build_media_entry(
                            media_type="video",
                            url=source,
                            quality="original",
                            extension=self._infer_extension_from_url(source),
                            info={"variant": "gif"},
                        )
                    )

        # Simple image or direct media link
        if url_overridden and is_probable_url(url_overridden):
            extension = self._infer_extension_from_url(url_overridden)
            if extension:
                media_type = "image"
                if extension in {"mp4", "webm"}:
                    media_type = "video"
                medias.append(
                    build_media_entry(
                        media_type=media_type,
                        url=url_overridden,
                        quality="original",
                        extension=extension,
                        info={"post_hint": post_hint},
                    )
                )

        return medias

    # ------------------------------------------------------------------ #
    # Utility                                                            #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _infer_extension_from_url(url: str) -> str:
        if "?" in url:
            url = url.split("?", 1)[0]
        if "#" in url:
            url = url.split("#", 1)[0]
        lowered = url.lower()
        for ext in ("mp4", "webm", "gif", "jpg", "jpeg", "png"):
            if lowered.endswith(f".{ext}"):
                return ext if ext != "jpeg" else "jpg"
        return ""