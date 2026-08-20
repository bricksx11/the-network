"""Builds the actual per-platform caption/description, replacing the single inline
`f"{hook}\\n\\n{cta}"` that orchestrator.py::publish_niche used to build once and reuse
everywhere. Confirmed via research this was a real gap -- no hashtag/SEO logic existed at
all before this module.

Platform behavior this is built against (2025-2026, see the niche content-intelligence
configs' platform_notes for the sourced specifics):
- Instagram captions are Google-indexed since 10 July 2025 -- phrase like a real search
  query, not keyword-stuffed.
- TikTok indexes spoken audio + on-screen text + caption together for search -- the keyword
  needs to appear in the caption text too, not just the video.
- 3-5 hashtags, not 30 -- confirmed via the barber research's technical-spec findings.
- Facebook: format/caption length barely moves engagement (Buffer benchmark data) -- reuses
  the Instagram-shape caption without hashtags (Facebook hashtags don't drive discovery the
  way IG/TikTok's do).
"""

from __future__ import annotations

from src.research_gate import Script

MAX_HASHTAGS = 5


def _campaign_cta(
    script: Script, campaign: dict, platform: str | None = None, cta_override: str | None = None
) -> str:
    if cta_override:
        return cta_override
    override = script.platform_cta_overrides.get(platform) if platform else None
    if override:
        return override
    return campaign.get("cta_text") or script.cta


def build_hashtags(content_intelligence: dict, max_count: int = MAX_HASHTAGS) -> list[str]:
    """Pulls hashtags from the niche's "use" terminology list -- real trade terms the
    audience actually searches/self-identifies with, not generic broad tags (which research
    found to be saturated/wrong-audience for a B2B account anyway).
    """
    terms = content_intelligence.get("terminology", {}).get("use", [])
    tags = []
    for term in terms:
        tag = "#" + "".join(ch for ch in term.title() if ch.isalnum())
        if tag != "#" and tag not in tags:
            tags.append(tag)
        if len(tags) >= max_count:
            break
    return tags


def build_caption(
    script: Script,
    content_intelligence: dict,
    campaign: dict,
    platform: str,
    cta_override: str | None = None,
) -> str:
    """One caption per platform, not one caption reused everywhere.

    cta_override takes priority over everything else (script.platform_cta_overrides,
    campaign.yaml's default) -- used by orchestrator.py for niche_config's per-niche YouTube
    cta_override, which predates campaign.yaml and is real per-niche config, not a campaign-
    wide default.
    """
    cta = _campaign_cta(script, campaign, platform, cta_override)

    if platform in ("instagram", "facebook"):
        lines = [script.hook]
        if script.reveal:
            lines += ["", script.reveal]
        lines += ["", cta]
        if platform == "instagram":
            hashtags = build_hashtags(content_intelligence)
            if hashtags:
                lines += ["", " ".join(hashtags)]
        return "\n".join(lines)

    if platform == "tiktok":
        # Shorter, more spoken-style -- the keyword needs to land in text since TikTok
        # indexes caption + on-screen text + spoken audio together for search.
        hashtags = build_hashtags(content_intelligence, max_count=3)
        parts = [script.hook, cta]
        if hashtags:
            parts.append(" ".join(hashtags))
        return " | ".join(parts)

    if platform == "youtube":
        # Description, not title (title stays script.hook, set by the caller) -- longer form
        # is fine/expected here, no hashtag convention on Shorts descriptions the way IG/TikTok have.
        lines = [script.reveal or "", "", cta]
        return "\n".join(lines)

    # Unknown platform: safe fallback matching the old behavior.
    return f"{script.hook}\n\n{cta}"
