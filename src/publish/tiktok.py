"""TikTok Content Posting API: photo/carousel posts uploaded to the creator's native
drafts/inbox (never Direct Post), matching the plan's TikTok behavior.

Verified against TikTok's own docs before writing this (not assumed): photo/carousel posts
only support source_info.source == "PULL_FROM_URL" -- FILE_UPLOAD (chunked binary upload)
is video-only. This corrects the plan's original assumption that FILE_UPLOAD would sidestep
hosting for TikTok too; it doesn't, for photo posts specifically. Images need the same
public-URL hosting-hop as Instagram, PLUS TikTok requires the hosting domain to be verified
in the app dashboard before PULL_FROM_URL will accept URLs on it -- that verification is a
one-time manual dashboard step, not something this module can do.

post_mode=MEDIA_UPLOAD (not DIRECT_POST) is what lands content in the creator's drafts/inbox
instead of publishing it -- this is the whole reason TikTok doesn't need App Review for this
use case.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

API_BASE = "https://open.tiktokapis.com/v2"
MAX_CAROUSEL_IMAGES = 35  # TikTok's documented photo-post limit; verify if it changes
MIN_CAROUSEL_IMAGES = 1

STATUS_POLL_INTERVAL_S = 3
STATUS_POLL_TIMEOUT_S = 120

# Confirmed from docs: publish_id and an error object (code/message/log_id) on init.
# Status-check terminal-success value confirmed against a real sandbox call (not assumed):
# for post_mode=MEDIA_UPLOAD (drafts/inbox -- what this module always uses), the real
# terminal status is SEND_TO_USER_INBOX, not PUBLISH_COMPLETE -- that name is presumably
# specific to DIRECT_POST, which this module never uses. Keeping PUBLISH_COMPLETE
# recognized too costs nothing and guards against it appearing in some other path.
STATUS_COMPLETE_VALUES = ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE")


class TikTokAPIError(Exception):
    def __init__(self, message: str, code: Optional[str] = None, log_id: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.log_id = log_id


class TikTokStatusTimeoutError(Exception):
    """Raised when a publish_id never reaches a terminal status within the timeout."""


@dataclass(frozen=True)
class TikTokCredentials:
    access_token: str


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def _raise_for_tiktok_error(payload: dict) -> None:
    error = payload.get("error", {})
    code = error.get("code")
    if code and code != "ok":
        raise TikTokAPIError(error.get("message", f"TikTok API error: {code}"), code=code, log_id=error.get("log_id"))


def upload_carousel_to_drafts(
    image_urls: list[str],
    title: str,
    description: str,
    access_token: str,
) -> str:
    """Initiate a photo/carousel post to the creator's TikTok drafts/inbox (post_mode=
    MEDIA_UPLOAD). Returns the publish_id. Image URLs must be hosted on a domain already
    verified with this TikTok app -- PULL_FROM_URL rejects unverified domains.
    """
    if not (MIN_CAROUSEL_IMAGES <= len(image_urls) <= MAX_CAROUSEL_IMAGES):
        raise ValueError(
            f"carousel needs {MIN_CAROUSEL_IMAGES}-{MAX_CAROUSEL_IMAGES} images, got {len(image_urls)}"
        )

    body = {
        "media_type": "PHOTO",
        "post_mode": "MEDIA_UPLOAD",
        "post_info": {
            "title": title,
            "description": description,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_cover_index": 0,
            "photo_images": image_urls,
        },
    }

    response = requests.post(f"{API_BASE}/post/publish/content/init/", headers=_headers(access_token), json=body)
    payload = response.json()
    _raise_for_tiktok_error(payload)
    return payload["data"]["publish_id"]


def check_publish_status(publish_id: str, access_token: str) -> dict:
    response = requests.post(
        f"{API_BASE}/post/publish/status/fetch/",
        headers=_headers(access_token),
        json={"publish_id": publish_id},
    )
    payload = response.json()
    _raise_for_tiktok_error(payload)
    return payload["data"]


def wait_for_publish_complete(
    publish_id: str,
    access_token: str,
    poll_interval_s: float = STATUS_POLL_INTERVAL_S,
    timeout_s: float = STATUS_POLL_TIMEOUT_S,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        data = check_publish_status(publish_id, access_token)
        status = data.get("status", "")
        if status in STATUS_COMPLETE_VALUES:
            return
        if "FAIL" in status.upper():
            raise TikTokAPIError(f"publish {publish_id} failed with status {status!r}: {data}")
        time.sleep(poll_interval_s)
    raise TikTokStatusTimeoutError(f"publish {publish_id} did not complete within {timeout_s}s")
