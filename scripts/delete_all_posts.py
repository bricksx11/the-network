"""One-off cleanup: delete every post the pipeline has published for a niche, on every
platform where deletion is actually possible via API.

Usage (run via GitHub Actions, where NICHE_CREDS__<NICHE> secrets actually live):
    python -m scripts.delete_all_posts --niche Barber
    python -m scripts.delete_all_posts --niche DogGroomer

TikTok is deliberately NOT handled here: the Content Posting API used by this pipeline only
supports creating drafts (post_mode=MEDIA_UPLOAD) and checking their publish status -- it
exposes no endpoint to list or delete a creator's inbox/drafts. That has to be done by hand
in the TikTok app itself (Inbox tab). Printed as a reminder at the end, not silently skipped.
"""

from __future__ import annotations

import argparse
import sys

from src.credentials import CredentialsError, load_niche_credentials
from src.publish.meta_common import GRAPH_INSTAGRAM_API_BASE, graph_delete, graph_get
from src.publish.youtube import build_youtube_client


def delete_all_instagram_media(ig_business_account_id: str, access_token: str) -> int:
    count = 0
    after = None
    while True:
        params = {"fields": "id"}
        if after:
            params["after"] = after
        result = graph_get(f"{ig_business_account_id}/media", access_token, api_base=GRAPH_INSTAGRAM_API_BASE, **params)
        media = result.get("data", [])
        for item in media:
            graph_delete(item["id"], access_token, api_base=GRAPH_INSTAGRAM_API_BASE)
            count += 1
            print(f"  deleted IG media {item['id']}")
        cursors = result.get("paging", {}).get("cursors", {})
        after = cursors.get("after") if result.get("paging", {}).get("next") else None
        if not after:
            break
    return count


def delete_all_facebook_posts(page_id: str, access_token: str) -> int:
    count = 0
    after = None
    while True:
        params = {"fields": "id"}
        if after:
            params["after"] = after
        result = graph_get(f"{page_id}/posts", access_token, **params)
        posts = result.get("data", [])
        for item in posts:
            graph_delete(item["id"], access_token)
            count += 1
            print(f"  deleted FB post {item['id']}")
        cursors = result.get("paging", {}).get("cursors", {})
        after = cursors.get("after") if result.get("paging", {}).get("next") else None
        if not after:
            break
    return count


def delete_all_youtube_uploads(youtube_creds) -> int:
    client = build_youtube_client(youtube_creds)
    channels = client.channels().list(part="contentDetails", mine=True).execute()
    items = channels.get("items", [])
    if not items:
        return 0
    uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    page_token = None
    while True:
        resp = client.playlistItems().list(
            part="contentDetails", playlistId=uploads_playlist_id, maxResults=50, pageToken=page_token
        ).execute()
        video_ids.extend(i["contentDetails"]["videoId"] for i in resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    for vid in video_ids:
        client.videos().delete(id=vid).execute()
        print(f"  deleted YouTube video {vid}")
    return len(video_ids)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", required=True)
    args = parser.parse_args()

    try:
        creds = load_niche_credentials(args.niche)
    except CredentialsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Platform IDs (ig_business_account_id / page_id) aren't in the credentials blob, so
    # they're passed in via env vars set by the calling workflow step from niches.yaml.
    import os

    ig_id = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    page_id = os.environ.get("FB_PAGE_ID")

    print(f"=== Cleanup for niche: {args.niche} ===")

    # Confirmed via a real failed run (not assumed): Instagram Graph API rejects DELETE on
    # published media for Instagram-Login-based tokens ("does not support this operation"),
    # even though the endpoint exists on paper. No programmatic deletion path -- must be
    # done by hand in the Instagram app, same situation as TikTok drafts below.
    print("Instagram: NOT deleted -- the API rejects deleting published media for this "
          "account type. Delete posts by hand in the Instagram app.")

    if creds.meta_access_token and page_id:
        print(f"Facebook ({page_id}):")
        try:
            n = delete_all_facebook_posts(page_id, creds.meta_access_token)
            print(f"  -> {n} posts deleted")
        except Exception as e:
            print(f"  -> FAILED: {e}", file=sys.stderr)
    else:
        print("Facebook: skipped (no token, or disabled/no page_id for this niche)")

    if creds.youtube:
        print("YouTube:")
        try:
            n = delete_all_youtube_uploads(creds.youtube)
            print(f"  -> {n} videos deleted")
        except Exception as e:
            print(f"  -> FAILED: {e}", file=sys.stderr)
    else:
        print("YouTube: skipped (no credentials configured)")

    print(
        "\nTikTok: NOT deleted -- the Content Posting API has no endpoint to list/delete "
        "drafts. Clear the Inbox tab manually in the TikTok app for this account."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
