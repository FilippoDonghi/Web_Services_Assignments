from collections.abc import Callable
from typing import Any

import pytest

from auth.app import create_app as create_auth_app
from shortener.utils import AuthServiceUnavailable, parse_bearer_token

TEST_SECRET = "test-secret-with-at-least-thirty-two-bytes-0001"
TEST_PASSWORD = "correct horse battery staple"


class InProcessAuthClient:
    """Exercise the real auth API without opening a network port."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def validate_authorization(self, header: str | None) -> str | None:
        token = parse_bearer_token(header)
        response = self._client.post("/validate", json={"token": token})
        if response.status_code == 401:
            return None
        if response.status_code != 200:
            raise AuthServiceUnavailable("unexpected in-process auth response")
        return response.get_json()["username"]


@pytest.fixture
def auth_app(tmp_path: Any) -> Any:
    app = create_auth_app(str(tmp_path / "auth"), jwt_secret=TEST_SECRET)
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def auth_client(auth_app: Any) -> Any:
    return auth_app.test_client()


@pytest.fixture
def issue_token(auth_client: Any) -> Callable[[str, str], str]:
    def issue(username: str = "alice", password: str = TEST_PASSWORD) -> str:
        created = auth_client.post(
            "/users",
            json={"username": username, "password": password},
        )
        assert created.status_code == 201
        login = auth_client.post(
            "/users/login",
            json={"username": username, "password": password},
        )
        assert login.status_code == 200
        return login.get_json()["access_token"]

    return issue
