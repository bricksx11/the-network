import json
from pathlib import Path

import pytest

from src.orchestrator import publish_niche
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


def test_publish_niche_skips_platforms_missing_ids(mocker, full_credentials_env, tmp_path):
    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1", "url2"])
    mock_ig = mocker.patch("src.orchestrator.ig_publish_carousel")
    mock_fb = mocker.patch("src.orchestrator.fb_publish_carousel")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id")
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
    # meta_access_token absent entirely -- IG/FB should skip even though IDs are present
    monkeypatch.setenv("NICHE_CREDS__BARBER", json.dumps({"tiktok_access_token": "tiktok-token"}))
    mocker.patch("src.orchestrator.publish_to_scratch_branch", return_value=["url1", "url2"])
    mock_ig = mocker.patch("src.orchestrator.ig_publish_carousel")
    mocker.patch("src.orchestrator.upload_carousel_to_drafts", return_value="tt-id")

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
