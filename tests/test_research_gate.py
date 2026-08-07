import pytest

from src.research_gate import (
    PROVEN_SHAPES,
    ResearchGateError,
    Script,
    run_research_gate,
    try_fetch_trend_signal,
    validate_shape,
)


def make_script(**overrides) -> Script:
    defaults = dict(
        shape="money_reveal",
        hook="I hit a 6-figure month as a barber.",
        beats=["Dropped low-paying clients.", "Raised my rates."],
        reveal="I started using an app to catch every call. Why? Missed calls are missed clients.",
        cta="Comment 'CALLS' and I'll send you the app.",
    )
    defaults.update(overrides)
    return Script(**defaults)


def test_valid_money_reveal_script_passes():
    validate_shape(make_script())  # should not raise


@pytest.mark.parametrize("shape", list(PROVEN_SHAPES))
def test_every_proven_shape_has_a_passing_example(shape):
    requirements = PROVEN_SHAPES[shape]
    script = make_script(
        shape=shape,
        beats=["beat"] * requirements.min_beats,
    )
    validate_shape(script)  # should not raise for any registered shape


def test_unknown_shape_is_rejected():
    script = make_script(shape="ai_slop_freestyle")
    with pytest.raises(ResearchGateError, match="unknown shape"):
        validate_shape(script)


def test_missing_hook_is_rejected():
    script = make_script(hook="   ")
    with pytest.raises(ResearchGateError, match="missing hook"):
        validate_shape(script)


def test_wrong_beat_count_is_rejected():
    script = make_script(beats=["only one beat"])  # money_reveal requires exactly 2
    with pytest.raises(ResearchGateError, match="expected 2-2 beats, got 1"):
        validate_shape(script)


def test_missing_reveal_is_rejected():
    script = make_script(reveal="")
    with pytest.raises(ResearchGateError, match="missing required Bizyr reveal"):
        validate_shape(script)


def test_missing_cta_is_rejected():
    script = make_script(cta="")
    with pytest.raises(ResearchGateError, match="missing required CTA"):
        validate_shape(script)


def test_trend_signal_never_raises_when_pytrends_unavailable_or_failing():
    # Whether or not pytrends is installed in this environment, a nonsense/unreachable
    # call must degrade to None rather than raising -- that's the whole point of the
    # soft-enrichment contract.
    result = try_fetch_trend_signal("this-keyword-should-not-crash-anything")
    assert result is None or result.keyword == "this-keyword-should-not-crash-anything"


def test_run_research_gate_passes_without_trend_seed():
    result = run_research_gate(make_script(), trend_seed_keyword=None)
    assert result.passed is True
    assert result.shape == "money_reveal"
    assert result.trend_signal is None


def test_run_research_gate_raises_on_hard_gate_failure():
    with pytest.raises(ResearchGateError):
        run_research_gate(make_script(cta=""), trend_seed_keyword=None)
