import random
from pathlib import Path

import pytest

from src.image_selector import ImageSelectorError, list_niche_images, select_images

BARBER_DIR = (
    Path(__file__).resolve().parent.parent / "assets" / "avatars" / "Barber" / "marketing"
)


def test_lists_real_barber_images_with_expected_roles():
    assets = list_niche_images(BARBER_DIR)
    by_name = {a.path.name: a.role for a in assets}

    assert by_name["aura-1.png"] == "host"
    assert by_name["aura-4.png"] == "host"
    assert by_name["haircut-1.png"] == "pool"
    assert by_name["washing-1.png"] == "pool"
    assert "manifest.yaml" not in by_name  # non-image files must be excluded


def test_select_images_slide_one_is_always_host():
    rng = random.Random(0)
    for _ in range(25):
        chosen = select_images(BARBER_DIR, count=5, rng=rng)
        assert chosen[0].role == "host"


def test_select_images_never_repeats_within_one_piece():
    rng = random.Random(1)
    for _ in range(25):
        chosen = select_images(BARBER_DIR, count=5, rng=rng)
        paths = [a.path for a in chosen]
        assert len(paths) == len(set(paths))


def test_select_images_can_reuse_across_separate_calls():
    # No persistent "already used" state -- two independent selections are allowed to overlap.
    rng = random.Random(2)
    first = {a.path for a in select_images(BARBER_DIR, count=5, rng=rng)}
    second = {a.path for a in select_images(BARBER_DIR, count=5, rng=rng)}
    assert first & second, "expected some overlap across separate days/pieces to be possible"


def test_select_images_raises_when_count_exceeds_pool(tmp_path):
    niche_dir = tmp_path / "marketing"
    niche_dir.mkdir()
    (niche_dir / "aura-1.png").write_bytes(b"fake")
    (niche_dir / "haircut-1.png").write_bytes(b"fake")

    with pytest.raises(ImageSelectorError, match="only 2 general-rotation image"):
        select_images(niche_dir, count=5)


def test_select_images_raises_when_no_host_images(tmp_path):
    niche_dir = tmp_path / "marketing"
    niche_dir.mkdir()
    (niche_dir / "haircut-1.png").write_bytes(b"fake")
    (niche_dir / "haircut-2.png").write_bytes(b"fake")

    with pytest.raises(ImageSelectorError, match="no host-role"):
        select_images(niche_dir, count=2)


def test_product_role_images_are_listed_but_never_selected(tmp_path):
    niche_dir = tmp_path / "marketing"
    niche_dir.mkdir()
    (niche_dir / "aura-1.png").write_bytes(b"fake")
    (niche_dir / "haircut-1.png").write_bytes(b"fake")
    (niche_dir / "razor-product.png").write_bytes(b"fake")
    (niche_dir / "manifest.yaml").write_text(
        "images:\n"
        "  aura-1.png: {role: host}\n"
        "  haircut-1.png: {role: pool}\n"
        "  razor-product.png: {role: product}\n"
    )

    assets = list_niche_images(niche_dir)
    assert {a.path.name for a in assets} == {"aura-1.png", "haircut-1.png", "razor-product.png"}

    rng = random.Random(0)
    for _ in range(10):
        chosen = select_images(niche_dir, count=2, rng=rng)
        assert "razor-product.png" not in {a.path.name for a in chosen}


def test_manifest_role_overrides_prefix_inference(tmp_path):
    niche_dir = tmp_path / "marketing"
    niche_dir.mkdir()
    (niche_dir / "random-name.png").write_bytes(b"fake")
    (niche_dir / "manifest.yaml").write_text(
        "images:\n  random-name.png: {role: host}\n"
    )

    assets = list_niche_images(niche_dir)
    assert assets[0].role == "host"


def test_missing_niche_directory_raises_clear_error(tmp_path):
    with pytest.raises(ImageSelectorError, match="no such niche marketing directory"):
        list_niche_images(tmp_path / "does-not-exist")
