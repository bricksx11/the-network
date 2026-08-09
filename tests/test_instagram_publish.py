import pytest

from src.publish.instagram import publish_carousel, publish_reel
from src.publish.meta_common import GRAPH_INSTAGRAM_API_BASE


def test_publish_carousel_creates_children_then_container_then_publishes(mocker):
    mock_post = mocker.patch(
        "src.publish.instagram.graph_post",
        side_effect=[
            {"id": "child-1"},
            {"id": "child-2"},
            {"id": "child-3"},
            {"id": "carousel-container"},
            {"id": "published-post-id"},
        ],
    )
    mock_wait = mocker.patch("src.publish.instagram.wait_for_container_ready")

    result = publish_carousel(
        "ig-account-1",
        ["http://x/1.png", "http://x/2.png", "http://x/3.png"],
        "caption text",
        "fake-token",
    )

    assert result == "published-post-id"
    assert mock_post.call_count == 5  # 3 children + 1 carousel container + 1 publish
    mock_wait.assert_called_once_with("carousel-container", "fake-token", api_base=GRAPH_INSTAGRAM_API_BASE)

    # the carousel container call must reference all three child ids, comma-joined
    carousel_call = mock_post.call_args_list[3]
    assert carousel_call.kwargs["children"] == "child-1,child-2,child-3"
    assert carousel_call.kwargs["media_type"] == "CAROUSEL"

    # the final call must publish using the carousel container's id as creation_id
    publish_call = mock_post.call_args_list[4]
    assert publish_call.kwargs["creation_id"] == "carousel-container"


def test_publish_carousel_rejects_too_few_images():
    with pytest.raises(ValueError, match="2-10 images"):
        publish_carousel("ig-account-1", ["http://x/1.png"], "caption", "fake-token")


def test_publish_carousel_rejects_too_many_images():
    urls = [f"http://x/{i}.png" for i in range(11)]
    with pytest.raises(ValueError, match="2-10 images"):
        publish_carousel("ig-account-1", urls, "caption", "fake-token")


def test_publish_reel_uses_reels_media_type_and_longer_timeout(mocker):
    mock_post = mocker.patch(
        "src.publish.instagram.graph_post",
        side_effect=[{"id": "video-container"}, {"id": "published-reel-id"}],
    )
    mock_wait = mocker.patch("src.publish.instagram.wait_for_container_ready")

    result = publish_reel("ig-account-1", "http://x/reel.mp4", "reel caption", "fake-token")

    assert result == "published-reel-id"
    create_call = mock_post.call_args_list[0]
    assert create_call.kwargs["media_type"] == "REELS"
    assert create_call.kwargs["video_url"] == "http://x/reel.mp4"
    mock_wait.assert_called_once_with(
        "video-container", "fake-token", timeout_s=300, api_base=GRAPH_INSTAGRAM_API_BASE
    )
