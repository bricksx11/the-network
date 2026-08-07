"""Validate that a day's script has real backing before it's allowed to render/publish.

Two layers, per the plan:

1. Hard gate (deterministic, zero external dependency): the script must match one of the
   proven content shapes validated by hand this session (money_reveal, mistakes_listicle,
   before_after, gear_list) and contain the beats that shape requires. Anything that doesn't
   fit is rejected outright -- this is the real, reliable check.

2. Soft enrichment (best-effort, optional): pulls directional trend signal for the niche's
   seed keywords via pytrends (unofficial Google Trends client, free, no API key -- it scrapes
   an undocumented endpoint and is known to be flaky/rate-limited). This must NEVER block a
   post from generating; any failure here is swallowed and simply results in no trend data,
   not a gate rejection.

Both the matched shape and any trend keywords used are returned in the result so the caller
(orchestrator) can write them into the per-run audit log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class ResearchGateError(Exception):
    """Raised when a script fails the hard gate -- caller should not render/publish it."""


@dataclass(frozen=True)
class ShapeRequirements:
    name: str
    min_beats: int
    max_beats: int
    requires_reveal: bool
    requires_cta: bool
    description: str


# The proven formats validated by hand this session. A script that doesn't map to one of
# these is rejected -- this list only grows by deliberately validating a new format the same
# way these were (build it, watch it perform, then formalize it here), not by generator whim.
PROVEN_SHAPES: dict[str, ShapeRequirements] = {
    "money_reveal": ShapeRequirements(
        name="money_reveal",
        min_beats=2,
        max_beats=2,
        requires_reveal=True,
        requires_cta=True,
        description=(
            "Hook (concrete result, e.g. income milestone) -> 2 relatable non-software "
            "changes -> vague missed-calls setup folded into the reveal -> Bizyr named "
            "with a 'why' -> comment-bait CTA."
        ),
    ),
    "mistakes_listicle": ShapeRequirements(
        name="mistakes_listicle",
        min_beats=2,
        max_beats=3,
        requires_reveal=True,
        requires_cta=True,
        description=(
            "Hook ('mistakes I made') -> 2-3 real mistakes -> final beat is the mistake "
            "tied to missed calls, resolved by naming Bizyr -> CTA."
        ),
    ),
    "before_after": ShapeRequirements(
        name="before_after",
        min_beats=2,
        max_beats=2,
        requires_reveal=True,
        requires_cta=True,
        description="Hook (before vs after framing) -> exactly 2 beats (before, after) -> reveal -> CTA.",
    ),
    "gear_list": ShapeRequirements(
        name="gear_list",
        min_beats=3,
        max_beats=3,
        requires_reveal=True,
        requires_cta=True,
        description=(
            "Hook ('things every X needs') -> 3 real physical gear picks (specific brands/"
            "models, not generic advice) -> Bizyr as the 4th item, framed as gear not a pitch -> CTA."
        ),
    ),
}


@dataclass(frozen=True)
class Script:
    """Minimal contract expected from script_provider.py's output."""

    shape: str
    hook: str
    beats: list[str]
    reveal: Optional[str] = None
    cta: str = ""
    platform_cta_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TrendSignal:
    keyword: str
    rising_queries: list[str]


@dataclass(frozen=True)
class GateResult:
    shape: str
    passed: bool
    reason: Optional[str]
    trend_signal: Optional[TrendSignal]


def validate_shape(script: Script) -> None:
    """Hard gate. Raises ResearchGateError with a specific reason if the script doesn't
    match one of PROVEN_SHAPES. Returns None (silently) if it passes.
    """
    requirements = PROVEN_SHAPES.get(script.shape)
    if requirements is None:
        known = ", ".join(sorted(PROVEN_SHAPES))
        raise ResearchGateError(
            f"unknown shape {script.shape!r} -- must be one of the proven formats: {known}"
        )

    if not script.hook.strip():
        raise ResearchGateError(f"[{script.shape}] missing hook")

    beat_count = len(script.beats)
    if not (requirements.min_beats <= beat_count <= requirements.max_beats):
        raise ResearchGateError(
            f"[{script.shape}] expected {requirements.min_beats}-{requirements.max_beats} "
            f"beats, got {beat_count}"
        )

    if requirements.requires_reveal and not (script.reveal or "").strip():
        raise ResearchGateError(f"[{script.shape}] missing required Bizyr reveal beat")

    if requirements.requires_cta and not script.cta.strip():
        raise ResearchGateError(f"[{script.shape}] missing required CTA")


def try_fetch_trend_signal(seed_keyword: str, geo: str = "") -> Optional[TrendSignal]:
    """Best-effort trend enrichment. Returns None on ANY failure -- network issues, pytrends
    not installed, rate limiting, schema changes upstream, all of it. This function must
    never raise; a missing signal just means the script generator gets no directional
    flavor for today, not that the pipeline stops.
    """
    try:
        from pytrends.request import TrendReq  # optional dependency, imported lazily
    except ImportError:
        return None

    try:
        pytrends = TrendReq(hl="en-US", tz=0)
        pytrends.build_payload([seed_keyword], timeframe="now 7-d", geo=geo)
        related = pytrends.related_queries()
        rising_df = (related.get(seed_keyword) or {}).get("rising")
        if rising_df is None or rising_df.empty:
            return TrendSignal(keyword=seed_keyword, rising_queries=[])
        rising_queries = rising_df["query"].head(5).tolist()
        return TrendSignal(keyword=seed_keyword, rising_queries=rising_queries)
    except Exception:
        # Deliberately broad: pytrends wraps an unofficial, undocumented endpoint and can
        # fail in ways that don't have a stable exception type to catch narrowly.
        return None


def run_research_gate(script: Script, trend_seed_keyword: Optional[str] = None) -> GateResult:
    """Run the hard gate, then best-effort trend enrichment. Returns a GateResult for the
    caller to log, or raises ResearchGateError if the hard gate fails (caller should not
    proceed to render/publish in that case).
    """
    validate_shape(script)  # raises on failure, nothing to catch here

    trend_signal = try_fetch_trend_signal(trend_seed_keyword) if trend_seed_keyword else None

    return GateResult(
        shape=script.shape,
        passed=True,
        reason=None,
        trend_signal=trend_signal,
    )
