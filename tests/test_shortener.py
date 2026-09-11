from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from shortener.app import create_app as create_shortener_app
from shortener.url import UrlStore
from shortener.utils import AuthServiceUnavailable
from tests.conftest import TEST_PASSWORD, InProcessAuthClient


class UnavailableAuthClient:
    def validate_authorization(self, _header: str | None) -> str | None:
        raise AuthServiceUnavailable("simulated outage")


def authorization(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_authenticated_crud_and_redirect_flow(
    tmp_path: Path,
    auth_client: Any,
    issue_token: Callable[[str, str], str],
) -> None:
    alice_token = issue_token()
    bob_token = issue_token("bob", "bob has a sufficiently long password")
    app = create_shortener_app(str(tmp_path / "shortener"), InProcessAuthClient(auth_client))
    app.config.update(TESTING=True)
    client = app.test_client()

    created = client.post(
        "/",
        headers=authorization(alice_token),
        json={"url": "https://example.com/original"},
    )
    short_id = created.get_json()["id"]

    assert created.status_code == 201
    assert len(short_id) == 12
    assert created.headers["Location"] == f"/{short_id}"
    assert client.get(f"/{short_id}").status_code == 302
    assert client.get(f"/{short_id}").headers["Location"] == "https://example.com/original"
    assert client.get("/", headers=authorization(alice_token)).get_json() == {
        "items": [{"id": short_id, "url": "https://example.com/original"}],
        "count": 1,
    }

    forbidden = client.put(
        f"/{short_id}",
        headers=authorization(bob_token),
        json={"url": "https://example.com/not-bobs-link"},
    )
    updated = client.put(
        f"/{short_id}",
        headers=authorization(alice_token),
        json={"url": "https://example.org/updated"},
    )

    assert forbidden.status_code == 403
    assert updated.status_code == 204
    assert client.get(f"/{short_id}").headers["Location"] == "https://example.org/updated"
    assert client.delete(f"/{short_id}", headers=authorization(alice_token)).status_code == 204
    assert client.get(f"/{short_id}").status_code == 404


def test_delete_all_returns_count(
    tmp_path: Path,
    auth_client: Any,
    issue_token: Callable[[str, str], str],
) -> None:
    token = issue_token()
    app = create_shortener_app(str(tmp_path / "shortener"), InProcessAuthClient(auth_client))
    client = app.test_client()
    headers = authorization(token)
    for destination in ("https://example.com/one", "https://example.com/two"):
        assert client.post("/", headers=headers, json={"url": destination}).status_code == 201

    deleted = client.delete("/", headers=headers)

    assert deleted.status_code == 200
    assert deleted.get_json() == {"deleted": 2}
    assert client.get("/", headers=headers).get_json() == {"items": [], "count": 0}


@pytest.mark.parametrize("header", [None, "token", "Basic token", "Bearer", "Bearer one two"])
def test_protected_routes_require_strict_bearer_header(tmp_path: Path, header: str | None) -> None:
    class ShouldNotBeCalled:
        def validate_authorization(self, supplied_header: str | None) -> str | None:
            from shortener.utils import parse_bearer_token

            return parse_bearer_token(supplied_header)

    app = create_shortener_app(str(tmp_path / "shortener"), ShouldNotBeCalled())
    client = app.test_client()
    headers = {"Authorization": header} if header is not None else {}

    response = client.get("/", headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_invalid_token_and_auth_outage_are_distinct(tmp_path: Path) -> None:
    class InvalidTokenClient:
        def validate_authorization(self, _header: str | None) -> str | None:
            return None

    invalid_app = create_shortener_app(str(tmp_path / "invalid"), InvalidTokenClient())
    unavailable_app = create_shortener_app(str(tmp_path / "unavailable"), UnavailableAuthClient())

    invalid = invalid_app.test_client().get("/", headers=authorization("bad-token"))
    unavailable = unavailable_app.test_client().get("/", headers=authorization("any-token"))

    assert invalid.status_code == 401
    assert invalid.get_json()["error"]["code"] == "invalid_token"
    assert unavailable.status_code == 503
    assert unavailable.get_json()["error"]["code"] == "authentication_unavailable"


def test_create_rejects_bad_json_and_url(
    tmp_path: Path,
    auth_client: Any,
    issue_token: Callable[[str, str], str],
) -> None:
    token = issue_token("alice", TEST_PASSWORD)
    app = create_shortener_app(str(tmp_path / "shortener"), InProcessAuthClient(auth_client))
    client = app.test_client()
    headers = authorization(token)

    not_json = client.post("/", headers=headers, data="url=https://example.com")
    extra_field = client.post(
        "/",
        headers=headers,
        json={"url": "https://example.com", "owner": "mallory"},
    )
    invalid_url = client.post("/", headers=headers, json={"url": "javascript:alert(1)"})

    assert not_json.status_code == 415
    assert extra_field.status_code == 400
    assert invalid_url.status_code == 400


def test_url_store_rejects_corrupt_database(tmp_path: Path) -> None:
    instance = tmp_path / "corrupt"
    instance.mkdir()
    (instance / "database.json").write_text(
        '{"version":1,"urls":{"../escape":{"url":"javascript:alert(1)","owner":"alice"}}}',
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="unsupported schema"):
        UrlStore(str(instance))


def test_url_store_rolls_back_failed_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UrlStore(str(tmp_path / "urls"))
    short_id = store.add("https://example.com/original", "alice")

    def fail_to_persist() -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store, "_persist_locked", fail_to_persist)

    with pytest.raises(OSError, match="simulated disk failure"):
        store.update_for_owner(short_id, "https://example.org/changed", "alice")

    assert store.get(short_id) == {"url": "https://example.com/original", "owner": "alice"}
