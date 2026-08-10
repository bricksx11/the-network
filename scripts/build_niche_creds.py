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

Each platform's credentials are independent and optional -- matching src/credentials.py's
own "omit what a niche doesn't have configured yet" design, since a niche is commonly rolled
out platform-by-platform, not all four at once. IMPORTANT: this means a typo'd key name gets
silently dropped rather than caught -- if a value you know you added isn't showing up, check
the key spelling against KNOWN_KEYS below before assuming the platform is just "not set up
yet". YouTube is the one exception: its three fields (refresh_token/client_id/client_secret)
are all-or-nothing, since a partially-filled youtube block is broken, not just incomplete.
"""

from __future__ import annotations

import json
import sys

KNOWN_KEYS = {
    "ig_access_token",
    "meta_access_token",
    "tiktok_access_token",
    "youtube_refresh_token",
    "youtube_client_id",
    "youtube_client_secret",
}
YOUTUBE_KEYS = {"youtube_refresh_token", "youtube_client_id", "youtube_client_secret"}


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
        if key in KNOWN_KEYS and value:
            values[key] = value
    return values


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/build_niche_creds.py <path-to-creds.txt>", file=sys.stderr)
        sys.exit(1)

    values = parse_creds_file(sys.argv[1])

    youtube_present = YOUTUBE_KEYS & values.keys()
    if youtube_present and youtube_present != YOUTUBE_KEYS:
        missing = YOUTUBE_KEYS - youtube_present
        print(f"youtube block is partially filled -- missing: {', '.join(sorted(missing))}", file=sys.stderr)
        sys.exit(1)

    blob: dict = {}
    if "meta_access_token" in values:
        blob["meta_access_token"] = values["meta_access_token"]
    if "ig_access_token" in values:
        blob["ig_access_token"] = values["ig_access_token"]
    if "tiktok_access_token" in values:
        blob["tiktok_access_token"] = values["tiktok_access_token"]
    if youtube_present == YOUTUBE_KEYS:
        blob["youtube"] = {
            "refresh_token": values["youtube_refresh_token"],
            "client_id": values["youtube_client_id"],
            "client_secret": values["youtube_client_secret"],
        }

    if not blob:
        print("no known credential values found in that file -- nothing to push", file=sys.stderr)
        sys.exit(1)

    print(f"platforms included: {', '.join(sorted(blob.keys()))}", file=sys.stderr)
    print(json.dumps(blob))
