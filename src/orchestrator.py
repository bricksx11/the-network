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

from src.image_selector import select_images
from src.render.carousel import SlideText, render_carousel
from src.render.video import render_video
from src.research_gate import ResearchGateError, run_research_gate
from src.script_provider import get_todays_script

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


if __name__ == "__main__":
    import sys

    niche = sys.argv[1] if len(sys.argv) > 1 else "Barber"
    try:
        record = run_niche(niche, REPO_ROOT / "render_output")
        print(json.dumps(record, indent=2))
    except (OrchestratorError, ResearchGateError) as e:
        print(f"pipeline stopped: {e}", file=sys.stderr)
        sys.exit(1)
