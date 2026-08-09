import pytest

from src.publish.tiktok import (
    TikTokAPIError,
    TikTokStatusTimeoutError,
    check_publish_status,
    upload_carousel_to_drafts,
    wait_for_publish_complete,
)


class FakeResponse:
    def __init__(self, json_data):
        self._json = json_data

    def json(self):
        return self._json


def test_upload_carousel_sends_correct_media_upload_body(mocker):
    mock_post = mocker.patch(
        "requests.post",
        return_value=FakeResponse({"data": {"publish_id": "v_pub_url~123"}, "error": {"code": "ok"}}),
    )

    result = upload_carousel_to_drafts(
        ["http://x/1.jpg", "http://x/2.jpg"], "My title", "My description", "fake-token"
    )

    assert result == "v_pub_url~123"
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["media_type"] == "PHOTO"
    assert kwargs["json"]["post_mode"] == "MEDIA_UPLOAD"  # drafts, never DIRECT_POST
    assert kwargs["json"]["source_info"]["source"] == "PULL_FROM_URL"
    assert kwargs["json"]["source_info"]["photo_images"] == ["http://x/1.jpg", "http://x/2.jpg"]
    assert kwargs["headers"]["Authorization"] == "Bearer fake-token"


def test_upload_carousel_rejects_too_many_images():
    urls = [f"http://x/{i}.jpg" for i in range(36)]
    with pytest.raises(ValueError, match="1-35 images"):
        upload_carousel_to_drafts(urls, "t", "d", "fake-token")


def test_upload_carousel_raises_on_api_error(mocker):
    mocker.patch(
        "requests.post",
        return_value=FakeResponse(
            {"data": {}, "error": {"code": "invalid_param", "message": "bad domain", "log_id": "abc123"}}
        ),
    )
    with pytest.raises(TikTokAPIError) as exc_info:
        upload_carousel_to_drafts(["http://x/1.jpg"], "t", "d", "fake-token")
    assert exc_info.value.code == "invalid_param"
    assert exc_info.value.log_id == "abc123"


def test_check_publish_status_returns_data(mocker):
    mocker.patch(
        "requests.post",
        return_value=FakeResponse({"data": {"status": "PROCESSING_UPLOAD"}, "error": {"code": "ok"}}),
    )
    result = check_publish_status("v_pub_url~123", "fake-token")
    assert result == {"status": "PROCESSING_UPLOAD"}


def test_wait_for_publish_complete_returns_on_success(mocker):
    mocker.patch(
        "src.publish.tiktok.check_publish_status",
        return_value={"status": "PUBLISH_COMPLETE"},
    )
    wait_for_publish_complete("v_pub_url~123", "fake-token", poll_interval_s=0, timeout_s=1)  # should not raise


def test_wait_for_publish_complete_recognizes_inbox_delivery_as_success(mocker):
    # SEND_TO_USER_INBOX -- the real terminal status for post_mode=MEDIA_UPLOAD, confirmed
    # against a live sandbox call, not PUBLISH_COMPLETE (that one turned out to be wrong for
    # this mode -- a real post silently timed out because this status went unrecognized).
    mocker.patch(
        "src.publish.tiktok.check_publish_status",
        return_value={"status": "SEND_TO_USER_INBOX"},
    )
    wait_for_publish_complete("v_pub_url~123", "fake-token", poll_interval_s=0, timeout_s=1)  # should not raise


def test_wait_for_publish_complete_raises_on_failed_status(mocker):
    mocker.patch(
        "src.publish.tiktok.check_publish_status",
        return_value={"status": "PUBLISH_FAILED"},
    )
    with pytest.raises(TikTokAPIError, match="PUBLISH_FAILED"):
        wait_for_publish_complete("v_pub_url~123", "fake-token", poll_interval_s=0, timeout_s=1)


def test_wait_for_publish_complete_times_out(mocker):
    mocker.patch(
        "src.publish.tiktok.check_publish_status",
        return_value={"status": "PROCESSING_UPLOAD"},
    )
    with pytest.raises(TikTokStatusTimeoutError):
        wait_for_publish_complete("v_pub_url~123", "fake-token", poll_interval_s=0.01, timeout_s=0.05)
