import json

import pytest

from src.credentials import CredentialsError, load_niche_credentials


def test_load_niche_credentials_full_blob(monkeypatch):
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
    creds = load_niche_credentials("Barber")
    assert creds.meta_access_token == "meta-token"
    assert creds.tiktok_access_token == "tiktok-token"
    assert creds.youtube.refresh_token == "yt-refresh"
    assert creds.youtube.client_id == "yt-client-id"


def test_load_niche_credentials_partial_blob_omits_platforms(monkeypatch):
    monkeypatch.setenv("NICHE_CREDS__BARBER", json.dumps({"meta_access_token": "meta-token"}))
    creds = load_niche_credentials("Barber")
    assert creds.meta_access_token == "meta-token"
    assert creds.tiktok_access_token is None
    assert creds.youtube is None


def test_load_niche_credentials_uppercases_niche_name_for_env_var(monkeypatch):
    monkeypatch.setenv("NICHE_CREDS__DOGGROOMER", json.dumps({"meta_access_token": "x"}))
    creds = load_niche_credentials("doggroomer")
    assert creds.meta_access_token == "x"


def test_load_niche_credentials_raises_clearly_when_env_var_missing(monkeypatch):
    monkeypatch.delenv("NICHE_CREDS__BARBER", raising=False)
    with pytest.raises(CredentialsError, match="NICHE_CREDS__BARBER is not set"):
        load_niche_credentials("Barber")


def test_load_niche_credentials_raises_clearly_on_invalid_json(monkeypatch):
    monkeypatch.setenv("NICHE_CREDS__BARBER", "not valid json{{{")
    with pytest.raises(CredentialsError, match="not valid JSON"):
        load_niche_credentials("Barber")
