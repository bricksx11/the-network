import pytest

from src.publish.meta_common import (
    ContainerTimeoutError,
    GraphAPIError,
    graph_get,
    graph_post,
    wait_for_container_ready,
)


class FakeResponse:
    def __init__(self, json_data, ok=True, status_code=200):
        self._json = json_data
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._json


def test_graph_post_returns_json_on_success(mocker):
    mock_post = mocker.patch("requests.post", return_value=FakeResponse({"id": "123"}))
    result = graph_post("me/media", "fake-token", image_url="http://example.com/a.png")
    assert result == {"id": "123"}
    # access_token must always be sent, alongside whatever params were passed
    _, kwargs = mock_post.call_args
    assert kwargs["data"]["access_token"] == "fake-token"
    assert kwargs["data"]["image_url"] == "http://example.com/a.png"


def test_graph_post_raises_graph_api_error_on_failure(mocker):
    mocker.patch(
        "requests.post",
        return_value=FakeResponse(
            {"error": {"message": "Invalid OAuth token", "code": 190, "type": "OAuthException"}},
            ok=False,
            status_code=400,
        ),
    )
    with pytest.raises(GraphAPIError) as exc_info:
        graph_post("me/media", "bad-token")
    assert exc_info.value.code == 190
    assert exc_info.value.error_type == "OAuthException"
    assert "Invalid OAuth token" in str(exc_info.value)


def test_graph_get_returns_json_on_success(mocker):
    mocker.patch("requests.get", return_value=FakeResponse({"status_code": "FINISHED"}))
    result = graph_get("12345", "fake-token", fields="status_code")
    assert result == {"status_code": "FINISHED"}


def test_wait_for_container_ready_returns_on_finished(mocker):
    mocker.patch("requests.get", return_value=FakeResponse({"status_code": "FINISHED"}))
    wait_for_container_ready("container-1", "fake-token", poll_interval_s=0, timeout_s=1)  # should not raise


def test_wait_for_container_ready_raises_on_error_status(mocker):
    mocker.patch("requests.get", return_value=FakeResponse({"status_code": "ERROR"}))
    with pytest.raises(GraphAPIError, match="failed processing"):
        wait_for_container_ready("container-1", "fake-token", poll_interval_s=0, timeout_s=1)


def test_wait_for_container_ready_times_out_if_never_finished(mocker):
    mocker.patch("requests.get", return_value=FakeResponse({"status_code": "IN_PROGRESS"}))
    with pytest.raises(ContainerTimeoutError):
        wait_for_container_ready("container-1", "fake-token", poll_interval_s=0.01, timeout_s=0.05)
