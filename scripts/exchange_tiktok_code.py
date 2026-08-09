"""One-off setup script -- NOT part of the pipeline. Exchanges a TikTok Login Kit
authorization code (from the sandbox OAuth flow, target user @aidentrimz) for an
access_token + refresh_token via TikTok's token endpoint.

Run this yourself -- client_secret is read from an env var so it's never typed to or seen
by anything else:

    export TIKTOK_CLIENT_KEY="<from the app dashboard's Client key field>"
    export TIKTOK_CLIENT_SECRET="<from the app dashboard's Client secret field>"
    python scripts/exchange_tiktok_code.py "<code from the bizyr.co?code=... redirect>"

TikTok access tokens are short-lived and refresh tokens rotate on every use (per the
plan) -- this script is for one-time verification, not the production credential-refresh
path.
"""

from __future__ import annotations

import os
import sys

import requests

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = "https://bizyr.co/"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/exchange_tiktok_code.py <code>", file=sys.stderr)
        sys.exit(1)

    client_key = os.environ.get("TIKTOK_CLIENT_KEY")
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET")
    if not client_key or not client_secret:
        print(
            "set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET in your shell first",
            file=sys.stderr,
        )
        sys.exit(1)

    code = sys.argv[1]
    response = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
    )
    print(response.json())
