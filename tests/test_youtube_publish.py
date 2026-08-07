from pathlib import Path
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

from src.publish.youtube import (
    RETRY_BASE_DELAY_S,
    YouTubeUploadError,
    _run_resumable_upload,
    upload_private_video,
)


class FakeHttpResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "error"


def make_http_error(status: int) -> HttpError:
    return HttpError(resp=FakeHttpResp(status), content=b"error")


class FakeResumableRequest:
    """Simulates googleapiclient's chunked upload request: raises for the first N calls,
    then succeeds with a final response.
    """

    def __init__(self, failures: list[HttpError], final_response: dict):
        self._failures = list(failures)
        self._final_response = final_response
        self.call_count = 0

    def next_chunk(self):
        self.call_count += 1
        if self._failures:
            raise self._failures.pop(0)
        return (None, self._final_response)


def test_run_resumable_upload_succeeds_immediately_with_no_errors():
    request = FakeResumableRequest(failures=[], final_response={"id": "abc123"})
    result = _run_resumable_upload(request)
    assert result == {"id": "abc123"}
    assert request.call_count == 1


def test_run_resumable_upload_retries_retriable_errors_then_succeeds(mocker):
    mock_sleep = mocker.patch("time.sleep")
    request = FakeResumableRequest(
        failures=[make_http_error(503), make_http_error(500)],
        final_response={"id": "abc123"},
    )
    result = _run_resumable_upload(request, max_retries=5)
    assert result == {"id": "abc123"}
    assert request.call_count == 3
    # exponential backoff: base * 2^0, base * 2^1
    assert mock_sleep.call_args_list[0].args[0] == RETRY_BASE_DELAY_S * 1
    assert mock_sleep.call_args_list[1].args[0] == RETRY_BASE_DELAY_S * 2


def test_run_resumable_upload_raises_on_non_retriable_error():
    request = FakeResumableRequest(failures=[make_http_error(403)], final_response={"id": "x"})
    with pytest.raises(YouTubeUploadError):
        _run_resumable_upload(request)


def test_run_resumable_upload_raises_after_exhausting_retries(mocker):
    mocker.patch("time.sleep")
    request = FakeResumableRequest(
        failures=[make_http_error(500)] * 6,  # more than max_retries
        final_response={"id": "x"},
    )
    with pytest.raises(YouTubeUploadError):
        _run_resumable_upload(request, max_retries=5)


def test_upload_private_video_sets_privacy_status_and_returns_id(mocker, tmp_path):
    fake_video = tmp_path / "reel.mp4"
    fake_video.write_bytes(b"fake video bytes")

    mock_request = FakeResumableRequest(failures=[], final_response={"id": "video123"})
    mock_youtube = MagicMock()
    mock_youtube.videos.return_value.insert.return_value = mock_request

    mocker.patch("src.publish.youtube.MediaFileUpload")

    result = upload_private_video(mock_youtube, fake_video, "My title", "My description")

    assert result == "video123"
    _, kwargs = mock_youtube.videos.return_value.insert.call_args
    assert kwargs["body"]["status"]["privacyStatus"] == "private"
    assert kwargs["body"]["snippet"]["title"] == "My title"
