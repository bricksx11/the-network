"""Facebook Page publishing: carousel only (never the ffmpeg video, per plan), no audio
consideration (not native to Facebook feed posts). Auto-published directly, no manual step.

Multi-photo post flow: upload each image unpublished to /{page-id}/photos, collect the
resulting photo ids, then reference them via attached_media on /{page-id}/feed.
"""

from __future__ import annotations

import json

from src.publish.meta_common import graph_post

MIN_CAROUSEL_IMAGES = 2
MAX_CAROUSEL_IMAGES = 10


def publish_carousel(page_id: str, image_urls: list[str], message: str, access_token: str) -> str:
    """Create and publish a Facebook Page multi-photo post. Returns the published post id."""
    if not (MIN_CAROUSEL_IMAGES <= len(image_urls) <= MAX_CAROUSEL_IMAGES):
        raise ValueError(
            f"carousel needs {MIN_CAROUSEL_IMAGES}-{MAX_CAROUSEL_IMAGES} images, got {len(image_urls)}"
        )

    photo_ids = []
    for url in image_urls:
        result = graph_post(f"{page_id}/photos", access_token, url=url, published="false")
        photo_ids.append(result["id"])

    attached_media = {
        f"attached_media[{i}]": json.dumps({"media_fbid": photo_id})
        for i, photo_id in enumerate(photo_ids)
    }

    published = graph_post(f"{page_id}/feed", access_token, message=message, extra_params=attached_media)
    return published["id"]
