import json

import pytest

from src.content_history import HistoryEntry
from src.research_gate import PROVEN_SHAPES, ResearchGateError
from src.script_generator import (
    MAX_REGENERATE_ATTEMPTS,
    MAX_TRANSIENT_RETRIES,
    ScriptGenerationError,
    _call_gemini,
    _choose_shape,
    generate_script,
)

CONTENT_INTELLIGENCE = {
    "positioning": "Diary defence, not lead gen.",
    "audience_identity": "UK barber",
    "terminology": {"use": ["chair rent", "the diary"], "avoid": []},
    "avoid_words": [],
    "pain_points": ["the phone rings mid-fade"],
    "real_numbers": ["chair rent ~£170/wk"],
    "platform_notes": {"instagram": "carousels for the argument"},
}
CAMPAIGN = {"cta_text": "Join the waitlist -- link in bio"}


def _fake_response(status_code=200, ok=True, json_body=None, text=""):
    mock = type("FakeResponse", (), {})()
    mock.status_code = status_code
    mock.ok = ok
    mock.text = text
    mock.json = lambda: json_body
    return mock


def _gemini_payload(hook, beats, reveal, cta, topic_summary="a topic"):
    return _fake_response(
        json_body={
            "candidates": [
                {"content": {"parts": [{"text": json.dumps({
                    "hook": hook, "beats": beats, "reveal": reveal, "cta": cta, "topic_summary": topic_summary,
                })}]}}
            ]
        }
    )


# --- _choose_shape -----------------------------------------------------------------------

def test_choose_shape_biases_away_from_overused_shape():
    history = [HistoryEntry(niche="Barber", timestamp="t", shape="money_reveal", hook=None, topic_summary=None)] * 20
    counts = {}
    for _ in range(300):
        chosen = _choose_shape(history)
        counts[chosen] = counts.get(chosen, 0) + 1
    # money_reveal was used 20 times recently -- it should be picked far less than an
    # untouched shape's fair share, not zero (still possible), just clearly biased down.
    untouched_avg = sum(v for k, v in counts.items() if k != "money_reveal") / max(
        1, len([k for k in counts if k != "money_reveal"])
    )
    assert counts.get("money_reveal", 0) < untouched_avg


def test_choose_shape_returns_a_known_shape():
    assert _choose_shape([]) in PROVEN_SHAPES


# --- _call_gemini --------------------------------------------------------------------------

def test_call_gemini_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ScriptGenerationError, match="GEMINI_API_KEY"):
        _call_gemini("prompt")


def test_call_gemini_retries_transient_errors_then_succeeds(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mocker.patch("src.script_generator.time.sleep")
    responses = [
        _fake_response(status_code=503, ok=False, text="overloaded"),
        _fake_response(status_code=503, ok=False, text="overloaded"),
        _gemini_payload("hook", ["b1", "b2"], "reveal", "cta"),
    ]
    mock_post = mocker.patch("src.script_generator.requests.post", side_effect=responses)

    result = _call_gemini("prompt")

    assert mock_post.call_count == 3
    assert result["hook"] == "hook"


def test_call_gemini_raises_after_exhausting_transient_retries(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mocker.patch("src.script_generator.time.sleep")
    mock_post = mocker.patch(
        "src.script_generator.requests.post",
        return_value=_fake_response(status_code=503, ok=False, text="overloaded"),
    )

    with pytest.raises(ScriptGenerationError, match="503"):
        _call_gemini("prompt")

    assert mock_post.call_count == MAX_TRANSIENT_RETRIES


def test_call_gemini_does_not_retry_non_transient_errors(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mock_post = mocker.patch(
        "src.script_generator.requests.post",
        return_value=_fake_response(status_code=400, ok=False, text="bad request"),
    )

    with pytest.raises(ScriptGenerationError, match="400"):
        _call_gemini("prompt")

    assert mock_post.call_count == 1


# --- generate_script -----------------------------------------------------------------------

def test_generate_script_returns_first_valid_attempt(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mocker.patch("src.script_generator._choose_shape", return_value="money_reveal")
    mock_call = mocker.patch(
        "src.script_generator._call_gemini",
        return_value={"hook": "fresh hook", "beats": ["b1", "b2"], "reveal": "reveal", "cta": "cta", "topic_summary": "topic"},
    )

    script, topic_summary = generate_script("Barber", "instagram", CONTENT_INTELLIGENCE, CAMPAIGN, [])

    assert mock_call.call_count == 1
    assert script.shape == "money_reveal"
    assert script.hook == "fresh hook"
    assert topic_summary == "topic"


def test_generate_script_regenerates_when_too_similar_then_succeeds(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mocker.patch("src.script_generator._choose_shape", return_value="money_reveal")
    history = [HistoryEntry(niche="Barber", timestamp="t", shape="money_reveal", hook="a repeated hook", topic_summary="old topic")]
    mock_call = mocker.patch(
        "src.script_generator._call_gemini",
        side_effect=[
            {"hook": "a repeated hook", "beats": ["b1", "b2"], "reveal": "reveal", "cta": "cta", "topic_summary": "new topic"},
            {"hook": "a genuinely new hook", "beats": ["b1", "b2"], "reveal": "reveal", "cta": "cta", "topic_summary": "new topic"},
        ],
    )

    script, topic_summary = generate_script("Barber", "instagram", CONTENT_INTELLIGENCE, CAMPAIGN, history)

    assert mock_call.call_count == 2
    assert script.hook == "a genuinely new hook"


def test_generate_script_raises_after_exhausting_regenerate_attempts(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mocker.patch("src.script_generator._choose_shape", return_value="money_reveal")
    # On the final attempt generate_script switches to a different shape (random.choice over
    # remaining_shapes) -- pin it to another exactly-2-beat shape so the mocked 2-beat data
    # stays valid regardless of which shape it lands on, keeping this test about the
    # "still too similar after every attempt" path, not shape-beat-count coincidences.
    mocker.patch("src.script_generator.random.choice", return_value="myth_vs_reality")
    history = [HistoryEntry(niche="Barber", timestamp="t", shape="money_reveal", hook="a repeated hook", topic_summary="old topic")]
    mock_call = mocker.patch(
        "src.script_generator._call_gemini",
        return_value={"hook": "a repeated hook", "beats": ["b1", "b2"], "reveal": "reveal", "cta": "cta", "topic_summary": "old topic"},
    )

    with pytest.raises(ScriptGenerationError, match="could not generate sufficiently original content"):
        generate_script("Barber", "instagram", CONTENT_INTELLIGENCE, CAMPAIGN, history)

    assert mock_call.call_count == MAX_REGENERATE_ATTEMPTS


def test_generate_script_propagates_shape_validation_failure(mocker, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    mocker.patch("src.script_generator._choose_shape", return_value="money_reveal")  # requires exactly 2 beats
    mocker.patch(
        "src.script_generator._call_gemini",
        return_value={"hook": "hook", "beats": ["only one beat"], "reveal": "reveal", "cta": "cta", "topic_summary": "t"},
    )

    with pytest.raises(ResearchGateError):
        generate_script("Barber", "instagram", CONTENT_INTELLIGENCE, CAMPAIGN, [])
