"""One-off diagnostic script -- NOT part of the pipeline. Checks the real status of a
TikTok publish_id, since upload_carousel_to_drafts() only fires the init call and returns
the ID -- it never confirms the async pull-from-URL/processing actually succeeded.

Usage:
    export TIKTOK_ACCESS_TOKEN="<paste from your saved creds file>"
    python scripts/check_tiktok_publish_status.py "<publish_id>"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.publish.tiktok import check_publish_status

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/check_tiktok_publish_status.py <publish_id>", file=sys.stderr)
        sys.exit(1)

    token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if not token:
        print("set TIKTOK_ACCESS_TOKEN in your shell first", file=sys.stderr)
        sys.exit(1)

    print(check_publish_status(sys.argv[1], token))
