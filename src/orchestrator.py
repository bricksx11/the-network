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

from src.caption_builder import build_caption
from src.content_history import load_recent, recent_image_paths
from src.credentials import load_niche_credentials
from src.image_selector import select_images
from src.publish.facebook import publish_carousel as fb_publish_carousel
from src.publish.hosting import publish_to_scratch_branch
from src.publish.instagram import publish_carousel as ig_publish_carousel
from src.publish.instagram import publish_reel as ig_publish_reel
from src.publish.tiktok import upload_carousel_to_drafts, wait_for_publish_complete
from src.publish.youtube import build_youtube_client, upload_private_video
from src.render.carousel import SlideText, render_carousel
from src.render.video import render_video
from src.research_gate import ResearchGateError, run_research_gate
from src.script_generator import ScriptGenerationError
from src.script_provider import get_todays_script

GITHUB_OWNER = "bricksx11"
GITHUB_REPO = "the-network"

REPO_ROOT = Path(__file__).resolve().parent.parent
NICHES_CONFIG_PATH = REPO_ROOT / "config" / "niches.yaml"
CONTENT_INTELLIGENCE_DIR = REPO_ROOT / "config" / "content_intelligence"
CAMPAIGN_CONFIG_PATH = REPO_ROOT / "config" / "campaign.yaml"
MUSIC_DIR = REPO_ROOT / "assets" / "music"
LOGS_DIR = REPO_ROOT / "logs"

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav", ".aac")

# Script generation is done once per run and reused across every platform's carousel/video --
# "instagram" is the primary/canonical platform for content flavor (carousel-first pipeline);
# caption_builder.py handles the real per-platform variation on top of that single script.
PRIMARY_GENERATION_PLATFORM = "instagram"

MAX_AVOID_WORDS_ATTEMPTS = 2  # first attempt + one regenerate before failing loudly


class OrchestratorError(Exception):
    pass


def load_niche_config(niche: str) -> dict:
    all_config = yaml.safe_load(NICHES_CONFIG_PATH.read_text())
    niches = all_config.get("niches", {})
    if niche not in niches:
        raise OrchestratorError(f"unknown niche {niche!r} -- not present in {NICHES_CONFIG_PATH}")
    return niches[niche]


def load_content_intelligence(niche: str) -> dict:
    path = CONTENT_INTELLIGENCE_DIR / f"{niche}.yaml"
    if not path.exists():
        raise OrchestratorError(f"no content-intelligence config for niche {niche!r} -- expected {path}")
    return yaml.safe_load(path.read_text()) or {}


def load_campaign_config() -> dict:
    if not CAMPAIGN_CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CAMPAIGN_CONFIG_PATH.read_text()) or {}


def _find_avoid_word(script, content_intelligence: dict) -> str | None:
    """Scan the generated script's actual text against the niche's avoid_words list --
    the repetition/shape checks inside generate_script() don't check wording against this
    list, only against recent history and PROVEN_SHAPES structure, so this is a genuinely
    separate check (plan step 8).
    """
    avoid_words = content_intelligence.get("avoid_words", [])
    text = " ".join([script.hook, *script.beats, script.reveal or "", script.cta]).lower()
    for phrase in avoid_words:
        if phrase.lower() in text:
            return phrase
    return None


def find_music_track(rng: random.Random) -> Path | None:
    """Pick a random committed, licensed royalty-free track, or None if the library is still
    empty. None renders a silent video rather than blocking the whole run -- safe for
    platforms with a manual review step (YouTube + Studio's own Audio Library, TikTok drafts
    + in-app sound) where real audio gets added after upload. Never silently substitutes a
    placeholder tone -- that would risk shipping unlicensed audio without anyone noticing.
    Callers that auto-publish with no manual step (Instagram Reels) must not rely on this
    returning a track; treat None there as "not ready for Reels yet."
    """
    tracks = [p for p in MUSIC_DIR.rglob("*") if p.suffix.lower() in AUDIO_EXTENSIONS]
    if not tracks:
        print(
            f"warning: no music tracks found under {MUSIC_DIR} -- rendering silent video. "
            f"Add real licensed audio via assets/music/README.md before enabling Instagram "
            f"Reels (no manual step there to add audio after the fact)."
        )
        return None
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


def run_niche(niche: str, out_dir: Path, rng: random.Random | None = None, publish: bool = True) -> dict:
    """Render (always) and publish (by default). `publish=False` is for local dev/testing
    without needing any platform credentials set -- matches how this was verified end to
    end locally before any API wiring existed.
    """
    rng = rng or random.Random()
    niche_config = load_niche_config(niche)
    image_dir = REPO_ROOT / niche_config["image_dir"]

    content_intelligence = load_content_intelligence(niche)
    campaign = load_campaign_config()
    recent_history = load_recent(niche)

    script, topic_summary = get_todays_script(
        niche, PRIMARY_GENERATION_PLATFORM, content_intelligence, campaign, recent_history
    )
    avoid_hit = _find_avoid_word(script, content_intelligence)
    for _ in range(MAX_AVOID_WORDS_ATTEMPTS - 1):
        if avoid_hit is None:
            break
        script, topic_summary = get_todays_script(
            niche, PRIMARY_GENERATION_PLATFORM, content_intelligence, campaign, recent_history
        )
        avoid_hit = _find_avoid_word(script, content_intelligence)
    if avoid_hit is not None:
        raise OrchestratorError(
            f"generated script for {niche} still contains banned phrase {avoid_hit!r} after "
            f"{MAX_AVOID_WORDS_ATTEMPTS} attempts -- stopping rather than publishing generic AI copy"
        )

    gate_result = run_research_gate(script, trend_seed_keyword=niche_config.get("trend_seed_keyword"))

    slide_texts = build_slide_texts(script)
    images = select_images(
        image_dir, count=len(slide_texts), rng=rng, recent_images=recent_image_paths(recent_history)
    )

    carousel_dir = out_dir / niche / "carousel"
    carousel_paths = render_carousel(images, slide_texts, carousel_dir)

    # The video is currently only ever published to YouTube (Instagram Reel is off via
    # post_reel: false) -- its last-slide on-screen CTA needs to be YouTube's own override
    # ("Link in bio"), not the default comment-bait CTA baked into the carousel's slides.
    # Same images, different text. Revisit this if Instagram Reel (sharing this same file)
    # ever gets re-enabled -- "Link in bio" on-screen may not be the right call there too.
    video_slide_texts = build_slide_texts(script, platform="youtube")
    video_path = out_dir / niche / "video" / "reel.mp4"
    music_track = find_music_track(rng)
    render_video(images, video_slide_texts, music_track, video_path)

    run_record = {
        "niche": niche,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "shape": gate_result.shape,
        "hook": script.hook,
        "topic_summary": topic_summary,
        "trend_signal": asdict(gate_result.trend_signal) if gate_result.trend_signal else None,
        "images_used": [str(a.path.relative_to(REPO_ROOT)) for a in images],
        "music_track": str(music_track.relative_to(REPO_ROOT)) if music_track else None,
        "carousel_output": [str(p.relative_to(out_dir)) for p in carousel_paths],
        "video_output": str(video_path.relative_to(out_dir)),
    }

    if publish:
        run_record["publish_results"] = publish_niche(
            niche,
            niche_config,
            carousel_paths,
            video_path,
            script,
            content_intelligence,
            campaign,
            has_music=music_track is not None,
        )

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
    content_intelligence: dict,
    campaign: dict,
    repo_root: Path = REPO_ROOT,
    github_owner: str = GITHUB_OWNER,
    github_repo: str = GITHUB_REPO,
    has_music: bool = True,
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

    has_music=False means video_path is a silent render (no licensed track available yet).
    That's fine for platforms with a manual review step, but Instagram Reels auto-publish
    immediately with no such step -- so the Reel specifically is skipped rather than posting
    dead-silent public content, even though the carousel (unaffected by audio) still goes out.

    instagram.post_reel: false in niche_config is a separate, explicit override that skips
    the Reel regardless of has_music -- for staying carousel-only on Instagram by choice
    (e.g. while still deciding on Reel content/audio), independent of the music guard above.
    """
    creds = load_niche_credentials(niche)
    platforms = niche_config.get("platforms", {})
    results: dict = {}

    needs_carousel_urls = any(
        platforms.get(p, {}).get("enabled") for p in ("instagram", "facebook", "tiktok")
    )
    ig_config = platforms.get("instagram", {})
    needs_video_url = (
        ig_config.get("enabled") and ig_config.get("business_account_id") and ig_config.get("post_reel", True)
    )

    carousel_urls: list[str] = []
    video_url: str | None = None
    if needs_carousel_urls or needs_video_url:
        files_to_host = list(carousel_paths) + ([video_path] if needs_video_url else [])
        urls = publish_to_scratch_branch(files_to_host, repo_root, github_owner, github_repo)
        carousel_urls = urls[: len(carousel_paths)]
        if needs_video_url:
            video_url = urls[len(carousel_paths)]

    ig = ig_config
    if ig.get("enabled") and ig.get("business_account_id") and creds.ig_access_token:
        ig_caption = build_caption(script, content_intelligence, campaign, "instagram")
        carousel_id = ig_publish_carousel(
            ig["business_account_id"], carousel_urls, ig_caption, creds.ig_access_token
        )
        ig_result: dict = {"carousel_post_id": carousel_id}
        if not ig.get("post_reel", True):
            ig_result["reel_skipped"] = "post_reel disabled in config -- carousel only for now"
        elif has_music:
            ig_result["reel_post_id"] = ig_publish_reel(
                ig["business_account_id"], video_url, ig_caption, creds.ig_access_token
            )
        else:
            ig_result["reel_skipped"] = "no licensed music available -- silent Reel not auto-published"
        results["instagram"] = ig_result
    else:
        results["instagram"] = {"skipped": "not configured"}

    fb = platforms.get("facebook", {})
    if fb.get("enabled") and fb.get("page_id") and creds.meta_access_token:
        fb_caption = build_caption(script, content_intelligence, campaign, "facebook")
        post_id = fb_publish_carousel(fb["page_id"], carousel_urls, fb_caption, creds.meta_access_token)
        results["facebook"] = {"post_id": post_id}
    else:
        results["facebook"] = {"skipped": "not configured"}

    tt = platforms.get("tiktok", {})
    if tt.get("enabled") and creds.tiktok_access_token:
        tt_caption = build_caption(script, content_intelligence, campaign, "tiktok")
        publish_id = upload_carousel_to_drafts(carousel_urls, script.hook, tt_caption, creds.tiktok_access_token)
        # init returning a publish_id only means TikTok accepted the request, not that it
        # actually finished pulling/processing the images -- confirmed the hard way (a real
        # publish_id whose actual status later came back FAILED, file_format_check_failed).
        # Wait for a real terminal status so a silent failure doesn't get reported as success.
        wait_for_publish_complete(publish_id, creds.tiktok_access_token)
        results["tiktok"] = {"publish_id": publish_id}
    else:
        results["tiktok"] = {"skipped": "not configured"}

    yt = platforms.get("youtube", {})
    if yt.get("enabled") and creds.youtube:
        youtube_client = build_youtube_client(creds.youtube)
        # niche_config's cta_override is the actual source of truth (e.g. "Link in bio" --
        # YouTube has no DM/comment-bait culture) -- takes priority over campaign.yaml's
        # default CTA via caption_builder's cta_override param.
        yt_description = build_caption(
            script, content_intelligence, campaign, "youtube", cta_override=yt.get("cta_override")
        )
        video_id = upload_private_video(youtube_client, video_path, script.hook, yt_description)
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
    except (OrchestratorError, ResearchGateError, ScriptGenerationError) as e:
        print(f"pipeline stopped: {e}", file=sys.stderr)
        sys.exit(1)
