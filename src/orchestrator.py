"""Ties every stage together for one niche: script -> research gate -> image selection ->
render (carousel + video) -> run log. This is the local, no-credentials-needed half of the
pipeline (everything up to "verify output locally before any API wiring", per the plan) --
publish/*.py wiring happens later, gated on real platform credentials.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.credentials import load_niche_credentials
from src.image_selector import select_images
from src.publish.facebook import publish_carousel as fb_publish_carousel
from src.publish.hosting import publish_to_scratch_branch
from src.publish.instagram import publish_carousel as ig_publish_carousel
from src.publish.instagram import publish_reel as ig_publish_reel
from src.publish.tiktok import upload_carousel_to_drafts
from src.publish.youtube import build_youtube_client, upload_private_video
from src.render.carousel import SlideText, render_carousel
from src.render.video import render_video
from src.research_gate import ResearchGateError, run_research_gate
from src.script_provider import get_todays_script

GITHUB_OWNER = "bricksx11"
GITHUB_REPO = "the-network"

REPO_ROOT = Path(__file__).resolve().parent.parent
NICHES_CONFIG_PATH = REPO_ROOT / "config" / "niches.yaml"
MUSIC_DIR = REPO_ROOT / "assets" / "music"
LOGS_DIR = REPO_ROOT / "logs"

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac")


class OrchestratorError(Exception):
    pass


def load_niche_config(niche: str) -> dict:
    all_config = yaml.safe_load(NICHES_CONFIG_PATH.read_text())
    niches = all_config.get("niches", {})
    if niche not in niches:
        raise OrchestratorError(f"unknown niche {niche!r} -- not present in {NICHES_CONFIG_PATH}")
    return niches[niche]


def find_music_track(rng: random.Random) -> Path:
    """Pick a random committed, licensed royalty-free track. Raises a clear, actionable
    error if the music library is still empty -- this must never silently fall back to a
    placeholder tone outside of tests, since that would risk shipping unlicensed/no audio
    without anyone noticing.
    """
    tracks = [p for p in MUSIC_DIR.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS]
    if not tracks:
        raise OrchestratorError(
            f"no music tracks found under {MUSIC_DIR} -- add licensed royalty-free audio "
            f"files (with a LICENSE.txt per track, per the plan) before rendering real "
            f"video output. See assets/music/README.md."
        )
    return rng.choice(tracks)


def build_slide_texts(script, platform: str | None = None) -> list[SlideText]:
    """Map a Script (hook / beats / reveal / cta) onto one SlideText per slide, matching
    the pattern validated by hand this session: slide 1 is the hook (with the save/swipe
    corner labels), one slide per story beat, and a final slide combining the reveal as the
    headline with the CTA as the subtext.
    """
    cta = script.platform_cta_overrides.get(platform, script.cta) if platform else script.cta

    slides = [SlideText(headline=script.hook, corner_left="Save this for later.", corner_right="Swipe →")]
    slides += [SlideText(headline=beat) for beat in script.beats]
    slides.append(SlideText(headline=script.reveal, subtext=cta))
    return slides


def run_niche(niche: str, out_dir: Path, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    niche_config = load_niche_config(niche)
    image_dir = REPO_ROOT / niche_config["image_dir"]

    script = get_todays_script(niche)
    gate_result = run_research_gate(script, trend_seed_keyword=niche_config.get("trend_seed_keyword"))

    slide_texts = build_slide_texts(script)
    images = select_images(image_dir, count=len(slide_texts), rng=rng)

    carousel_dir = out_dir / niche / "carousel"
    carousel_paths = render_carousel(images, slide_texts, carousel_dir)

    video_path = out_dir / niche / "video" / "reel.mp4"
    music_track = find_music_track(rng)
    render_video(images, slide_texts, music_track, video_path)

    run_record = {
        "niche": niche,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "shape": gate_result.shape,
        "trend_signal": asdict(gate_result.trend_signal) if gate_result.trend_signal else None,
        "images_used": [str(a.path.relative_to(REPO_ROOT)) for a in images],
        "music_track": str(music_track.relative_to(REPO_ROOT)),
        "carousel_output": [str(p.relative_to(out_dir)) for p in carousel_paths],
        "video_output": str(video_path.relative_to(out_dir)),
    }

    LOGS_DIR.mkdir(exist_ok=True)
    log_path = LOGS_DIR / f"{niche}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    log_path.write_text(json.dumps(run_record, indent=2))
    run_record["log_path"] = str(log_path.relative_to(REPO_ROOT))

    return run_record


def publish_niche(
    niche: str,
    niche_config: dict,
    carousel_paths: list[Path],
    video_path: Path,
    script,
    repo_root: Path = REPO_ROOT,
    github_owner: str = GITHUB_OWNER,
    github_repo: str = GITHUB_REPO,
) -> dict:
    """Publish rendered output to every enabled, ID-configured platform for this niche.
    A platform missing its account/page ID in niche_config (still null -- not yet
    provisioned) is skipped and reported as such, rather than attempted or erroring, per
    the plan's "refuse to run for a niche/platform combination where the relevant ID is
    still null."

    Carousel images and the video are hosted in a single scratch-branch push (not two
    separate ones) -- pushing twice would force-overwrite the first push's files before
    Instagram/TikTok/Facebook ever get a chance to fetch them, since each push replaces
    the branch's entire contents.
    """
    creds = load_niche_credentials(niche)
    platforms = niche_config.get("platforms", {})
    results: dict = {}

    needs_carousel_urls = any(
        platforms.get(p, {}).get("enabled") for p in ("instagram", "facebook", "tiktok")
    )
    needs_video_url = platforms.get("instagram", {}).get("enabled") and platforms["instagram"].get(
        "business_account_id"
    )

    carousel_urls: list[str] = []
    video_url: str | None = None
    if needs_carousel_urls or needs_video_url:
        files_to_host = list(carousel_paths) + ([video_path] if needs_video_url else [])
        urls = publish_to_scratch_branch(files_to_host, repo_root, github_owner, github_repo)
        carousel_urls = urls[: len(carousel_paths)]
        if needs_video_url:
            video_url = urls[len(carousel_paths)]

    caption = f"{script.hook}\n\n{script.cta}"

    ig = platforms.get("instagram", {})
    if ig.get("enabled") and ig.get("business_account_id") and creds.meta_access_token:
        carousel_id = ig_publish_carousel(ig["business_account_id"], carousel_urls, caption, creds.meta_access_token)
        reel_id = ig_publish_reel(ig["business_account_id"], video_url, caption, creds.meta_access_token)
        results["instagram"] = {"carousel_post_id": carousel_id, "reel_post_id": reel_id}
    else:
        results["instagram"] = {"skipped": "not configured"}

    fb = platforms.get("facebook", {})
    if fb.get("enabled") and fb.get("page_id") and creds.meta_access_token:
        post_id = fb_publish_carousel(fb["page_id"], carousel_urls, caption, creds.meta_access_token)
        results["facebook"] = {"post_id": post_id}
    else:
        results["facebook"] = {"skipped": "not configured"}

    tt = platforms.get("tiktok", {})
    if tt.get("enabled") and creds.tiktok_access_token:
        publish_id = upload_carousel_to_drafts(carousel_urls, script.hook, script.cta, creds.tiktok_access_token)
        results["tiktok"] = {"publish_id": publish_id}
    else:
        results["tiktok"] = {"skipped": "not configured"}

    yt = platforms.get("youtube", {})
    if yt.get("enabled") and creds.youtube:
        youtube_client = build_youtube_client(creds.youtube)
        cta = script.platform_cta_overrides.get("youtube", script.cta)
        video_id = upload_private_video(youtube_client, video_path, script.hook, f"{script.reveal}\n\n{cta}")
        results["youtube"] = {"video_id": video_id}
    else:
        results["youtube"] = {"skipped": "not configured"}

    return results


if __name__ == "__main__":
    import sys

    niche = sys.argv[1] if len(sys.argv) > 1 else "Barber"
    try:
        record = run_niche(niche, REPO_ROOT / "render_output")
        print(json.dumps(record, indent=2))
    except (OrchestratorError, ResearchGateError) as e:
        print(f"pipeline stopped: {e}", file=sys.stderr)
        sys.exit(1)
