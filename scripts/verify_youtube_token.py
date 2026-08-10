"""One-off verification script -- NOT part of the pipeline. Confirms a minted YouTube
refresh token is actually valid (not expired/revoked) by refreshing it for a real access
token -- not by calling a YouTube Data API method.

Deliberately does NOT call something like channels.list: that needs a broader scope
(youtube / youtube.readonly) than youtube.upload, which is all the pipeline actually
requests (confirmed via a real 403 insufficientPermissions error when this script first
tried channels.list -- a mismatch in this verification script, not a problem with the
token or the pipeline's actual videos.insert upload call, which youtube.upload does cover).
Refreshing the token is scope-agnostic and tests the one thing that actually matters here:
is this refresh_token/client_id/client_secret combo still valid.

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

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

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

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
    )
    credentials.refresh(Request())

    print("refresh succeeded -- token is valid")
    print(f"granted scopes: {credentials.scopes}")
    print(f"access token expires at: {credentials.expiry}")
