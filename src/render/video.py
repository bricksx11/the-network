"""Compile the same selected images used for the carousel into a short vertical video:
per-slide Ken Burns motion (zoompan) on the background photo only, a *static* text overlay
composited on top (reusing render_text_overlay_layer from carousel.py -- text never pans or
zooms, staying crisp and readable while only the photo moves underneath it), chained
crossfade transitions between slides, and a royalty-free audio track mixed in and trimmed to
the final duration. Audio is baked directly into the output file -- this is what sidesteps
Instagram/TikTok's API-level restrictions on attaching licensed audio programmatically,
confirmed unavailable via official APIs; a video file with its own embedded audio track
needs no such API field at all.

ffmpeg is invoked via subprocess with a hand-built filter_complex graph rather than a
wrapper library, so the exact command is inspectable/debuggable directly.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.image_selector import ImageAsset
from src.render.carousel import SlideText, render_background, render_text_overlay_layer

VIDEO_SIZE = (1080, 1920)  # 9:16 vertical -- Reels/Shorts/TikTok
FPS = 30
# 2.0s per slide: researched, not guessed -- short-form retention studies converge on a
# visual change every 2-3s as the pacing sweet spot, with static shots beyond ~4s becoming
# a "danger zone" where viewers scroll away. Matches the explicit 2s-max requirement too.
SEGMENT_DURATION_S = 2.0
XFADE_DURATION_S = 0.4  # crossfade length between consecutive slides (kept well under 2.0s)
ZOOM_PER_FRAME = 0.0015
MAX_ZOOM = 1.15
AUDIO_FADE_OUT_S = 1.0


class VideoRenderError(Exception):
    pass


@dataclass(frozen=True)
class VideoTimeline:
    """Small helper so the offset math (the fiddliest part of chaining xfade) is computed
    once, in one place, and is independently testable without needing to run ffmpeg at all.
    """

    slide_count: int
    segment_duration_s: float = SEGMENT_DURATION_S
    xfade_duration_s: float = XFADE_DURATION_S

    def __post_init__(self) -> None:
        if self.slide_count < 2:
            raise ValueError("need at least 2 slides to build a video timeline (crossfades need pairs)")
        if self.xfade_duration_s >= self.segment_duration_s:
            raise ValueError("xfade_duration_s must be shorter than segment_duration_s")

    @property
    def step(self) -> float:
        return self.segment_duration_s - self.xfade_duration_s

    def xfade_offset(self, transition_index: int) -> float:
        """Offset (seconds into the running merged stream) at which the `transition_index`-th
        crossfade (0-indexed, combining the stream-so-far with the next clip) should start.
        """
        if not (0 <= transition_index < self.slide_count - 1):
            raise ValueError(f"transition_index out of range: {transition_index}")
        return (transition_index + 1) * self.step

    @property
    def total_duration_s(self) -> float:
        return self.slide_count * self.segment_duration_s - (self.slide_count - 1) * self.xfade_duration_s


def _zoompan_expr(slide_index: int, fps: int, duration_s: float) -> str:
    """Alternating Ken Burns per slide: even slides push in (zoom 1.0 -> MAX_ZOOM), odd
    slides pull back (zoom MAX_ZOOM -> 1.0). Both use a centered focal point rather than a
    pan-while-zoom expression -- centered zoom is robust across arbitrary source content,
    whereas hand-tuned panning math is easy to get subtly wrong for aspect ratios/crops we
    haven't tested against. Alternation still gives visible variety between slides.
    """
    frames = round(duration_s * fps)
    if slide_index % 2 == 0:
        zoom_expr = f"min(zoom+{ZOOM_PER_FRAME},{MAX_ZOOM})"
    else:
        zoom_expr = f"if(eq(on,0),{MAX_ZOOM},max(zoom-{ZOOM_PER_FRAME},1.0))"
    return (
        f"zoompan=z='{zoom_expr}':d={frames}"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":s={VIDEO_SIZE[0]}x{VIDEO_SIZE[1]}:fps={fps}"
    )


def _run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VideoRenderError(f"ffmpeg failed (exit {result.returncode}):\n{result.stderr}")


def render_video(
    images: list[ImageAsset],
    slide_texts: list[SlideText],
    audio_path: Optional[Path],
    out_path: Path,
    fps: int = FPS,
    segment_duration_s: float = SEGMENT_DURATION_S,
    xfade_duration_s: float = XFADE_DURATION_S,
) -> Path:
    """audio_path=None renders a silent video -- used when no licensed music track is
    available yet. Silent output is safe to upload to platforms with a manual review step
    (YouTube private upload + Studio's own Audio Library, TikTok drafts + in-app sound) but
    should never be auto-published somewhere with no such step (e.g. Instagram Reels).
    """
    if len(images) != len(slide_texts):
        raise ValueError(f"got {len(images)} images but {len(slide_texts)} slide texts -- must match 1:1")
    if audio_path is not None and not audio_path.exists():
        raise VideoRenderError(f"audio track not found: {audio_path}")

    timeline = VideoTimeline(len(images), segment_duration_s, xfade_duration_s)

    with tempfile.TemporaryDirectory(prefix="the-network-video-") as tmp:
        tmp_dir = Path(tmp)
        bg_paths, overlay_paths = [], []
        for i, (image, text) in enumerate(zip(images, slide_texts)):
            bg = render_background(image.path, VIDEO_SIZE)
            bg_path = tmp_dir / f"bg-{i}.png"
            bg.save(bg_path)
            bg_paths.append(bg_path)

            overlay = render_text_overlay_layer(text, VIDEO_SIZE)
            overlay_path = tmp_dir / f"overlay-{i}.png"
            overlay.save(overlay_path)
            overlay_paths.append(overlay_path)

        _render_video_from_assets(bg_paths, overlay_paths, audio_path, out_path, timeline, fps)

    return out_path


def _render_video_from_assets(
    bg_paths: list[Path],
    overlay_paths: list[Path],
    audio_path: Optional[Path],
    out_path: Path,
    timeline: VideoTimeline,
    fps: int,
) -> None:
    n = len(bg_paths)
    input_args: list[str] = []
    filter_parts: list[str] = []

    # Two inputs per slide (moving background + static overlay), then audio last (if any).
    for i in range(n):
        input_args += ["-loop", "1", "-t", str(timeline.segment_duration_s), "-r", str(fps), "-i", str(bg_paths[i])]
        input_args += ["-loop", "1", "-t", str(timeline.segment_duration_s), "-r", str(fps), "-i", str(overlay_paths[i])]
    if audio_path is not None:
        input_args += ["-i", str(audio_path)]

    seg_labels = []
    for i in range(n):
        bg_in = 2 * i
        ov_in = 2 * i + 1
        zoompan = _zoompan_expr(i, fps, timeline.segment_duration_s)
        filter_parts.append(f"[{bg_in}:v]{zoompan},format=rgba[bgz{i}]")
        filter_parts.append(f"[{ov_in}:v]format=rgba[ov{i}]")
        filter_parts.append(f"[bgz{i}][ov{i}]overlay=0:0:format=auto[seg{i}]")
        seg_labels.append(f"seg{i}")

    # Chain xfade across the N composited segments.
    running_label = seg_labels[0]
    for i in range(1, n):
        offset = timeline.xfade_offset(i - 1)
        out_label = f"xf{i}" if i < n - 1 else "vout"
        filter_parts.append(
            f"[{running_label}][{seg_labels[i]}]xfade=transition=fade:duration={timeline.xfade_duration_s}:offset={offset}[{out_label}]"
        )
        running_label = out_label

    total_duration = timeline.total_duration_s
    map_args = ["-map", "[vout]"]
    codec_args = ["-c:v", "libx264", "-pix_fmt", "yuv420p"]

    if audio_path is not None:
        audio_input_index = 2 * n
        fade_start = max(total_duration - AUDIO_FADE_OUT_S, 0)
        filter_parts.append(
            f"[{audio_input_index}:a]atrim=0:{total_duration},afade=t=out:st={fade_start}:d={AUDIO_FADE_OUT_S}[aout]"
        )
        map_args += ["-map", "[aout]"]
        codec_args += ["-c:a", "aac"]

    filter_complex = ";".join(filter_parts)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            *input_args,
            "-filter_complex",
            filter_complex,
            *map_args,
            "-t",
            str(total_duration),
            *codec_args,
            "-shortest",
            str(out_path),
        ]
    )


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None
