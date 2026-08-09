"""One-off verification script -- NOT part of the pipeline. Confirms a token generated via
the Meta app dashboard's "Generate token" button (Instagram API > API setup with Instagram
login) actually resolves the Instagram account, by hitting the same graph.instagram.com
endpoint the real publish code uses.

Run this yourself -- it reads the token from an env var so it's never typed to or seen by
anything else:

    export IG_ACCESS_TOKEN="<paste from the dashboard's Generate token button>"
    python scripts/verify_ig_token.py
"""

from __future__ import annotations

import os
import sys

import requests

GRAPH_INSTAGRAM_BASE = "https://graph.instagram.com/v21.0"

if __name__ == "__main__":
    token = os.environ.get("IG_ACCESS_TOKEN")
    if not token:
        print("set IG_ACCESS_TOKEN in your shell first: export IG_ACCESS_TOKEN=...", file=sys.stderr)
        sys.exit(1)

    response = requests.get(
        f"{GRAPH_INSTAGRAM_BASE}/me",
        params={"fields": "user_id,username", "access_token": token},
    )
    print(response.json())
