"""Instagram Graph API publishing: carousel (images, no audio -- hard platform limit,
confirmed via research, not assumption) and Reels (ffmpeg video with audio already baked
into the file). Both auto-publish directly, no manual/draft step, per the plan.

Media must be fetched by URL by Meta's servers -- this module takes already-hosted URLs as
input; getting local render output onto a public URL is the orchestrator's job, not this
module's (see meta_common's docstring on the hosting-hop).
"""

from __future__ import annotations

from src.publish.meta_common import graph_post, wait_for_container_ready

MAX_CAROUSEL_IMAGES = 10
MIN_CAROUSEL_IMAGES = 2
VIDEO_CONTAINER_TIMEOUT_S = 300  # video processing is slower than images, give it more room


def publish_carousel(ig_business_account_id: str, image_urls: list[str], caption: str, access_token: str) -> str:
    """Create and publish an Instagram carousel post. Returns the published media id."""
    if not (MIN_CAROUSEL_IMAGES <= len(image_urls) <= MAX_CAROUSEL_IMAGES):
        raise ValueError(
            f"carousel needs {MIN_CAROUSEL_IMAGES}-{MAX_CAROUSEL_IMAGES} images, got {len(image_urls)}"
        )

    child_ids = []
    for url in image_urls:
        result = graph_post(
            f"{ig_business_account_id}/media",
            access_token,
            image_url=url,
            is_carousel_item="true",
        )
        child_ids.append(result["id"])

    container = graph_post(
        f"{ig_business_account_id}/media",
        access_token,
        media_type="CAROUSEL",
        caption=caption,
        children=",".join(child_ids),
    )
    container_id = container["id"]
    wait_for_container_ready(container_id, access_token)

    published = graph_post(f"{ig_business_account_id}/media_publish", access_token, creation_id=container_id)
    return published["id"]


def publish_reel(ig_business_account_id: str, video_url: str, caption: str, access_token: str) -> str:
    """Create and publish an Instagram Reel. Audio must already be baked into the video
    file at video_url -- there's no API field for attaching a soundtrack the way the native
    composer's music picker works (confirmed: Instagram's audio library isn't exposed via
    API at all). Returns the published media id.
    """
    container = graph_post(
        f"{ig_business_account_id}/media",
        access_token,
        media_type="REELS",
        video_url=video_url,
        caption=caption,
    )
    container_id = container["id"]
    wait_for_container_ready(container_id, access_token, timeout_s=VIDEO_CONTAINER_TIMEOUT_S)

    published = graph_post(f"{ig_business_account_id}/media_publish", access_token, creation_id=container_id)
    return published["id"]
