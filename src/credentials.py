"""Loads a niche's platform credentials from a single JSON-blob environment variable
(NICHE_CREDS__<NICHE>), matching the plan's secret-naming convention -- one secret per
niche rather than one per token, so the secrets list doesn't grow linearly with
niches x platforms x token-types.

Expected shape:
{
  "meta_access_token": "...",           # Facebook Page token (graph.facebook.com) -- Facebook only
  "ig_access_token": "...",             # Instagram Login token (graph.instagram.com) -- Instagram only.
                                         # Separate from meta_access_token: Facebook Login and Instagram
                                         # Login are different Meta identity systems that don't share
                                         # tokens (confirmed via Meta's own docs).
  "tiktok_access_token": "...",
  "youtube": {
    "refresh_token": "...",
    "client_id": "...",
    "client_secret": "..."
  }
}

Any platform's key can be omitted if that platform isn't enabled for the niche -- callers
check for None and skip rather than erroring, since not every niche need be on every
platform from day one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from src.publish.youtube import YouTubeCredentials


class CredentialsError(Exception):
    pass


@dataclass(frozen=True)
class NicheCredentials:
    meta_access_token: Optional[str]
    ig_access_token: Optional[str]
    tiktok_access_token: Optional[str]
    youtube: Optional[YouTubeCredentials]


def load_niche_credentials(niche: str) -> NicheCredentials:
    env_var = f"NICHE_CREDS__{niche.upper()}"
    raw = os.environ.get(env_var)
    if raw is None:
        raise CredentialsError(f"{env_var} is not set -- no credentials available for niche {niche!r}")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CredentialsError(f"{env_var} is not valid JSON: {e}") from e

    youtube_data = data.get("youtube")
    youtube_creds = None
    if youtube_data:
        youtube_creds = YouTubeCredentials(
            refresh_token=youtube_data["refresh_token"],
            client_id=youtube_data["client_id"],
            client_secret=youtube_data["client_secret"],
        )

    return NicheCredentials(
        meta_access_token=data.get("meta_access_token"),
        ig_access_token=data.get("ig_access_token"),
        tiktok_access_token=data.get("tiktok_access_token"),
        youtube=youtube_creds,
    )
