"""Render a set of selected images into a text-overlaid carousel, via Pillow only --
no AI image generation involved, so there's no risk of the garbled/misplaced text that
came up repeatedly when this was being done by hand through an image-generation model.

Design decision that replaces the manual "text must not overlap the face" instruction we
kept having to give an image model: text always lives in a fixed bottom-anchored zone.
Since placement is fully deterministic here (we're drawing pixels, not asking a model to
improvise layout), there's no face-overlap failure mode to guard against at all -- the zone
is chosen to sit well clear of where a subject's face normally falls in these photos.

Text style: a white rounded-rectangle box sized to fit its own text, black bold text inside
-- the "handmade caption" look (per a reference example), not a translucent gradient scrim
with white text. This also means the box reads cleanly against any photo regardless of how
busy/bright it is, since it's fully opaque rather than relying on darkening the photo
underneath for contrast.
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
TEXT_ZONE_HEIGHT_FRACTION = 0.42  # bottom ~42% of the canvas is the safe zone for text boxes
HEADLINE_WEIGHT = 800
SUBTEXT_WEIGHT = 600
CORNER_WEIGHT = 700
HEADLINE_SIZE = 54
SUBTEXT_SIZE = 34
CORNER_SIZE = 26
LINE_SPACING = 1.18

BOX_FILL = (255, 255, 255, 255)
BOX_TEXT_FILL = (10, 10, 10, 255)
BOX_RADIUS = 22
BOX_PAD_X = 26
BOX_PAD_Y = 18
BOX_GAP = 18  # vertical gap between stacked boxes (headline -> subtext, etc.)


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


def _draw_boxed_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    top: int,
    canvas_width: int,
    max_text_width: int,
) -> int:
    """Draw a white rounded-rectangle box sized to fit `text` (word-wrapped, centered), with
    black bold text inside -- the "handmade caption" look. Box is horizontally centered on
    the canvas. Returns the y-coordinate just below the box (for stacking the next one).
    """
    lines = _wrap_text(draw, text, font, max_text_width)
    if not lines:
        return top

    line_height = int(font.size * LINE_SPACING)
    line_widths = [draw.textbbox((0, 0), line, font=font)[2] for line in lines]
    block_width = max(line_widths)
    block_height = line_height * len(lines)

    box_left = (canvas_width - block_width) // 2 - BOX_PAD_X
    box_right = (canvas_width + block_width) // 2 + BOX_PAD_X
    box_top = top
    box_bottom = top + block_height + 2 * BOX_PAD_Y
    draw.rounded_rectangle((box_left, box_top, box_right, box_bottom), radius=BOX_RADIUS, fill=BOX_FILL)

    y = box_top + BOX_PAD_Y
    for line, line_width in zip(lines, line_widths):
        x = (canvas_width - line_width) // 2
        draw.text((x, y), line, font=font, fill=BOX_TEXT_FILL)
        y += line_height

    return box_bottom


@dataclass(frozen=True)
class SlideText:
    headline: str
    subtext: Optional[str] = None
    corner_left: Optional[str] = None  # e.g. "Save this for later." -- slide 1 only, by convention
    corner_right: Optional[str] = None  # e.g. "Swipe →" -- slide 1 only, by convention


def render_background(image_path: Path, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """Just the cover-cropped photo, no text. video.py uses this as the layer that
    gets Ken Burns motion applied -- kept separate from the text layer so panning/zooming
    the photo never distorts or jitters the text sitting on top of it.
    """
    base = Image.open(image_path).convert("RGB")
    return _cover_resize_crop(base, canvas_size)


def render_text_overlay_layer(text: SlideText, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Image.Image:
    """The headline/subtext/corner label boxes only, as a transparent RGBA layer sized
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
    draw = ImageDraw.Draw(layer)

    zone_top = int(height * (1 - TEXT_ZONE_HEIGHT_FRACTION))
    max_text_width = width - 2 * MARGIN

    y = zone_top
    y = _draw_boxed_text_block(draw, headline, _load_font(HEADLINE_SIZE, HEADLINE_WEIGHT), y, width, max_text_width)

    if subtext:
        y += BOX_GAP
        _draw_boxed_text_block(draw, subtext, _load_font(SUBTEXT_SIZE, SUBTEXT_WEIGHT), y, width, max_text_width)

    corner_font = _load_font(CORNER_SIZE, CORNER_WEIGHT)
    corner_top = height - MARGIN - CORNER_SIZE - 2 * BOX_PAD_Y
    if corner_left:
        _draw_left_boxed_text(draw, corner_left, corner_font, MARGIN, corner_top)
    if corner_right:
        _draw_right_boxed_text(draw, corner_right, corner_font, width - MARGIN, corner_top)

    return layer


def _draw_left_boxed_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, left: int, top: int) -> None:
    """Small white-box label anchored by its left edge (bottom-left corner label)."""
    width = draw.textbbox((0, 0), text, font=font)[2]
    box = (left - BOX_PAD_X, top, left + width + BOX_PAD_X, top + font.size + 2 * BOX_PAD_Y)
    draw.rounded_rectangle(box, radius=BOX_RADIUS, fill=BOX_FILL)
    draw.text((left, top + BOX_PAD_Y), text, font=font, fill=BOX_TEXT_FILL)


def _draw_right_boxed_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, right: int, top: int) -> None:
    """Small white-box label anchored by its right edge (bottom-right corner label)."""
    width = draw.textbbox((0, 0), text, font=font)[2]
    box = (right - width - BOX_PAD_X, top, right + BOX_PAD_X, top + font.size + 2 * BOX_PAD_Y)
    draw.rounded_rectangle(box, radius=BOX_RADIUS, fill=BOX_FILL)
    draw.text((right - width, top + BOX_PAD_Y), text, font=font, fill=BOX_TEXT_FILL)


JPEG_QUALITY = 92


def render_slide(image_path: Path, text: SlideText, out_path: Path, canvas_size: tuple[int, int] = CANVAS_SIZE) -> Path:
    """Flattened single JPEG for carousel posts: background + text overlay composited
    together. JPEG, not PNG -- confirmed via a real TikTok API failure
    (file_format_check_failed) that TikTok's Content Posting API rejects PNG outright for
    photo posts, JPEG/WEBP only. Instagram/Facebook accept both, so this is a safe universal
    choice rather than needing a platform-specific render path.
    """
    background = render_background(image_path, canvas_size).convert("RGBA")
    overlay = render_text_overlay_layer(text, canvas_size)
    canvas = Image.alpha_composite(background, overlay)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "JPEG", quality=JPEG_QUALITY)
    return out_path


def render_carousel(
    images: list[ImageAsset], slide_texts: list[SlideText], out_dir: Path, canvas_size: tuple[int, int] = CANVAS_SIZE
) -> list[Path]:
    if len(images) != len(slide_texts):
        raise ValueError(f"got {len(images)} images but {len(slide_texts)} slide texts -- must match 1:1")

    out_paths = []
    for i, (image, text) in enumerate(zip(images, slide_texts), start=1):
        out_path = out_dir / f"slide-{i}.jpg"
        out_paths.append(render_slide(image.path, text, out_path, canvas_size))
    return out_paths
