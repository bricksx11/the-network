"""One-off setup script -- NOT part of the pipeline. Runs the local OAuth consent flow once
to mint a YouTube refresh token for the pipeline's resumable-upload credentials.

This opens your browser, you log in as whichever Google account owns the target YouTube
channel (must be added as a Test user on the OAuth consent screen -- Audience tab), and
approve the youtube.upload scope. The refresh token is printed to YOUR terminal only; it is
never sent anywhere else. Copy it from there into your own NICHE_CREDS__<NICHE> secret
blob's youtube.refresh_token field (client_id/client_secret for that field come from the
same client_secret_*.json file this script reads).

Usage:
    .venv/bin/python scripts/mint_youtube_refresh_token.py "/path/to/client_secret_....json"
"""

from __future__ import annotations

import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/mint_youtube_refresh_token.py <path-to-client_secret.json>", file=sys.stderr)
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=SCOPES)
    credentials = flow.run_local_server(port=0)

    print("\nSuccess. Refresh token (copy this into your own NICHE_CREDS secret, do not share it):")
    print(credentials.refresh_token)
