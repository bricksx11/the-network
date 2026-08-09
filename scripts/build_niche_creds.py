"""One-off setup script -- NOT part of the pipeline. Reads the plain-text creds file you've
been filling in by hand and prints the exact JSON shape src/credentials.py expects for the
NICHE_CREDS__<NICHE> GitHub secret. Prints ONLY the JSON to stdout (no extra text) so it can
be piped straight into `gh secret set` -- the values never need to be retyped or pass
through chat.

Usage:
    .venv/bin/python scripts/build_niche_creds.py "/path/to/the-network-BARBER-creds.txt" \\
      | gh secret set NICHE_CREDS__BARBER --repo bricksx11/the-network

Expects lines shaped like `key = value` (extra indented continuation lines, like the
tiktok_refresh_token note, are ignored -- only the first line of each key is read).
"""

from __future__ import annotations

import json
import sys

REQUIRED_KEYS = {
    "ig_access_token",
    "meta_access_token",
    "tiktok_access_token",
    "youtube_refresh_token",
    "youtube_client_id",
    "youtube_client_secret",
}


def parse_creds_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in open(path, encoding="utf-8"):
        if line.startswith((" ", "\t")) or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        # strip inline `(Aiden Barber Page token)`-style annotations from the key itself
        key = key.split("(")[0].strip()
        value = rest.strip()
        if key in REQUIRED_KEYS and value:
            values[key] = value
    return values


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/build_niche_creds.py <path-to-creds.txt>", file=sys.stderr)
        sys.exit(1)

    values = parse_creds_file(sys.argv[1])
    missing = REQUIRED_KEYS - values.keys()
    if missing:
        print(f"missing/blank values for: {', '.join(sorted(missing))}", file=sys.stderr)
        sys.exit(1)

    blob = {
        "meta_access_token": values["meta_access_token"],
        "ig_access_token": values["ig_access_token"],
        "tiktok_access_token": values["tiktok_access_token"],
        "youtube": {
            "refresh_token": values["youtube_refresh_token"],
            "client_id": values["youtube_client_id"],
            "client_secret": values["youtube_client_secret"],
        },
    }
    print(json.dumps(blob))
