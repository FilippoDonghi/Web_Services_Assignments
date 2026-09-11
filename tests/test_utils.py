from typing import Any

import pytest
import requests

from shortener.utils import (
    AuthClient,
    AuthServiceUnavailable,
    InvalidAuthorization,
    is_valid_url,
    parse_bearer_token,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://localhost:8080/path?query=value#fragment",
        "https://sub.example.travel/a-long-path",
    ],
)
def test_url_validator_accepts_absolute_http_urls(url: str) -> None:
    assert is_valid_url(url)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "example.com",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https://user:password@example.com",
        "https://example.com:99999",
        "https://example.com/path with spaces",
        "https://example.com\\@attacker.example",
    ],
)
def test_url_validator_rejects_unsafe_or_ambiguous_values(url: object) -> None:
    assert not is_valid_url(url)


class FakeResponse:
    status_code = 200

    def json(self) -> dict[str, str]:
        return {"username": "alice"}


class RecordingSession:
    def __init__(self) -> None:
        self.call: dict[str, Any] = {}

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.call = {"url": url, **kwargs}
        return FakeResponse()


def test_auth_client_uses_bearer_token_and_timeout() -> None:
    session = RecordingSession()
    client = AuthClient("http://auth:5001/", timeout_seconds=1.5, session=session)

    username = client.validate_authorization("Bearer signed-token")

    assert username == "alice"
    assert session.call == {
        "url": "http://auth:5001/validate",
        "json": {"token": "signed-token"},
        "timeout": 1.5,
        "allow_redirects": False,
    }


def test_auth_client_translates_network_failure() -> None:
    class TimeoutSession:
        def post(self, _url: str, **_kwargs: Any) -> None:
            raise requests.Timeout("simulated timeout")

    client = AuthClient("http://auth:5001", timeout_seconds=0.1, session=TimeoutSession())

    with pytest.raises(AuthServiceUnavailable):
        client.validate_authorization("Bearer signed-token")


@pytest.mark.parametrize("header", ["Bearer token\tpart", "Bearer token\npart"])
def test_bearer_parser_rejects_all_token_whitespace(header: str) -> None:
    with pytest.raises(InvalidAuthorization):
        parse_bearer_token(header)


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://auth.example",
        "http://user:password@auth.example",
        "http://auth.example?redirect=https://attacker.example",
    ],
)
def test_auth_client_rejects_unsafe_base_urls(base_url: str) -> None:
    with pytest.raises(RuntimeError, match="AUTH_BASE_URL"):
        AuthClient(base_url)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_auth_client_rejects_invalid_timeouts(timeout: float) -> None:
    with pytest.raises(RuntimeError, match="AUTH_TIMEOUT_SECONDS"):
        AuthClient(timeout_seconds=timeout)
