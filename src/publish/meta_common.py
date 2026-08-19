"""Shared Graph API session/token helpers for Instagram and Facebook publishing.

Both platforms use the same underlying Meta Graph API and the same container-then-publish
pattern for photos/carousels, so this module holds what's common: the HTTP wrapper,
container creation/polling, and error handling. instagram.py and facebook.py build on top.

Key gap the requirements didn't cover (per plan): Graph API's Content Publishing endpoints
fetch media by URL, they don't accept direct file upload -- callers of this module must
already have a public URL for their rendered image/video (the "hosting-hop", handled in the
orchestrator, not here).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

GRAPH_API_VERSION = "v21.0"  # pinned explicitly -- bump deliberately, don't let this drift silently
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
# Facebook Login and Instagram Login are separate Meta identity systems that don't share
# data (confirmed via Meta's own docs) -- a token minted via Instagram Login only works
# against graph.instagram.com, never graph.facebook.com, and vice versa. Facebook posting
# (Page token) uses GRAPH_API_BASE; Instagram posting (Instagram Login token) uses this.
GRAPH_INSTAGRAM_API_BASE = f"https://graph.instagram.com/{GRAPH_API_VERSION}"

CONTAINER_POLL_INTERVAL_S = 3
CONTAINER_POLL_TIMEOUT_S = 120


class GraphAPIError(Exception):
    """Wraps a Graph API error response ({"error": {...}}) with the useful fields pulled out."""

    def __init__(
        self,
        message: str,
        code: Optional[int] = None,
        error_type: Optional[str] = None,
        raw: Optional[dict] = None,
    ):
        super().__init__(message)
        self.code = code
        self.error_type = error_type
        self.raw = raw


class ContainerTimeoutError(Exception):
    """Raised when a media container never reaches FINISHED status within the timeout."""


@dataclass(frozen=True)
class MetaCredentials:
    access_token: str
    ig_business_account_id: Optional[str] = None
    page_id: Optional[str] = None


def _raise_for_graph_error(response: requests.Response) -> None:
    if response.ok:
        return
    try:
        payload = response.json()
    except ValueError:
        response.raise_for_status()
        return
    error = payload.get("error", {})
    raise GraphAPIError(
        error.get("message", f"Graph API request failed with status {response.status_code}"),
        code=error.get("code"),
        error_type=error.get("type"),
        raw=payload,
    )


def graph_post(
    path: str, access_token: str, extra_params: Optional[dict] = None, api_base: str = GRAPH_API_BASE, **params
) -> dict:
    """extra_params exists alongside **params for keys that aren't valid Python identifiers
    (e.g. Facebook's `attached_media[0]` array-style form field names).
    """
    body = {**params, **(extra_params or {}), "access_token": access_token}
    response = requests.post(f"{api_base}/{path}", data=body)
    _raise_for_graph_error(response)
    return response.json()


def graph_get(path: str, access_token: str, api_base: str = GRAPH_API_BASE, **params) -> dict:
    response = requests.get(f"{api_base}/{path}", params={**params, "access_token": access_token})
    _raise_for_graph_error(response)
    return response.json()


def graph_delete(path: str, access_token: str, api_base: str = GRAPH_API_BASE, **params) -> dict:
    response = requests.delete(f"{api_base}/{path}", params={**params, "access_token": access_token})
    _raise_for_graph_error(response)
    return response.json()


def wait_for_container_ready(
    container_id: str,
    access_token: str,
    poll_interval_s: float = CONTAINER_POLL_INTERVAL_S,
    timeout_s: float = CONTAINER_POLL_TIMEOUT_S,
    api_base: str = GRAPH_API_BASE,
) -> None:
    """Poll a media container's status_code until it's FINISHED (ready to publish) or ERROR.
    Video containers especially can take a while to process -- this must not fire
    media_publish immediately after container creation.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = graph_get(container_id, access_token, fields="status_code", api_base=api_base)
        status = result.get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise GraphAPIError(f"container {container_id} failed processing: {result}")
        time.sleep(poll_interval_s)
    raise ContainerTimeoutError(f"container {container_id} did not finish within {timeout_s}s")
