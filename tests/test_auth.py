import json
from pathlib import Path
from typing import Any

import pytest

from auth.app import create_app
from auth.users import UserStore
from tests.conftest import TEST_PASSWORD, TEST_SECRET


def test_secret_is_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET is required"):
        create_app(str(tmp_path / "missing-secret"))


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"username": "ab", "password": TEST_PASSWORD}, "invalid_username"),
        ({"username": "alice", "password": "short"}, "invalid_password"),
        ({"username": "alice"}, "missing_fields"),
        (
            {"username": "alice", "password": TEST_PASSWORD, "admin": True},
            "unexpected_fields",
        ),
    ],
)
def test_registration_rejects_invalid_payloads(
    auth_client: Any, payload: dict[str, Any], expected_code: str
) -> None:
    response = auth_client.post("/users", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == expected_code


def test_registration_requires_json(auth_client: Any) -> None:
    response = auth_client.post("/users", data="username=alice")
    assert response.status_code == 415
    assert response.get_json()["error"]["code"] == "unsupported_media_type"


def test_registration_hashes_password_and_rejects_duplicate(
    auth_client: Any, auth_app: Any
) -> None:
    payload = {"username": "alice", "password": TEST_PASSWORD}
    first = auth_client.post("/users", json=payload)
    duplicate = auth_client.post("/users", json=payload)

    assert first.status_code == 201
    assert duplicate.status_code == 409
    database_text = (Path(auth_app.instance_path) / "database.json").read_text(encoding="utf-8")
    database = json.loads(database_text)
    assert TEST_PASSWORD not in database_text
    assert database["users"]["alice"]["password_hash"].startswith("scrypt:")


def test_login_validate_and_reject_tampered_token(auth_client: Any, issue_token: Any) -> None:
    token = issue_token()

    valid = auth_client.post("/validate", json={"token": token})
    wrong_login = auth_client.post(
        "/users/login",
        json={"username": "alice", "password": "this is the wrong password"},
    )
    forged = f"{token.rsplit('.', maxsplit=1)[0]}.not-a-valid-signature"
    invalid = auth_client.post("/validate", json={"token": forged})

    assert valid.status_code == 200
    assert valid.get_json() == {"username": "alice"}
    assert wrong_login.status_code == 401
    assert wrong_login.headers["WWW-Authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert invalid.get_json()["error"]["code"] == "invalid_token"


def test_password_change_invalidates_old_password(auth_client: Any, issue_token: Any) -> None:
    issue_token()
    new_password = "an even better password phrase"

    changed = auth_client.put(
        "/users/password",
        json={
            "username": "alice",
            "old_password": TEST_PASSWORD,
            "new_password": new_password,
        },
    )
    old_login = auth_client.post(
        "/users/login",
        json={"username": "alice", "password": TEST_PASSWORD},
    )
    new_login = auth_client.post(
        "/users/login",
        json={"username": "alice", "password": new_password},
    )

    assert changed.status_code == 204
    assert changed.headers["Cache-Control"] == "no-store"
    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_legacy_plaintext_database_is_migrated(tmp_path: Path) -> None:
    instance = tmp_path / "legacy"
    instance.mkdir()
    legacy_password = "test"
    (instance / "database.json").write_text(
        json.dumps({"alice": legacy_password}),
        encoding="utf-8",
    )

    app = create_app(str(instance), jwt_secret=TEST_SECRET)
    client = app.test_client()
    login = client.post(
        "/users/login",
        json={"username": "alice", "password": legacy_password},
    )
    migrated_text = (instance / "database.json").read_text(encoding="utf-8")

    assert login.status_code == 200
    assert f'"alice":"{legacy_password}"' not in migrated_text


def test_user_store_rolls_back_failed_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UserStore(str(tmp_path / "users"))

    def fail_to_persist() -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store, "_persist_locked", fail_to_persist)

    with pytest.raises(OSError, match="simulated disk failure"):
        store.create("alice", TEST_PASSWORD)

    assert not store.exists("alice")


def test_unexpected_failures_return_sanitized_json(
    auth_client: Any, auth_app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = auth_app.extensions["user_store"]

    def fail_to_create(_username: str, _password: str) -> bool:
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(store, "create", fail_to_create)
    response = auth_client.post(
        "/users",
        json={"username": "alice", "password": TEST_PASSWORD},
    )

    assert response.status_code == 500
    assert response.get_json() == {
        "error": {"code": "internal_error", "message": "An unexpected error occurred"}
    }
    assert b"sensitive filesystem detail" not in response.data
