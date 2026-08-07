"""Render a set of selected images into a text-overlaid carousel, via Pillow only --
no AI image generation involved, so there's no risk of the garbled/misplaced text that
came up repeatedly when this was being done by hand through an image-generation model.

Design decision that replaces the manual "text must not overlap the face" instruction we
kept having to give an image model: text always lives in a fixed bottom-anchored zone with
a dark gradient scrim behind it. Since placement is fully deterministic here (we're drawing
pixels, not asking a model to improvise layout), there's no face-overlap failure mode to
guard against at all -- the zone is chosen to sit well clear of where a subject's face
normally falls in these photos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# Inter (like most text fonts) has no emoji glyphs, and Pillow does not fall back to a
# system emoji font automatically -- an un-stripped emoji renders as a broken tofu glyph
# instead of silently failing, which is worse than just not drawing it. Caption/comment
# text sent to platform APIs keeps emoji as normal (those render fine natively there);
# this stripping only applies to text actually drawn onto the image itself.
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols & pictographs, supplemental symbols, emoticons, transport, etc.
    "\U00002600-\U000027BF"  # misc symbols, dingbats (includes arrows-adjacent pictographs)
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flag emoji)
    "\U0000FE0F"  # variation selector-16 (emoji presentation)
    "]+",
    flags=re.UNICODE,
)


def _strip_unsupported_glyphs(text: str) -> str:
    return _EMOJI_PATTERN.sub("", text).strip()

from src.image_selector import ImageAsset

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FONT_PATH = REPO_ROOT / "assets" / "fonts" / "Inter.ttf"

CANVAS_SIZE = (1080, 1350)  # 4:5, Instagram/TikTok/Facebook carousel portrait
MARGIN = 72  # generous padding from every edge -- text must never sit flush against a side
SCRIM_HEIGHT_FRACTION = 0.42  # bottom ~42% of the canvas carries the text zone
HEADLINE_WEIGHT = 800
SUBTEXT_WEIGHT = 500
CORNER_WEIGHT = 600
HEADLINE_SIZE = 58
SUBTEXT_SIZE = 38
CORNER_SIZE = 30
LINE_SPACING = 1.18


def _load_font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(DEFAULT_FONT_PATH), size)
    try:
        font.set_variation_by_axes([14, weight])  # [optical size, weight] for Inter's axes
    except Exception:
        pass  # a non-variable fallback font just renders at its single built-in weight
    return font


def _cover_resize_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize+center-crop an image to exactly `size`, preserving aspect ratio (cover-fit)."""
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w, new_h = round(src_w * scale), round(src_h * scale)
    resized = image.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    top: int,
    max_width: int,
    fill: tuple[int, int, int, int],
) -> int:
    """Draw word-wrapped text starting at `top`, return the y-coordinate just below it."""
    lines = _wrap_text(draw, text, font, max_width)
    line_height = int(font.size * LINE_SPACING)
    y = top
    for line in lines:
        draw.text((MARGIN, y), line, font=font, fill=fill)
        y += line_height
    return y


@dataclass(frozen=True)
class SlideText:
    headline: str
    subtext: Optional[str] = None
    corner_left: Optional[str] = None  # e.g. "Save this for later." -- slide 1 only, by convention
    corner_right: Optional[str] = None  # e.g. "Swipe →" -- slide 1 only, by convention


def render_background(image_path: Path, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """Just the cover-cropped photo, no text/scrim. video.py uses this as the layer that
    gets Ken Burns motion applied -- kept separate from the text layer so panning/zooming
    the photo never distorts or jitters the text sitting on top of it.
    """
    base = Image.open(image_path).convert("RGB")
    return _cover_resize_crop(base, canvas_size)


def render_text_overlay_layer(text: SlideText, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """The scrim + headline/subtext/corner labels only, as a transparent RGBA layer sized
    to `canvas_size`. Used both to flatten onto a static carousel slide (render_slide) and,
    unflattened, as the fixed overlay layer composited on top of a moving Ken-Burns
    background in video.py.
    """
    width, height = canvas_size
    headline = _strip_unsupported_glyphs(text.headline)
    subtext = _strip_unsupported_glyphs(text.subtext) if text.subtext else None
    corner_left = _strip_unsupported_glyphs(text.corner_left) if text.corner_left else None
    corner_right = _strip_unsupported_glyphs(text.corner_right) if text.corner_right else None

    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

    scrim_top = int(height * (1 - SCRIM_HEIGHT_FRACTION))
    scrim_draw = ImageDraw.Draw(layer)
    zone_height = height - scrim_top
    for y in range(scrim_top, height):
        progress = (y - scrim_top) / zone_height
        alpha = int(190 * progress**1.4)
        scrim_draw.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    max_text_width = width - 2 * MARGIN
    white = (255, 255, 255, 255)

    y = scrim_top + int(zone_height * 0.22)
    y = _draw_wrapped_block(scrim_draw, headline, _load_font(HEADLINE_SIZE, HEADLINE_WEIGHT), y, max_text_width, white)

    if subtext:
        y += 14
        _draw_wrapped_block(scrim_draw, subtext, _load_font(SUBTEXT_SIZE, SUBTEXT_WEIGHT), y, max_text_width, white)

    corner_font = _load_font(CORNER_SIZE, CORNER_WEIGHT)
    bottom_y = height - MARGIN - CORNER_SIZE
    if corner_left:
        scrim_draw.text((MARGIN, bottom_y), corner_left, font=corner_font, fill=white)
    if corner_right:
        w = scrim_draw.textbbox((0, 0), corner_right, font=corner_font)[2]
        scrim_draw.text((width - MARGIN - w, bottom_y), corner_right, font=corner_font, fill=white)

    return layer


def render_slide(image_path: Path, text: SlideText, out_path: Path, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Path:
    """Flattened single PNG for carousel posts: background + text overlay composited together."""
    background = render_background(image_path, canvas_size).convert("RGBA")
    overlay = render_text_overlay_layer(text, canvas_size)
    canvas = Image.alpha_composite(background, overlay)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG")
    return out_path


def render_carousel(
    images: list[ImageAsset], slide_texts: list[SlideText], out_dir: Path, canvas_size: tuple[int, int] = CANVAS_SIZE
) -> list[Path]:
    if len(images) != len(slide_texts):
        raise ValueError(f"got {len(images)} images but {len(slide_texts)} slide texts -- must match 1:1")

    out_paths = []
    for i, (image, text) in enumerate(zip(images, slide_texts), start=1):
        out_path = out_dir / f"slide-{i}.png"
        out_paths.append(render_slide(image.path, text, out_path, canvas_size))
    return out_paths
