"""One-off setup script -- NOT part of the pipeline. Exchanges a TikTok Login Kit
authorization code (from the sandbox OAuth flow) for an access_token + refresh_token via
TikTok's token endpoint, and writes both directly into a niche creds file -- never printed
to the terminal, so there's nothing to manually copy or redact before showing Claude.

Run this yourself -- client_secret is read from an env var so it's never typed to or seen
by anything else:

    export TIKTOK_CLIENT_KEY="<from the app dashboard's Client key field>"
    export TIKTOK_CLIENT_SECRET="<from the app dashboard's Client secret field>"
    python scripts/exchange_tiktok_code.py "<code from the bizyr.co?code=... redirect>" \\
      "/path/to/the-network-<NICHE>-creds.txt"

If the creds file doesn't exist yet, it's created with just the two TikTok lines. If it
already has tiktok_access_token/tiktok_refresh_token lines, they're replaced in place;
otherwise a new TIKTOK section is appended.

TikTok access tokens are short-lived and refresh tokens rotate on every use (per the
plan) -- this script is for one-time verification, not the production credential-refresh
path.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REDIRECT_URI = "https://bizyr.co/"


def _write_tokens_into_creds_file(creds_path: Path, access_token: str, refresh_token: str) -> None:
    access_line = f"tiktok_access_token = {access_token}\n"
    refresh_line = f"tiktok_refresh_token = {refresh_token}\n"

    if not creds_path.exists():
        creds_path.write_text(f"TIKTOK\n{access_line}{refresh_line}\n")
        return

    text = creds_path.read_text()
    if re.search(r"^tiktok_access_token\s*=", text, flags=re.MULTILINE):
        text = re.sub(r"^tiktok_access_token\s*=.*$", access_line.rstrip("\n"), text, flags=re.MULTILINE)
        text = re.sub(r"^tiktok_refresh_token\s*=.*$", refresh_line.rstrip("\n"), text, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + f"\n\nTIKTOK\n{access_line}{refresh_line}"
    creds_path.write_text(text)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python scripts/exchange_tiktok_code.py <code> <path-to-creds.txt>", file=sys.stderr)
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
    creds_path = Path(sys.argv[2])

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
    payload = response.json()

    if "access_token" not in payload or "refresh_token" not in payload:
        print(f"token exchange failed -- response did not contain both tokens: {payload}", file=sys.stderr)
        sys.exit(1)

    _write_tokens_into_creds_file(creds_path, payload["access_token"], payload["refresh_token"])
    print(f"wrote tiktok_access_token and tiktok_refresh_token into {creds_path}")
