"""Reads the existing per-run audit logs (logs/<Niche>-<timestamp>.json, already committed
by CI -- see _pipeline.yml's "Commit run log" step) back into the pipeline as real content
history, so the generator can avoid repeating hooks/topics/shapes/images. Deliberately
extends the existing log format rather than introducing a new storage system: orchestrator.py
already writes one JSON file per run, this module just reads a richer version of it back.

No embedding API, no database -- a simple normalized keyword/phrase overlap check is enough
at this scale (a few posts a day, checked against the last ~60 days).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "logs"

# Below this fraction of shared significant words, two hooks/topics are considered
# genuinely different. Tuned conservatively (catch obvious repeats, don't false-positive on
# every post that happens to mention "clients" or "booking").
SIMILARITY_THRESHOLD = 0.6

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with", "your",
    "you", "is", "are", "it", "this", "that", "i", "my", "me", "so", "as", "be", "not",
}


@dataclass(frozen=True)
class HistoryEntry:
    niche: str
    timestamp: str
    shape: str | None
    hook: str | None
    topic_summary: str | None
    images_used: list[str] = field(default_factory=list)


def load_recent(niche: str, days: int = 60, logs_dir: Path = LOGS_DIR) -> list[HistoryEntry]:
    """Read every logs/<niche>-*.json run record from the last `days` days, oldest first.
    Missing hook/topic_summary fields (older logs, before this module existed) are just
    None -- callers treat that as "nothing to compare against" for that entry, not an error.
    """
    if not logs_dir.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries: list[HistoryEntry] = []

    for path in sorted(logs_dir.glob(f"{niche}-*.json")):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue  # a malformed/partial log shouldn't break the whole pipeline

        ts_raw = data.get("timestamp")
        try:
            ts = datetime.fromisoformat(ts_raw) if ts_raw else None
        except ValueError:
            ts = None
        if ts is not None and ts < cutoff:
            continue

        entries.append(
            HistoryEntry(
                niche=data.get("niche", niche),
                timestamp=ts_raw or "",
                shape=data.get("shape"),
                hook=data.get("hook"),
                topic_summary=data.get("topic_summary"),
                images_used=data.get("images_used", []),
            )
        )

    return entries


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-z']+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _overlap_ratio(a: str, b: str) -> float:
    words_a, words_b = _significant_words(a), _significant_words(b)
    if not words_a or not words_b:
        return 0.0
    shared = words_a & words_b
    return len(shared) / min(len(words_a), len(words_b))


def is_too_similar(
    candidate_hook: str,
    candidate_topic: str,
    history: list[HistoryEntry],
    threshold: float = SIMILARITY_THRESHOLD,
) -> bool:
    """True if candidate_hook/candidate_topic overlaps too heavily with anything in history.
    Checked against hook and topic_summary independently -- either one tripping the
    threshold counts as "too similar", since a reused hook with a new topic (or vice versa)
    is still a repeat in the way that matters to the audience.
    """
    for entry in history:
        if entry.hook and _overlap_ratio(candidate_hook, entry.hook) >= threshold:
            return True
        if entry.topic_summary and _overlap_ratio(candidate_topic, entry.topic_summary) >= threshold:
            return True
    return False


def shape_usage_counts(history: list[HistoryEntry]) -> dict[str, int]:
    """How many times each shape was used recently -- feeds shape-selection weighting so the
    generator leans away from whatever's been overused, rather than picking uniformly at
    random (which would still let one shape dominate by chance over a run of days).
    """
    counts: dict[str, int] = {}
    for entry in history:
        if entry.shape:
            counts[entry.shape] = counts.get(entry.shape, 0) + 1
    return counts


def recent_image_paths(history: list[HistoryEntry], within_last: int = 10) -> set[str]:
    """Image paths used in the most recent `within_last` runs -- feeds image_selector's dedup
    param. Only looks at the tail, not the full window, since a small library (14-19 images)
    inevitably needs to cycle back eventually -- avoiding the last ~10 runs' worth is enough
    to stop back-to-back repeats without starving selection entirely.
    """
    used: set[str] = set()
    for entry in history[-within_last:]:
        used.update(entry.images_used)
    return used
