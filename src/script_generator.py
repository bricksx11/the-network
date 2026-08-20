"""Real per-niche, per-platform content generation -- replaces script_provider.py's old
hardcoded stub (`return _STUB_SCRIPT` regardless of niche, literally containing the text "As
a barber" on every DogGroomer post too). This was the entire root cause of the repetition
problem: everything downstream (image selection, rendering, publishing) was already generic
and niche-aware, only this one function wasn't.

Calls Gemini directly via its REST API (same GEMINI_URL pattern bizyr-backend uses in
production) -- no new SDK dependency, `requests` is already in requirements.txt. Cost is
negligible (a handful of calls/day; bizyr-backend's own measured real-world cost for
similarly-sized structured-JSON calls is ~$0.0015/message) but this repo needs its own
GEMINI_API_KEY secret, which it doesn't have yet.

Generation flow: pick a shape (weighted away from recently-overused ones) -> build a prompt
from the niche's content-intelligence config + campaign CTA + recent hooks/topics to avoid
-> request schema-constrained JSON matching Script's fields -> validate through the existing
research_gate hard gate -> reject/regenerate once if it's still too similar to recent
history, then fall back to a different shape rather than looping forever.
"""

from __future__ import annotations

import json
import os
import random
import time

import requests

from src.content_history import HistoryEntry, is_too_similar, shape_usage_counts
from src.research_gate import PROVEN_SHAPES, Script, validate_shape

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
REQUEST_TIMEOUT_S = 30
MAX_REGENERATE_ATTEMPTS = 3  # original shape -> same-shape retry with feedback -> different-
# shape attempt. (Not 2: with only 2 attempts, the "fall back to a different shape" branch
# reassigns `shape` on the loop's last iteration only for the loop to exit right after --
# dead code that never actually got a third attempt. 3 matches what the docstring below
# actually describes.)
MAX_TRANSIENT_RETRIES = 3  # separate from MAX_REGENERATE_ATTEMPTS -- a 503 isn't a content
# problem, retrying the same prompt is correct (unlike a "too similar" rejection, which needs
# a different shape/prompt). Confirmed for real: gemini-flash-latest returned a genuine,
# repeated 503 "high demand" during verification while gemini-flash-lite-latest was healthy
# at the same moment -- a scheduled twice-daily run must not die outright on that.
TRANSIENT_RETRY_BACKOFF_S = 2
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

_SCRIPT_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "hook": {"type": "STRING"},
        "beats": {"type": "ARRAY", "items": {"type": "STRING"}},
        "reveal": {"type": "STRING"},
        "cta": {"type": "STRING"},
        "topic_summary": {
            "type": "STRING",
            "description": "One short phrase naming the specific topic/angle, for dedup tracking -- not shown to the audience.",
        },
    },
    "required": ["hook", "beats", "reveal", "cta", "topic_summary"],
}


class ScriptGenerationError(Exception):
    """Raised when generation can't produce a valid, sufficiently-original script.
    The caller should not fall back to publishing something stale -- matches the codebase's
    existing "refuse to run" philosophy (e.g. null platform IDs already skip rather than
    error-swallow).
    """


def _choose_shape(recent_history: list[HistoryEntry]) -> str:
    """Weighted random choice, biased away from whatever's been used most recently -- not
    ML, just enough to stop one shape (e.g. money_reveal) from dominating by chance the way
    it did before (it was, in fact, the *only* shape ever exercised).
    """
    usage = shape_usage_counts(recent_history)
    shapes = list(PROVEN_SHAPES.keys())
    # Inverse-frequency weighting: unused/rarely-used shapes get picked far more often than
    # heavily-used ones, without making a heavily-used shape literally impossible to repeat.
    weights = [1.0 / (1 + usage.get(name, 0)) for name in shapes]
    return random.choices(shapes, weights=weights, k=1)[0]


def _build_prompt(
    niche: str,
    platform: str,
    shape: str,
    content_intelligence: dict,
    campaign: dict,
    recent_history: list[HistoryEntry],
    avoid_note: str | None = None,
) -> str:
    requirements = PROVEN_SHAPES[shape]
    recent_hooks = [e.hook for e in recent_history[-15:] if e.hook]
    recent_topics = [e.topic_summary for e in recent_history[-15:] if e.topic_summary]

    parts = [
        f"You are writing a single social media carousel/video script for {content_intelligence.get('audience_identity', niche)}.",
        f"Positioning: {content_intelligence.get('positioning', '').strip()}",
        "",
        f"Content shape to use: {shape} -- {requirements.description}",
        f"You must produce exactly {requirements.min_beats}-{requirements.max_beats} beats.",
        "",
        "Real terminology this audience actually uses (use naturally, don't force all of it in):",
        ", ".join(content_intelligence.get("terminology", {}).get("use", [])),
        "",
        "Never use these words/phrases -- they read as generic AI/corporate copy to this audience:",
        ", ".join(content_intelligence.get("avoid_words", [])),
        "",
        "Real pain points this audience actually has (pick ONE angle, don't try to cover all of them):",
        "\n".join(f"- {p}" for p in content_intelligence.get("pain_points", [])),
        "",
        "Real, sourced numbers you may draw from if relevant (do not invent new statistics):",
        "\n".join(f"- {n}" for n in content_intelligence.get("real_numbers", [])),
        "",
        f"Platform: {platform}. {content_intelligence.get('platform_notes', {}).get(platform, '')}",
        "",
        f"The reveal beat must naturally introduce Bizyr (an AI receptionist/booking tool) as the "
        f"solution to the pain point raised -- not a hard sell, a natural 'here's what actually fixed it'.",
        f"The CTA should work with this campaign framing: {campaign.get('cta_text', '')}",
    ]

    if recent_hooks:
        parts += [
            "",
            "Hooks already used recently -- your new hook must NOT resemble any of these "
            "(different topic, different angle, different wording):",
            "\n".join(f"- {h}" for h in recent_hooks),
        ]
    if recent_topics:
        parts += [
            "",
            "Topics already covered recently -- pick a genuinely different angle:",
            "\n".join(f"- {t}" for t in recent_topics),
        ]
    if avoid_note:
        parts += ["", f"IMPORTANT: your previous attempt was rejected for this reason: {avoid_note}. Try a materially different angle."]

    parts += [
        "",
        "Return strict JSON matching the schema. hook = the opening line (slide 1 / video open, "
        "must earn attention on its own). beats = the supporting points. reveal = the beat that "
        "introduces Bizyr. cta = the call to action. topic_summary = a short internal label for "
        "what this post is actually about (not shown to the audience).",
    ]
    return "\n".join(parts)


def _call_gemini(prompt: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ScriptGenerationError("GEMINI_API_KEY is not set -- cannot generate real content")

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCRIPT_RESPONSE_SCHEMA,
        },
    }

    response = None
    for attempt in range(MAX_TRANSIENT_RETRIES):
        response = requests.post(
            f"{GEMINI_URL}?key={api_key}",
            json=body,
            timeout=REQUEST_TIMEOUT_S,
        )
        if response.ok or response.status_code not in TRANSIENT_STATUS_CODES:
            break
        if attempt < MAX_TRANSIENT_RETRIES - 1:
            time.sleep(TRANSIENT_RETRY_BACKOFF_S * (attempt + 1))

    if not response.ok:
        raise ScriptGenerationError(f"Gemini request failed ({response.status_code}): {response.text[:500]}")

    payload = response.json()
    try:
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise ScriptGenerationError(f"unexpected Gemini response shape: {e}: {payload}") from e


def generate_script(
    niche: str,
    platform: str,
    content_intelligence: dict,
    campaign: dict,
    recent_history: list[HistoryEntry],
) -> tuple[Script, str]:
    """Generate one genuinely new Script for this niche/platform, checked against real
    content history so it doesn't repeat a recent hook/topic. Raises ScriptGenerationError
    (not a silent fallback) if it can't produce something sufficiently original within
    MAX_REGENERATE_ATTEMPTS -- the caller should stop the run rather than publish something
    stale, matching the codebase's existing refuse-to-run philosophy.

    Returns (script, topic_summary) -- topic_summary is an internal dedup label, not part of
    Script itself (Script is a frozen dataclass shared with research_gate's validation and
    deliberately kept to its existing minimal contract; the caller logs topic_summary
    separately into the run record for future dedup checks).
    """
    shape = _choose_shape(recent_history)
    avoid_note: str | None = None

    for attempt in range(MAX_REGENERATE_ATTEMPTS):
        prompt = _build_prompt(niche, platform, shape, content_intelligence, campaign, recent_history, avoid_note)
        data = _call_gemini(prompt)

        script = Script(
            shape=shape,
            hook=data["hook"],
            beats=data["beats"],
            reveal=data["reveal"],
            cta=data["cta"],
        )
        topic_summary = data.get("topic_summary", "")

        validate_shape(script)  # raises ResearchGateError if malformed -- let it propagate

        if not is_too_similar(script.hook, topic_summary, recent_history):
            return script, topic_summary

        avoid_note = f"hook/topic too similar to recent content (hook: {script.hook!r})"
        if attempt == 0:
            # One retry with the same shape and explicit feedback before giving up on it.
            continue
        # Still too similar on the retry -- try a different shape entirely rather than
        # looping indefinitely against the same one.
        remaining_shapes = [s for s in PROVEN_SHAPES if s != shape]
        shape = random.choice(remaining_shapes) if remaining_shapes else shape

    raise ScriptGenerationError(
        f"could not generate sufficiently original content for {niche}/{platform} after "
        f"{MAX_REGENERATE_ATTEMPTS} attempts -- stopping rather than publishing a repeat"
    )
