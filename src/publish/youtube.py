"""YouTube Data API v3 publishing: private video upload only (ffmpeg video, never the
carousel -- YouTube's native 2026 image-carousel feature has zero public API, confirmed
via research, so it's out of reach for this pipeline regardless).

No hosting-hop needed here, unlike Instagram/TikTok -- videos.insert takes direct file
bytes via resumable upload, not a public URL. Uses Google's official client library
(googleapiclient) rather than hand-rolling the resumable-upload chunking protocol, since
it already implements the documented retry/backoff behavior correctly.

Uploads always land as privacyStatus=private -- sits in Studio for the user to review and
publish manually, never goes live automatically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

UPLOAD_CHUNK_SIZE_BYTES = 5 * 1024 * 1024  # 5MB, matches Google's documented example
MAX_RETRIES = 5
RETRY_BASE_DELAY_S = 1.0
RETRIABLE_STATUS_CODES = {500, 502, 503, 504}


class YouTubeUploadError(Exception):
    pass


@dataclass(frozen=True)
class YouTubeCredentials:
    refresh_token: str
    client_id: str
    client_secret: str
    token_uri: str = "https://oauth2.googleapis.com/token"


def build_youtube_client(creds: YouTubeCredentials) -> Resource:
    credentials = Credentials(
        token=None,
        refresh_token=creds.refresh_token,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        token_uri=creds.token_uri,
    )
    return build("youtube", "v3", credentials=credentials)


class ResumableUploadRequest(Protocol):
    """Just the slice of googleapiclient's HttpRequest interface this module relies on --
    lets tests inject a fake without needing the real Google client machinery.
    """

    def next_chunk(self) -> tuple[Any, dict | None]: ...


def _run_resumable_upload(
    request: ResumableUploadRequest,
    max_retries: int = MAX_RETRIES,
    base_delay_s: float = RETRY_BASE_DELAY_S,
) -> dict:
    """Drive a resumable upload's chunk loop to completion, retrying retriable server
    errors with exponential backoff. Isolated from build_youtube_client so the retry logic
    itself is unit-testable without the real Google API client.
    """
    response = None
    retries = 0
    while response is None:
        try:
            _status, response = request.next_chunk()
        except HttpError as e:
            status_code = getattr(e.resp, "status", None)
            if status_code in RETRIABLE_STATUS_CODES and retries < max_retries:
                time.sleep(base_delay_s * (2**retries))
                retries += 1
                continue
            raise YouTubeUploadError(f"upload failed: {e}") from e
    return response


def upload_private_video(
    youtube_client: Resource,
    video_path: Path,
    title: str,
    description: str,
) -> str:
    """Upload a video as private. Returns the resulting video id."""
    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": "private"},
    }
    media = MediaFileUpload(str(video_path), chunksize=UPLOAD_CHUNK_SIZE_BYTES, resumable=True)
    request = youtube_client.videos().insert(part="snippet,status", body=body, media_body=media)

    response = _run_resumable_upload(request)
    return response["id"]
