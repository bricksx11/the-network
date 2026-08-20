import json
from datetime import datetime, timedelta, timezone

from src.content_history import (
    HistoryEntry,
    is_too_similar,
    load_recent,
    recent_image_paths,
    shape_usage_counts,
)


def _write_log(logs_dir, niche, timestamp, **fields):
    logs_dir.mkdir(parents=True, exist_ok=True)
    ts_slug = timestamp.replace(":", "").replace("-", "")
    path = logs_dir / f"{niche}-{ts_slug}.json"
    path.write_text(json.dumps({"niche": niche, "timestamp": timestamp, **fields}))
    return path


def test_load_recent_reads_matching_niche_within_window(tmp_path):
    now = datetime.now(timezone.utc)
    _write_log(tmp_path, "Barber", now.isoformat(), shape="money_reveal", hook="hook one")
    _write_log(tmp_path, "DogGroomer", now.isoformat(), shape="checklist", hook="unrelated niche")

    entries = load_recent("Barber", days=60, logs_dir=tmp_path)

    assert len(entries) == 1
    assert entries[0].hook == "hook one"


def test_load_recent_skips_entries_older_than_cutoff(tmp_path):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=90)
    _write_log(tmp_path, "Barber", old.isoformat(), shape="money_reveal", hook="stale hook")
    _write_log(tmp_path, "Barber", now.isoformat(), shape="checklist", hook="fresh hook")

    entries = load_recent("Barber", days=60, logs_dir=tmp_path)

    assert [e.hook for e in entries] == ["fresh hook"]


def test_load_recent_skips_malformed_json(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Barber-20260101T000000Z.json").write_text("{not valid json")
    now = datetime.now(timezone.utc)
    _write_log(tmp_path, "Barber", now.isoformat(), shape="money_reveal", hook="good hook")

    entries = load_recent("Barber", days=60, logs_dir=tmp_path)

    assert [e.hook for e in entries] == ["good hook"]


def test_load_recent_returns_empty_when_dir_missing(tmp_path):
    assert load_recent("Barber", logs_dir=tmp_path / "does-not-exist") == []


def test_load_recent_defaults_missing_hook_and_topic_to_none(tmp_path):
    now = datetime.now(timezone.utc)
    _write_log(tmp_path, "Barber", now.isoformat(), shape="money_reveal")  # pre-dates hook/topic logging

    entries = load_recent("Barber", days=60, logs_dir=tmp_path)

    assert entries[0].hook is None
    assert entries[0].topic_summary is None


def _entry(**overrides):
    defaults = dict(niche="Barber", timestamp="2026-08-01T00:00:00+00:00", shape="money_reveal", hook=None, topic_summary=None)
    defaults.update(overrides)
    return HistoryEntry(**defaults)


def test_is_too_similar_true_on_hook_overlap():
    history = [_entry(hook="How I hit a 6-figure month as a barber")]
    assert is_too_similar("How I hit a 6-figure month as a barber owner", "different topic", history) is True


def test_is_too_similar_true_on_topic_overlap():
    history = [_entry(topic_summary="lost revenue from missed calls during cuts")]
    assert is_too_similar("a totally different hook", "lost revenue from missed calls during cuts", history) is True


def test_is_too_similar_false_when_genuinely_different():
    history = [_entry(hook="4 signs your diary is leaking money", topic_summary="diary leak checklist")]
    assert is_too_similar("A shop in Leeds lost three cuts to no-shows", "story about a specific shop", history) is False


def test_is_too_similar_ignores_entries_with_no_hook_or_topic():
    history = [_entry(hook=None, topic_summary=None)]
    assert is_too_similar("any hook", "any topic", history) is False


def test_shape_usage_counts_tallies_by_shape():
    history = [_entry(shape="money_reveal"), _entry(shape="money_reveal"), _entry(shape="checklist")]
    assert shape_usage_counts(history) == {"money_reveal": 2, "checklist": 1}


def test_shape_usage_counts_ignores_missing_shape():
    history = [_entry(shape=None), _entry(shape="checklist")]
    assert shape_usage_counts(history) == {"checklist": 1}


def test_recent_image_paths_only_looks_at_tail():
    history = [
        _entry(images_used=["old-1.png"]),
        *[_entry(images_used=[f"mid-{i}.png"]) for i in range(15)],
        _entry(images_used=["recent-1.png"]),
    ]
    used = recent_image_paths(history, within_last=10)
    assert "old-1.png" not in used
    assert "recent-1.png" in used
