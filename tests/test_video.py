import json
import subprocess
from pathlib import Path

import pytest

from src.image_selector import select_images
from src.render.carousel import SlideText
from src.render.video import VideoTimeline, ffmpeg_available, render_video

BARBER_DIR = (
    Path(__file__).resolve().parent.parent / "assets" / "avatars" / "Barber" / "marketing"
)

requires_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")


# --- Pure timeline math: no ffmpeg needed, this is the part most worth getting exactly right ---


def test_timeline_rejects_single_slide():
    with pytest.raises(ValueError, match="at least 2 slides"):
        VideoTimeline(slide_count=1)


def test_timeline_rejects_xfade_longer_than_segment():
    with pytest.raises(ValueError, match="shorter than segment_duration_s"):
        VideoTimeline(slide_count=3, segment_duration_s=1.0, xfade_duration_s=1.5)


def test_timeline_offsets_and_total_duration_for_known_values():
    # 3 slides, 3s each, 0.5s crossfades -- hand-computed expectation:
    # step = 2.5s; offsets = [2.5, 5.0]; total = 3*3 - 2*0.5 = 8.0s
    timeline = VideoTimeline(slide_count=3, segment_duration_s=3.0, xfade_duration_s=0.5)
    assert timeline.step == pytest.approx(2.5)
    assert timeline.xfade_offset(0) == pytest.approx(2.5)
    assert timeline.xfade_offset(1) == pytest.approx(5.0)
    assert timeline.total_duration_s == pytest.approx(8.0)


def test_timeline_offset_out_of_range_raises():
    timeline = VideoTimeline(slide_count=3)
    with pytest.raises(ValueError, match="out of range"):
        timeline.xfade_offset(2)  # only 2 transitions exist for 3 slides (indices 0, 1)


# --- Real ffmpeg render: skipped automatically in any environment without ffmpeg on PATH ---


@pytest.fixture
def placeholder_audio(tmp_path) -> Path:
    """A short generated sine tone -- NOT for real posting, just enough for the render
    pipeline to have a real audio stream to mix/trim/fade during local testing.
    """
    audio_path = tmp_path / "placeholder-tone.mp3"
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=15",
            "-c:a", "libmp3lame", str(audio_path),
        ],
        check=True,
    )
    return audio_path


@requires_ffmpeg
def test_render_video_produces_playable_output_with_correct_duration(tmp_path, placeholder_audio):
    images = select_images(BARBER_DIR, count=4)
    texts = [SlideText(headline=f"Slide {i}", subtext="Subtext line.") for i in range(1, 5)]
    out_path = tmp_path / "out.mp4"

    render_video(images, texts, placeholder_audio, out_path, segment_duration_s=2.0, xfade_duration_s=0.4)

    assert out_path.exists()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,codec_type",
         "-of", "json", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(probe.stdout)
    duration = float(data["format"]["duration"])

    expected_timeline = VideoTimeline(4, segment_duration_s=2.0, xfade_duration_s=0.4)
    assert duration == pytest.approx(expected_timeline.total_duration_s, abs=0.15)

    stream_types = {s["codec_type"] for s in data["streams"]}
    assert "video" in stream_types
    assert "audio" in stream_types

    video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    assert (video_stream["width"], video_stream["height"]) == (1080, 1920)


@requires_ffmpeg
def test_render_video_actually_animates_between_first_and_last_frame(tmp_path, placeholder_audio):
    """Sanity check that zoompan is really doing something, not silently a no-op --
    extract the very first and very last frame and confirm they differ (the Ken Burns
    motion should mean pixel content shifts even though it's the same source photo).
    """
    images = select_images(BARBER_DIR, count=2)
    texts = [SlideText(headline="A"), SlideText(headline="B")]
    out_path = tmp_path / "out.mp4"

    render_video(images, texts, placeholder_audio, out_path, segment_duration_s=2.0, xfade_duration_s=0.4)

    first_frame = tmp_path / "first.png"
    last_frame = tmp_path / "last.png"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(out_path),
         "-vf", "select=eq(n\\,0)", "-vframes", "1", str(first_frame)],
        check=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-sseof", "-0.2", "-i", str(out_path),
         "-vframes", "1", str(last_frame)],
        check=True,
    )

    assert first_frame.read_bytes() != last_frame.read_bytes()


@requires_ffmpeg
def test_render_video_with_no_audio_path_produces_silent_video(tmp_path):
    """audio_path=None (no licensed music available yet) must still render a valid video --
    used for platforms with a manual review step (YouTube Studio's own Audio Library, TikTok
    drafts + in-app sound) rather than blocking the whole pipeline on missing music.
    """
    images = select_images(BARBER_DIR, count=2)
    texts = [SlideText(headline="A"), SlideText(headline="B")]
    out_path = tmp_path / "out.mp4"

    render_video(images, texts, None, out_path, segment_duration_s=2.0, xfade_duration_s=0.4)

    assert out_path.exists()

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    stream_types = {s["codec_type"] for s in json.loads(probe.stdout)["streams"]}
    assert stream_types == {"video"}
