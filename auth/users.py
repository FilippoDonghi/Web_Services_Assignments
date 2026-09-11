"""Small, file-backed user store for the single-process demo service."""

import json
import os
import tempfile
import threading
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash


class UserStore:
    """Persist password hashes with in-process locking and atomic replacement."""

    def __init__(self, instance_path: str) -> None:
        # Keep the baseline filename so existing volumes can be migrated in place.
        self._path = Path(instance_path) / "database.json"
        self._lock = threading.RLock()
        self._users: dict[str, dict[str, str]] = {}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self._path.exists():
                self._persist_locked()
                return

            try:
                document = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Cannot read user database at {self._path}") from exc

            users = document.get("users") if isinstance(document, dict) else None
            if isinstance(users, dict) and all(
                isinstance(name, str)
                and isinstance(record, dict)
                and isinstance(record.get("password_hash"), str)
                for name, record in users.items()
            ):
                self._users = users
                return

            # The course baseline stored a top-level username -> plaintext password map.
            # Migrate it once so existing local volumes do not retain plaintext credentials.
            if isinstance(document, dict) and all(
                isinstance(name, str) and isinstance(password, str)
                for name, password in document.items()
            ):
                self._users = {
                    name: {"password_hash": generate_password_hash(password, method="scrypt")}
                    for name, password in document.items()
                }
                self._persist_locked()
                return

            raise RuntimeError(f"User database at {self._path} has an unsupported schema")

    def _persist_locked(self) -> None:
        document = {"version": 1, "users": self._users}
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                json.dump(document, temporary, separators=(",", ":"), sort_keys=True)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_name, 0o600)
            os.replace(temporary_name, self._path)
        except OSError:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise

    def exists(self, username: str) -> bool:
        with self._lock:
            return username in self._users

    def create(self, username: str, password: str) -> bool:
        with self._lock:
            if username in self._users:
                return False
            self._users[username] = {
                "password_hash": generate_password_hash(password, method="scrypt")
            }
            try:
                self._persist_locked()
            except OSError:
                del self._users[username]
                raise
            return True

    def authenticate(self, username: str, password: str) -> bool:
        with self._lock:
            record = self._users.get(username)
            return bool(record and check_password_hash(record["password_hash"], password))

    def update_password(self, username: str, old_password: str, new_password: str) -> bool:
        with self._lock:
            record = self._users.get(username)
            if not record or not check_password_hash(record["password_hash"], old_password):
                return False
            previous_hash = record["password_hash"]
            record["password_hash"] = generate_password_hash(new_password, method="scrypt")
            try:
                self._persist_locked()
            except OSError:
                record["password_hash"] = previous_hash
                raise
            return True
