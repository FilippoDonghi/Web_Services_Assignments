"""Authentication client and destination URL validation."""

import math
import os
from typing import Any
from urllib.parse import urlsplit

import requests


class InvalidAuthorization(ValueError):
    """The caller did not provide a well-formed Bearer credential."""


class AuthServiceUnavailable(RuntimeError):
    """The authentication service could not provide a trustworthy answer."""


def parse_bearer_token(header: str | None) -> str:
    if not isinstance(header, str):
        raise InvalidAuthorization("Authorization header is required")
    scheme, separator, token = header.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not token
        or any(character.isspace() for character in token)
    ):
        raise InvalidAuthorization("Authorization must use the Bearer scheme")
    if len(token) > 4096:
        raise InvalidAuthorization("Bearer token is too long")
    return token


class AuthClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        session: Any = requests,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("AUTH_BASE_URL", "http://127.0.0.1:5001")
        ).rstrip("/")
        parsed_base_url = urlsplit(self._base_url)
        if (
            parsed_base_url.scheme not in {"http", "https"}
            or not parsed_base_url.netloc
            or parsed_base_url.username is not None
            or parsed_base_url.password is not None
            or parsed_base_url.query
            or parsed_base_url.fragment
        ):
            raise RuntimeError(
                "AUTH_BASE_URL must be an HTTP(S) origin or path without credentials"
            )
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else float(os.environ.get("AUTH_TIMEOUT_SECONDS", "2"))
        )
        if not math.isfinite(self._timeout_seconds) or self._timeout_seconds <= 0:
            raise RuntimeError("AUTH_TIMEOUT_SECONDS must be positive")
        self._session = session

    def validate_authorization(self, header: str | None) -> str | None:
        token = parse_bearer_token(header)
        try:
            response = self._session.post(
                f"{self._base_url}/validate",
                json={"token": token},
                timeout=self._timeout_seconds,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise AuthServiceUnavailable("authentication service request failed") from exc

        if response.status_code == 401:
            return None
        if response.status_code != 200:
            raise AuthServiceUnavailable("authentication service returned an unexpected status")
        try:
            payload = response.json()
        except ValueError as exc:
            raise AuthServiceUnavailable("authentication service returned invalid JSON") from exc

        username = payload.get("username") if isinstance(payload, dict) else None
        if not isinstance(username, str) or not username:
            raise AuthServiceUnavailable("authentication service returned an invalid response")
        return username


def is_valid_url(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    if "\\" in value or any(character.isspace() or ord(character) < 32 for character in value):
        return False

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False

    return bool(
        parsed.scheme.lower() in {"http", "https"}
        and parsed.netloc
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and (port is None or 1 <= port <= 65535)
    )
