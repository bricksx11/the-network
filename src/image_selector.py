"""Pick images for one piece of content (one carousel or one video) for a given niche.

Rules (see plan): slide 1 must come from the "host" role (camera-facing/hook-appropriate);
the remaining slides are sampled from the rest of the general pool without replacement, so a
single piece of content never repeats an image. Reuse of the same image across *different*
days/pieces is fine, so this is a pure, stateless function -- no "already used" tracking
anywhere.

Three roles: "host" (slide 1 candidates), "pool" (general rotation, slides 2+), and
"product" (a specific product being held/shown -- e.g. a razor or shears -- locked out of
the default general-rotation pool since it's only appropriate for a dedicated post about
that exact product, not every post). An image explicitly meant to be usable in any post
despite depicting a product (e.g. the app itself) should be tagged "pool", not "product".

Role source of truth is manifest.yaml if the niche has one; otherwise falls back to inferring
from filename prefix ("aura-*" => host, everything else => pool), matching the existing
convention already used in the image library. Prefix inference never infers "product" --
that role must be set explicitly in a manifest, since guessing wrong here would leak a
locked product image into general rotation.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

VALID_ROLES = ("host", "pool", "product")
GENERAL_ROTATION_ROLES = ("host", "pool")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
HOST_PREFIX_DEFAULT = "aura-"


class ImageSelectorError(Exception):
    """Raised when a niche's image pool can't satisfy a selection request."""


@dataclass(frozen=True)
class ImageAsset:
    path: Path
    role: str  # "host" | "pool" | "product"

    def __post_init__(self) -> None:
        if self.role not in VALID_ROLES:
            raise ValueError(f"invalid role {self.role!r} for {self.path}")


def _infer_role_from_filename(filename: str) -> str:
    return "host" if filename.startswith(HOST_PREFIX_DEFAULT) else "pool"


def load_manifest(niche_marketing_dir: Path) -> dict[str, str]:
    """Return {filename: role} from manifest.yaml, or {} if the niche has none yet."""
    manifest_path = niche_marketing_dir / "manifest.yaml"
    if not manifest_path.exists():
        return {}

    data = yaml.safe_load(manifest_path.read_text()) or {}
    images = data.get("images", {})
    roles: dict[str, str] = {}
    for filename, entry in images.items():
        role = (entry or {}).get("role")
        if role not in VALID_ROLES:
            raise ImageSelectorError(
                f"manifest.yaml at {manifest_path} has invalid role {role!r} for {filename!r} "
                f"(must be one of {VALID_ROLES})"
            )
        roles[filename] = role
    return roles


def list_niche_images(niche_marketing_dir: Path) -> list[ImageAsset]:
    """List every image in a niche's marketing/ folder, tagged host/pool.

    manifest.yaml (if present) is authoritative; any image file present on disk but absent
    from the manifest falls back to prefix inference rather than being silently dropped, so
    newly-added images are usable immediately without forcing a manifest edit first.
    """
    if not niche_marketing_dir.is_dir():
        raise ImageSelectorError(f"no such niche marketing directory: {niche_marketing_dir}")

    manifest_roles = load_manifest(niche_marketing_dir)

    assets: list[ImageAsset] = []
    for path in sorted(niche_marketing_dir.iterdir()):
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        role = manifest_roles.get(path.name) or _infer_role_from_filename(path.name)
        assets.append(ImageAsset(path=path, role=role))

    if not assets:
        raise ImageSelectorError(f"no images found in {niche_marketing_dir}")
    return assets


def select_images(
    niche_marketing_dir: Path,
    count: int,
    rng: random.Random | None = None,
    recent_images: set[str] | None = None,
) -> list[ImageAsset]:
    """Select `count` images for one piece of content.

    Slide 1 (index 0) is always a "host" image; the remaining `count - 1` are sampled from
    the rest of the general-rotation pool (host + pool, minus whatever was already picked)
    without replacement. "product"-role images are never selected here -- they're locked to
    dedicated posts about that specific product, not general rotation. Raises
    ImageSelectorError if there's no host image, or not enough general-rotation images to
    fill `count` slots without repeating one within this single piece.

    `recent_images` (paths as strings, from content_history.recent_image_paths) is avoided
    where possible -- e.g. a 19-image library and 10 runs' worth of recent history can still
    leave enough headroom most days, but a small library will eventually run out. Falls back
    to allowing a repeat rather than raising, since re-showing an image after only ~10 posts
    is a much smaller problem than refusing to post at all; logs a warning when that happens
    so it's visible in run output that the library needs a top-up.
    """
    if count < 1:
        raise ValueError("count must be >= 1")

    rng = rng or random.Random()
    recent_images = recent_images or set()
    all_assets = list_niche_images(niche_marketing_dir)
    assets = [a for a in all_assets if a.role in GENERAL_ROTATION_ROLES]

    hosts = [a for a in assets if a.role == "host"]
    if not hosts:
        raise ImageSelectorError(
            f"no host-role images available in {niche_marketing_dir} -- need at least one "
            f"image tagged role: host (or prefixed '{HOST_PREFIX_DEFAULT}') for slide 1"
        )

    if len(assets) < count:
        raise ImageSelectorError(
            f"{niche_marketing_dir} has only {len(assets)} general-rotation image(s), need "
            f"{count} to avoid repeating an image within one piece of content"
        )

    fresh_hosts = [a for a in hosts if str(a.path) not in recent_images]
    if not fresh_hosts:
        logger.warning(
            "%s: every host-role image was used recently -- library needs a top-up, "
            "allowing a repeat for slide 1",
            niche_marketing_dir,
        )
        fresh_hosts = hosts
    slide_one = rng.choice(fresh_hosts)

    remaining_pool = [a for a in assets if a.path != slide_one.path]
    fresh_pool = [a for a in remaining_pool if str(a.path) not in recent_images]
    if len(fresh_pool) < count - 1:
        logger.warning(
            "%s: not enough unused images left (%d fresh, need %d) -- library needs a "
            "top-up, allowing repeats",
            niche_marketing_dir,
            len(fresh_pool),
            count - 1,
        )
        fresh_pool = remaining_pool
    rest = rng.sample(fresh_pool, count - 1)

    return [slide_one, *rest]
