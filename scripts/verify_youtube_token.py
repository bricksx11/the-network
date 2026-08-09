"""One-off verification script -- NOT part of the pipeline. Confirms a minted YouTube
refresh token actually works and resolves to the expected channel, by making a real,
lightweight API call (channels.list mine=true) -- no video upload involved.

Run this yourself -- values are read from env vars so nothing is typed to or seen by
anything else:

    export YOUTUBE_REFRESH_TOKEN="<from the creds file>"
    export YOUTUBE_CLIENT_ID="<from the creds file>"
    export YOUTUBE_CLIENT_SECRET="<from the creds file>"
    python scripts/verify_youtube_token.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.publish.youtube import YouTubeCredentials, build_youtube_client

if __name__ == "__main__":
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    if not all([refresh_token, client_id, client_secret]):
        print(
            "set YOUTUBE_REFRESH_TOKEN, YOUTUBE_CLIENT_ID, and YOUTUBE_CLIENT_SECRET in your shell first",
            file=sys.stderr,
        )
        sys.exit(1)

    client = build_youtube_client(
        YouTubeCredentials(refresh_token=refresh_token, client_id=client_id, client_secret=client_secret)
    )
    response = client.channels().list(part="snippet", mine=True).execute()

    items = response.get("items", [])
    if not items:
        print("token is valid but no channel found for this account", file=sys.stderr)
        sys.exit(1)

    channel = items[0]
    print(f"channel_id: {channel['id']}")
    print(f"channel_title: {channel['snippet']['title']}")
