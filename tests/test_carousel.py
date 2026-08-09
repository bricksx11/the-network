from pathlib import Path

from PIL import Image

from src.image_selector import select_images
from src.render.carousel import (
    CANVAS_SIZE,
    SlideText,
    _strip_unsupported_glyphs,
    render_carousel,
    render_slide,
)

BARBER_DIR = (
    Path(__file__).resolve().parent.parent / "assets" / "avatars" / "Barber" / "marketing"
)


def test_render_slide_produces_correctly_sized_png(tmp_path):
    images = select_images(BARBER_DIR, count=1)
    out_path = render_slide(
        images[0].path,
        SlideText(headline="Test headline", subtext="Test subtext line here."),
        tmp_path / "slide-1.png",
    )
    assert out_path.exists()
    with Image.open(out_path) as img:
        assert img.size == CANVAS_SIZE
        assert img.mode == "RGB"


def test_render_slide_handles_long_wrapping_text_without_error(tmp_path):
    images = select_images(BARBER_DIR, count=1)
    long_headline = "This is a deliberately long headline that should wrap across several lines to test the word wrap logic thoroughly."
    render_slide(images[0].path, SlideText(headline=long_headline), tmp_path / "slide-1.png")


def test_render_slide_with_corner_labels(tmp_path):
    images = select_images(BARBER_DIR, count=1)
    render_slide(
        images[0].path,
        SlideText(headline="Hook line", corner_left="Save this for later.", corner_right="Swipe →"),
        tmp_path / "slide-1.png",
    )


def test_render_carousel_produces_one_file_per_slide(tmp_path):
    images = select_images(BARBER_DIR, count=4)
    texts = [SlideText(headline=f"Slide {i}") for i in range(1, 5)]
    out_paths = render_carousel(images, texts, tmp_path)
    assert len(out_paths) == 4
    for p in out_paths:
        assert p.exists()


def test_strip_unsupported_glyphs_removes_emoji_but_keeps_text():
    # Inter has no emoji glyphs -- an un-stripped emoji renders as a broken tofu box
    # (caught by visual inspection of a real rendered preview), so it must be stripped
    # before anything is drawn, while leaving the surrounding real text untouched.
    assert _strip_unsupported_glyphs("Comment 'CALLS' and I'll send you the app 👇") == (
        "Comment 'CALLS' and I'll send you the app"
    )
    assert _strip_unsupported_glyphs("Swipe →") == "Swipe →"  # plain arrow glyph, not an emoji, keep it
    assert _strip_unsupported_glyphs("No emoji here.") == "No emoji here."


def test_headline_renders_as_white_box_with_dark_text(tmp_path):
    """Locks in the actual visual style (white rounded box, black text inside) with a real
    pixel check -- not just "doesn't crash" -- since this is a deliberate, specific design
    requirement, not an implementation detail.
    """
    images = select_images(BARBER_DIR, count=1)
    out_path = render_slide(images[0].path, SlideText(headline="Hook"), tmp_path / "slide-1.png")

    with Image.open(out_path) as img:
        width, height = img.size
        zone_top = int(height * (1 - 0.42))  # matches TEXT_ZONE_HEIGHT_FRACTION
        band = img.crop((0, zone_top, width, zone_top + 120))
        pixels = list(band.getdata())

        near_white = [p for p in pixels if min(p[:3]) > 240]
        near_black = [p for p in pixels if max(p[:3]) < 60]

        assert near_white, "expected white box pixels in the headline's safe zone"
        assert near_black, "expected dark text pixels in the headline's safe zone"


def test_render_carousel_raises_on_mismatched_lengths(tmp_path):
    images = select_images(BARBER_DIR, count=3)
    texts = [SlideText(headline="only one")]
    try:
        render_carousel(images, texts, tmp_path)
        assert False, "expected ValueError"
    except ValueError:
        pass
