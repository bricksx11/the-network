"""One-off verification script -- NOT part of the pipeline. Confirms whether Instagram
Login (Business Login for Instagram) actually resolves a real IG account id, since the
classic Page.instagram_business_account field has stayed empty across every attempt despite
correct permissions, correct app, and a fresh disconnect/reconnect. These are two genuinely
separate Meta systems (Facebook Login vs Instagram Login) that don't share data -- this
checks the one we actually completed a successful OAuth flow against last night.

Run this yourself -- it reads your app's client secret from an env var so it never has to
be typed to or seen by anything else. Usage:

    export IG_APP_SECRET="<paste from Auto-posting app's dashboard>"
    python scripts/verify_instagram_login.py "<code from a fresh instagram.com/oauth/authorize redirect>"

Get a fresh code the same way as before: go to the app's Instagram API > API setup with
Instagram login > copy the Embed URL > open it, log in, approve, and copy the `code=`
value from the resulting (broken, that's fine) localhost redirect URL.
"""

from __future__ import annotations

import os
import sys

import requests

CLIENT_ID = "1029944766682722"  # Auto-posting app's Instagram App ID, not secret
REDIRECT_URI = "https://localhost/"
TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
GRAPH_INSTAGRAM_BASE = "https://graph.instagram.com/v21.0"


def exchange_code_for_token(code: str, client_secret: str) -> str:
    response = requests.post(
        TOKEN_EXCHANGE_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
    )
    payload = response.json()
    if "access_token" not in payload:
        raise RuntimeError(f"token exchange failed: {payload}")
    return payload["access_token"]


def get_ig_user_id(access_token: str) -> dict:
    response = requests.get(
        f"{GRAPH_INSTAGRAM_BASE}/me",
        params={"fields": "user_id,username", "access_token": access_token},
    )
    return response.json()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/verify_instagram_login.py <code>", file=sys.stderr)
        sys.exit(1)

    client_secret = os.environ.get("IG_APP_SECRET")
    if not client_secret:
        print("set IG_APP_SECRET in your shell first: export IG_APP_SECRET=...", file=sys.stderr)
        sys.exit(1)

    code = sys.argv[1]
    token = exchange_code_for_token(code, client_secret)
    result = get_ig_user_id(token)
    print(result)
