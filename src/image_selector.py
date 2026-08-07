"""Pick images for one piece of content (one carousel or one video) for a given niche.

Rules (see plan): slide 1 must come from the "host" role (camera-facing/hook-appropriate);
the remaining slides are sampled from the rest of the pool without replacement, so a single
piece of content never repeats an image. Reuse of the same image across *different* days/pieces
is fine, so this is a pure, stateless function -- no "already used" tracking anywhere.

Role source of truth is manifest.yaml if the niche has one; otherwise falls back to inferring
from filename prefix ("aura-*" => host, everything else => pool), matching the existing
convention already used in the image library.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import yaml

VALID_ROLES = ("host", "pool")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
HOST_PREFIX_DEFAULT = "aura-"


class ImageSelectorError(Exception):
    """Raised when a niche's image pool can't satisfy a selection request."""


@dataclass(frozen=True)
class ImageAsset:
    path: Path
    role: str  # "host" | "pool"

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
) -> list[ImageAsset]:
    """Select `count` images for one piece of content.

    Slide 1 (index 0) is always a "host" image; the remaining `count - 1` are sampled from
    the rest of the pool (host + pool, minus whatever was already picked) without replacement.
    Raises ImageSelectorError if there's no host image, or not enough total images to fill
    `count` slots without repeating one within this single piece.
    """
    if count < 1:
        raise ValueError("count must be >= 1")

    rng = rng or random.Random()
    assets = list_niche_images(niche_marketing_dir)

    hosts = [a for a in assets if a.role == "host"]
    if not hosts:
        raise ImageSelectorError(
            f"no host-role images available in {niche_marketing_dir} -- need at least one "
            f"image tagged role: host (or prefixed '{HOST_PREFIX_DEFAULT}') for slide 1"
        )

    if len(assets) < count:
        raise ImageSelectorError(
            f"{niche_marketing_dir} has only {len(assets)} image(s), need {count} to avoid "
            f"repeating an image within one piece of content"
        )

    slide_one = rng.choice(hosts)
    remaining_pool = [a for a in assets if a.path != slide_one.path]
    rest = rng.sample(remaining_pool, count - 1)

    return [slide_one, *rest]
