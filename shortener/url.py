"""Atomic JSON persistence for the single-process URL shortener demo."""

import json
import os
import secrets
import tempfile
import threading
from pathlib import Path

from .utils import is_valid_url


class UrlStore:
    def __init__(self, instance_path: str) -> None:
        # Each service has its own instance directory, so the baseline filename is unambiguous.
        self._path = Path(instance_path) / "database.json"
        self._lock = threading.RLock()
        self._urls: dict[str, dict[str, str]] = {}
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
                raise RuntimeError(f"Cannot read URL database at {self._path}") from exc

            urls = document.get("urls") if isinstance(document, dict) else None
            if not isinstance(urls, dict) or not all(
                isinstance(short_id, str)
                and short_id.isascii()
                and 1 <= len(short_id) <= 64
                and all(character.isalnum() or character in "-_" for character in short_id)
                and isinstance(record, dict)
                and isinstance(record.get("url"), str)
                and is_valid_url(record["url"])
                and isinstance(record.get("owner"), str)
                and 1 <= len(record["owner"]) <= 64
                for short_id, record in urls.items()
            ):
                raise RuntimeError(f"URL database at {self._path} has an unsupported schema")
            self._urls = urls

    def _persist_locked(self) -> None:
        document = {"version": 1, "urls": self._urls}
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

    def list_for_owner(self, owner: str) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"id": short_id, "url": record["url"]}
                for short_id, record in sorted(self._urls.items())
                if record["owner"] == owner
            ]

    def get(self, short_id: str) -> dict[str, str] | None:
        with self._lock:
            record = self._urls.get(short_id)
            return dict(record) if record else None

    def add(self, url: str, owner: str) -> str:
        with self._lock:
            for _ in range(10):
                short_id = secrets.token_urlsafe(9)
                if short_id not in self._urls:
                    self._urls[short_id] = {"url": url, "owner": owner}
                    try:
                        self._persist_locked()
                    except OSError:
                        del self._urls[short_id]
                        raise
                    return short_id
            raise RuntimeError("Could not allocate a unique short ID")

    def update_for_owner(self, short_id: str, url: str, owner: str) -> str:
        with self._lock:
            record = self._urls.get(short_id)
            if record is None:
                return "missing"
            if record["owner"] != owner:
                return "forbidden"
            previous_url = record["url"]
            record["url"] = url
            try:
                self._persist_locked()
            except OSError:
                record["url"] = previous_url
                raise
            return "updated"

    def delete_for_owner(self, short_id: str, owner: str) -> str:
        with self._lock:
            record = self._urls.get(short_id)
            if record is None:
                return "missing"
            if record["owner"] != owner:
                return "forbidden"
            del self._urls[short_id]
            try:
                self._persist_locked()
            except OSError:
                self._urls[short_id] = record
                raise
            return "deleted"

    def delete_all_for_owner(self, owner: str) -> int:
        with self._lock:
            owned_records = {
                short_id: record
                for short_id, record in self._urls.items()
                if record["owner"] == owner
            }
            owned_ids = list(owned_records)
            for short_id in owned_ids:
                del self._urls[short_id]
            if owned_ids:
                try:
                    self._persist_locked()
                except OSError:
                    self._urls.update(owned_records)
                    raise
            return len(owned_ids)
