import json
from pathlib import Path

import pytest

from src.orchestrator import publish_niche, run_niche
from src.research_gate import Script


def make_script(**overrides) -> Script:
    defaults = dict(
        shape="money_reveal",
        hook="I hit a 6-figure month as a barber.",
        beats=["beat one", "beat two"],
        reveal="I found an app.",
        cta="Comment 'CALLS' and I'll send you the app.",
        platform_cta_overrides={"youtube": "Link in bio"},
    )
    defaults.update(overrides)
    return Script(**defaults)


FULL_NICHE_CONFIG = {
    "platforms": {
        "instagram": {"enabled": True, "business_account_id": "ig-123"},
        "facebook": {"enabled": True, "page_id": "page-123"},
        "tiktok": {"enabled": True},
        "youtube": {"enabled": True},
    }
}


@pytest.fixture
def full_credentials_env(monkeypatch):
    monkeypatch.setenv(
        "NICHE_CREDS__BARBER",
        json.dumps(
            {
                "meta_access_token": "meta-token",
                "ig_access_token": "ig-token",
                "tiktok_access_token": "tiktok-token",
                "youtube": {
                    "refresh_token": "yt-refresh",
                    "client_id": "yt-client-id",
                    "client_secret": "yt-client-secret",
                },
            }
        ),
    )


def test_publish_niche_hosts_carousel_and_video_in_one_call(mocker, full_credentials_env, tmp_path):
    mock_host = mocker.patch(
        "src.orchestrator.publish_to_scratch_branch",
        return_value=[
            "https://raw.../slide-1.png",
            "https://raw.../slide-2.png",
            "https://raw.../reel.mp4",
        ],
    )
    mocker.patch("src.orchestrator.ig_publish_carousel", return_value="ig-carousel-id")
    mocker.patch("src.orchestrator.ig_publish_reel", return_value="ig-reel-id")
    mocker.patch("src.orchestrator.fb_publish_carousel", return_value="fb-post-id")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-publish-id")
    mocker.patch("src.orchestrator.wait_for_publish_complete")
    mocker.patch("src.orchestrator.build_youtube_client", return_value=mocker.MagicMock())
    mocker.patch("src.orchestrator.upload_private_video", return_value="yt-video-id")

    carousel_paths = [tmp_path / "slide-1.png", tmp_path / "slide-2.png"]
    video_path = tmp_path / "reel.mp4"

    results = publish_niche("Barber", FULL_NICHE_CONFIG, carousel_paths, video_path, make_script())

    # exactly one hosting push, containing both carousel images AND the video together
    assert mock_host.call_count == 1
    hosted_files = mock_host.call_args.args[0]
    assert hosted_files == [*carousel_paths, video_path]

    assert results["instagram"] == {"carousel_post_id": "ig-carousel-id", "reel_post_id": "ig-reel-id"}
    assert results["facebook"] == {"post_id": "fb-post-id"}
    assert results["tiktok"] == {"publish_id": "tt-publish-id"}
    assert results["youtube"] == {"video_id": "yt-video-id"}


def test_publish_niche_skips_reel_but_still_posts_carousel_when_no_music(mocker, full_credentials_env, tmp_path):
    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1", "url2", "url3"])
    mocker.patch("src.orchestrator.ig_publish_carousel", return_value="ig-carousel-id")
    mock_reel = mocker.patch("src.orchestrator.ig_publish_reel")
    mocker.patch("src.orchestrator.fb_publish_carousel", return_value="fb-post-id")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id")
    mocker.patch("src.orchestrator.wait_for_publish_complete")
    mocker.patch("src.orchestrator.build_youtube_client", return_value=mocker.MagicMock())
    mocker.patch("src.orchestrator.upload_private_video", return_value="yt-id")

    results = publish_niche(
        "Barber", FULL_NICHE_CONFIG, [tmp_path / "s1.png"], tmp_path / "r.mp4", make_script(), has_music=False
    )

    mock_reel.assert_not_called()
    assert results["instagram"]["carousel_post_id"] == "ig-carousel-id"
    assert "reel_post_id" not in results["instagram"]
    assert "reel_skipped" in results["instagram"]
    # unaffected by audio -- YouTube's video still uploads even though it's silent
    assert results["youtube"] == {"video_id": "yt-id"}


def test_publish_niche_propagates_tiktok_failure_after_init_looked_fine(mocker, full_credentials_env, tmp_path):
    """A publish_id from the init call is not proof of success -- confirmed for real (a
    publish_id whose actual status later came back FAILED). wait_for_publish_complete must
    actually be awaited so a silent async failure surfaces as a real error, not a false
    "success" result with a publish_id nobody checked.
    """
    from src.publish.tiktok import TikTokAPIError

    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1"])
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id-that-actually-fails")
    mocker.patch(
        "src.orchestrator.wait_for_publish_complete",
        side_effect=TikTokAPIError("publish failed with status 'FAILED': file_format_check_failed"),
    )

    niche_config = {
        "platforms": {
            "instagram": {"enabled": False},
            "facebook": {"enabled": False},
            "tiktok": {"enabled": True},
            "youtube": {"enabled": False},
        }
    }

    with pytest.raises(TikTokAPIError, match="file_format_check_failed"):
        publish_niche("Barber", niche_config, [tmp_path / "s1.jpg"], tmp_path / "r.mp4", make_script())


def test_publish_niche_skips_reel_when_post_reel_disabled_even_with_music(mocker, full_credentials_env, tmp_path):
    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1"])
    mocker.patch("src.orchestrator.ig_publish_carousel", return_value="ig-carousel-id")
    mock_reel = mocker.patch("src.orchestrator.ig_publish_reel")
    mocker.patch("src.orchestrator.fb_publish_carousel", return_value="fb-post-id")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id")
    mocker.patch("src.orchestrator.wait_for_publish_complete")
    mocker.patch("src.orchestrator.build_youtube_client", return_value=mocker.MagicMock())
    mocker.patch("src.orchestrator.upload_private_video", return_value="yt-id")

    niche_config = {
        "platforms": {
            "instagram": {"enabled": True, "business_account_id": "ig-123", "post_reel": False},
            "facebook": {"enabled": True, "page_id": "page-123"},
            "tiktok": {"enabled": True},
            "youtube": {"enabled": True},
        }
    }

    results = publish_niche(
        "Barber", niche_config, [tmp_path / "s1.jpg"], tmp_path / "r.mp4", make_script(), has_music=True
    )

    mock_reel.assert_not_called()
    assert results["instagram"]["carousel_post_id"] == "ig-carousel-id"
    assert results["instagram"]["reel_skipped"] == "post_reel disabled in config -- carousel only for now"


def test_publish_niche_skips_platforms_missing_ids(mocker, full_credentials_env, tmp_path):
    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1", "url2"])
    mock_ig = mocker.patch("src.orchestrator.ig_publish_carousel")
    mock_fb = mocker.patch("src.orchestrator.fb_publish_carousel")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id")
    mocker.patch("src.orchestrator.wait_for_publish_complete")
    mocker.patch("src.orchestrator.build_youtube_client")
    mocker.patch("src.orchestrator.upload_private_video", return_value="yt-id")

    niche_config = {
        "platforms": {
            "instagram": {"enabled": True, "business_account_id": None},  # not provisioned yet
            "facebook": {"enabled": True, "page_id": None},
            "tiktok": {"enabled": True},
            "youtube": {"enabled": True},
        }
    }

    results = publish_niche(
        "Barber", niche_config, [tmp_path / "s1.png"], tmp_path / "r.mp4", make_script()
    )

    assert results["instagram"] == {"skipped": "not configured"}
    assert results["facebook"] == {"skipped": "not configured"}
    mock_ig.assert_not_called()
    mock_fb.assert_not_called()
    # tiktok/youtube were configured, so they should still have run
    assert results["tiktok"] == {"publish_id": "tt-id"}
    assert results["youtube"] == {"video_id": "yt-id"}


def test_publish_niche_skips_platform_missing_credentials(mocker, tmp_path, monkeypatch):
    # meta_access_token/ig_access_token absent entirely -- IG/FB should skip even though IDs are present
    monkeypatch.setenv("NICHE_CREDS__BARBER", json.dumps({"tiktok_access_token": "tiktok-token"}))
    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1", "url2"])
    mock_ig = mocker.patch("src.orchestrator.ig_publish_carousel")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id")
    mocker.patch("src.orchestrator.wait_for_publish_complete")

    niche_config = {
        "platforms": {
            "instagram": {"enabled": True, "business_account_id": "ig-123"},
            "facebook": {"enabled": True, "page_id": "page-123"},
            "tiktok": {"enabled": True},
            "youtube": {"enabled": False},
        }
    }

    results = publish_niche(
        "Barber", niche_config, [tmp_path / "s1.png"], tmp_path / "r.mp4", make_script()
    )

    assert results["instagram"] == {"skipped": "not configured"}
    mock_ig.assert_not_called()
    assert results["youtube"] == {"skipped": "not configured"}


def test_publish_niche_does_not_host_anything_when_no_platform_needs_it(mocker, tmp_path, monkeypatch):
    monkeypatch.setenv("NICHE_CREDS__BARBER", json.dumps({}))
    mock_host = mocker.patch("src.orchestrator.publish_to_scratch_branch")

    niche_config = {
        "platforms": {
            "instagram": {"enabled": False},
            "facebook": {"enabled": False},
            "tiktok": {"enabled": False},
            "youtube": {"enabled": False},
        }
    }

    publish_niche("Barber", niche_config, [tmp_path / "s1.png"], tmp_path / "r.mp4", make_script())
    mock_host.assert_not_called()


def _mock_render_pipeline(mocker, tmp_path):
    """Mocks everything upstream of publish_niche so these tests exercise only run_niche's
    publish=True/False branching, not rendering itself (already covered elsewhere).
    """
    mocker.patch("src.orchestrator.get_todays_script", return_value=make_script())
    mocker.patch(
        "src.orchestrator.run_research_gate",
        return_value=mocker.MagicMock(shape="money_reveal", trend_signal=None),
    )
    fake_image = mocker.MagicMock()
    fake_image.path = tmp_path / "aura-1.png"
    mocker.patch("src.orchestrator.select_images", return_value=[fake_image] * 4)
    # must live under out_dir (tmp_path/"out") to match what real run_niche passes as
    # out_dir, since the code computes paths relative to it for the run log
    carousel_paths = [tmp_path / "out" / f"slide-{i}.png" for i in range(4)]
    mocker.patch("src.orchestrator.render_carousel", return_value=carousel_paths)
    mocker.patch("src.orchestrator.render_video")
    mocker.patch("src.orchestrator.find_music_track", return_value=tmp_path / "track.mp3")


def test_run_niche_publish_false_skips_publishing(mocker, tmp_path):
    # LOGS_DIR and REPO_ROOT are module-level constants tied to the real repo path --
    # patch both so this test never touches the real repo and relative_to() calls against
    # fake tmp_path files succeed.
    mocker.patch("src.orchestrator.LOGS_DIR", tmp_path / "logs")
    mocker.patch("src.orchestrator.REPO_ROOT", tmp_path)
    _mock_render_pipeline(mocker, tmp_path)
    mock_publish = mocker.patch("src.orchestrator.publish_niche")

    record = run_niche("Barber", tmp_path / "out", publish=False)

    mock_publish.assert_not_called()
    assert "publish_results" not in record


def test_run_niche_publish_true_calls_publish_and_merges_results(mocker, tmp_path):
    mocker.patch("src.orchestrator.LOGS_DIR", tmp_path / "logs")
    mocker.patch("src.orchestrator.REPO_ROOT", tmp_path)
    _mock_render_pipeline(mocker, tmp_path)
    mocker.patch(
        "src.orchestrator.publish_niche",
        return_value={"instagram": {"carousel_post_id": "abc"}},
    )

    record = run_niche("Barber", tmp_path / "out", publish=True)

    assert record["publish_results"] == {"instagram": {"carousel_post_id": "abc"}}
