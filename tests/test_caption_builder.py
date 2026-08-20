from src.caption_builder import build_caption, build_hashtags
from src.research_gate import Script


def make_script(**overrides) -> Script:
    defaults = dict(
        shape="money_reveal",
        hook="I hit a 6-figure month as a barber.",
        beats=["beat one", "beat two"],
        reveal="I found an app.",
        cta="Comment 'CALLS' and I'll send you the app.",
        platform_cta_overrides={},
    )
    defaults.update(overrides)
    return Script(**defaults)


CONTENT_INTELLIGENCE = {
    "terminology": {"use": ["chair rent", "no-show", "the diary", "skin fade", "rebook", "column"]},
}
CAMPAIGN = {"cta_text": "Join the waitlist -- link in bio"}


def test_build_hashtags_pulls_from_terminology_use_list():
    tags = build_hashtags(CONTENT_INTELLIGENCE)
    assert tags[0] == "#ChairRent"
    assert all(tag.startswith("#") for tag in tags)


def test_build_hashtags_respects_max_count():
    tags = build_hashtags(CONTENT_INTELLIGENCE, max_count=2)
    assert len(tags) == 2


def test_build_hashtags_empty_when_no_terminology():
    assert build_hashtags({}) == []


def test_build_caption_instagram_includes_hook_reveal_cta_and_hashtags():
    caption = build_caption(make_script(), CONTENT_INTELLIGENCE, CAMPAIGN, "instagram")
    assert "I hit a 6-figure month as a barber." in caption
    assert "I found an app." in caption
    assert "Join the waitlist -- link in bio" in caption
    assert "#ChairRent" in caption


def test_build_caption_facebook_has_no_hashtags():
    caption = build_caption(make_script(), CONTENT_INTELLIGENCE, CAMPAIGN, "facebook")
    assert "#" not in caption
    assert "Join the waitlist -- link in bio" in caption


def test_build_caption_tiktok_is_pipe_separated_and_shorter():
    caption = build_caption(make_script(), CONTENT_INTELLIGENCE, CAMPAIGN, "tiktok")
    assert " | " in caption
    assert "I found an app." not in caption  # reveal isn't included in TikTok's shorter form


def test_build_caption_youtube_uses_reveal_not_hook_as_body():
    caption = build_caption(make_script(), CONTENT_INTELLIGENCE, CAMPAIGN, "youtube")
    assert "I found an app." in caption
    assert "Join the waitlist -- link in bio" in caption


def test_build_caption_unknown_platform_falls_back_to_hook_and_cta():
    caption = build_caption(make_script(), CONTENT_INTELLIGENCE, CAMPAIGN, "some-future-platform")
    assert "I hit a 6-figure month as a barber." in caption
    assert "Join the waitlist -- link in bio" in caption


def test_build_caption_cta_override_beats_campaign_and_script():
    script = make_script(platform_cta_overrides={"youtube": "Script-level override"})
    caption = build_caption(script, CONTENT_INTELLIGENCE, CAMPAIGN, "youtube", cta_override="Explicit override wins")
    assert "Explicit override wins" in caption
    assert "Script-level override" not in caption
    assert "Join the waitlist" not in caption


def test_build_caption_platform_cta_override_beats_campaign_default():
    script = make_script(platform_cta_overrides={"youtube": "Script-level override"})
    caption = build_caption(script, CONTENT_INTELLIGENCE, CAMPAIGN, "youtube")
    assert "Script-level override" in caption
    assert "Join the waitlist" not in caption


def test_build_caption_falls_back_to_script_cta_when_no_campaign_or_override():
    caption = build_caption(make_script(), CONTENT_INTELLIGENCE, {}, "facebook")
    assert "Comment 'CALLS' and I'll send you the app." in caption
