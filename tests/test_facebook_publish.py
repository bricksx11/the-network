import json

import pytest

from src.publish.facebook import publish_carousel


def test_publish_carousel_uploads_unpublished_then_posts_to_feed(mocker):
    mock_post = mocker.patch(
        "src.publish.facebook.graph_post",
        side_effect=[
            {"id": "photo-1"},
            {"id": "photo-2"},
            {"id": "photo-3"},
            {"id": "published-post-id"},
        ],
    )

    result = publish_carousel(
        "page-1", ["http://x/1.png", "http://x/2.png", "http://x/3.png"], "caption text", "fake-token"
    )

    assert result == "published-post-id"
    assert mock_post.call_count == 4  # 3 photo uploads + 1 feed post

    # each photo upload must be unpublished
    for call in mock_post.call_args_list[:3]:
        assert call.kwargs["published"] == "false"

    # the feed call must reference all three photo ids via attached_media
    feed_call = mock_post.call_args_list[3]
    assert feed_call.args[0] == "page-1/feed"
    extra = feed_call.kwargs["extra_params"]
    assert json.loads(extra["attached_media[0]"]) == {"media_fbid": "photo-1"}
    assert json.loads(extra["attached_media[1]"]) == {"media_fbid": "photo-2"}
    assert json.loads(extra["attached_media[2]"]) == {"media_fbid": "photo-3"}


def test_publish_carousel_rejects_too_few_images():
    with pytest.raises(ValueError, match="2-10 images"):
        publish_carousel("page-1", ["http://x/1.png"], "caption", "fake-token")


def test_publish_carousel_rejects_too_many_images():
    urls = [f"http://x/{i}.png" for i in range(11)]
    with pytest.raises(ValueError, match="2-10 images"):
        publish_carousel("page-1", urls, "caption", "fake-token")
