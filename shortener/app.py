"""URL shortener service application factory."""

import os
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, redirect, request, url_for
from werkzeug.exceptions import HTTPException

from .config import BIND_HOST, PUBLIC_PATH_PREFIX, URL_SHORTENER_PORT
from .url import UrlStore
from .utils import AuthClient, AuthServiceUnavailable, InvalidAuthorization, is_valid_url


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _error(code: str, message: str, status: int) -> tuple[Response, int]:
    return jsonify({"error": {"code": code, "message": message}}), status


def _json_object(required_fields: set[str]) -> dict[str, Any]:
    if not request.is_json:
        raise ApiError(415, "unsupported_media_type", "Content-Type must be application/json")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "invalid_json", "Request body must be a JSON object")
    missing = sorted(required_fields - data.keys())
    unexpected = sorted(data.keys() - required_fields)
    if missing:
        raise ApiError(400, "missing_fields", f"Missing fields: {', '.join(missing)}")
    if unexpected:
        raise ApiError(400, "unexpected_fields", f"Unexpected fields: {', '.join(unexpected)}")
    return data


def create_app(instance_path: str | None = None, auth_client: Any | None = None) -> Flask:
    resolved_instance = Path(
        instance_path
        or os.environ.get("INSTANCE_PATH")
        or Path(__file__).resolve().parent / "instance"
    ).resolve()
    app = Flask(__name__, instance_path=str(resolved_instance), instance_relative_config=True)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    urls = UrlStore(app.instance_path)
    authenticator = auth_client or AuthClient()
    app.extensions["url_store"] = urls
    app.extensions["auth_client"] = authenticator

    def authenticated_username() -> str:
        try:
            username = authenticator.validate_authorization(request.headers.get("Authorization"))
        except InvalidAuthorization as exc:
            raise ApiError(401, "invalid_authorization", str(exc)) from exc
        except AuthServiceUnavailable as exc:
            raise ApiError(
                503,
                "authentication_unavailable",
                "Authentication service is temporarily unavailable",
            ) from exc
        if username is None:
            raise ApiError(401, "invalid_token", "Bearer token is invalid or expired")
        return username

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError) -> tuple[Response, int]:
        response, status = _error(exc.code, exc.message, exc.status)
        if status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response, status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException) -> tuple[Response, int]:
        return _error(exc.name.lower().replace(" ", "_"), exc.description, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception) -> tuple[Response, int]:
        app.logger.exception("Unhandled URL shortener service error", exc_info=exc)
        return _error("internal_error", "An unexpected error occurred", 500)

    @app.get("/health")
    def health() -> tuple[Response, int]:
        return jsonify({"status": "ok"}), 200

    @app.get("/")
    def list_urls() -> tuple[Response, int]:
        items = urls.list_for_owner(authenticated_username())
        return jsonify({"items": items, "count": len(items)}), 200

    @app.get("/<short_id>")
    def return_url(short_id: str) -> Response | tuple[Response, int]:
        record = urls.get(short_id)
        if record is None:
            return _error("not_found", "Short URL was not found", 404)
        return redirect(record["url"], code=302)

    @app.post("/")
    def add_url() -> tuple[Response, int]:
        username = authenticated_username()
        destination = _json_object({"url"})["url"]
        if not is_valid_url(destination):
            raise ApiError(400, "invalid_url", "URL must be an absolute HTTP or HTTPS URL")
        short_id = urls.add(destination, username)
        response = jsonify({"id": short_id, "url": destination})
        response.headers["Location"] = (
            f"{PUBLIC_PATH_PREFIX}/{short_id}"
            if PUBLIC_PATH_PREFIX
            else url_for("return_url", short_id=short_id)
        )
        return response, 201

    @app.put("/<short_id>")
    def update_url(short_id: str) -> tuple[Response, int] | tuple[str, int]:
        username = authenticated_username()
        destination = _json_object({"url"})["url"]
        if not is_valid_url(destination):
            raise ApiError(400, "invalid_url", "URL must be an absolute HTTP or HTTPS URL")
        outcome = urls.update_for_owner(short_id, destination, username)
        if outcome == "missing":
            return _error("not_found", "Short URL was not found", 404)
        if outcome == "forbidden":
            return _error("forbidden", "Short URL belongs to another user", 403)
        return "", 204

    @app.delete("/<short_id>")
    def delete_url(short_id: str) -> tuple[Response, int] | tuple[str, int]:
        outcome = urls.delete_for_owner(short_id, authenticated_username())
        if outcome == "missing":
            return _error("not_found", "Short URL was not found", 404)
        if outcome == "forbidden":
            return _error("forbidden", "Short URL belongs to another user", 403)
        return "", 204

    @app.delete("/")
    def delete_all_urls() -> tuple[Response, int]:
        deleted = urls.delete_all_for_owner(authenticated_username())
        return jsonify({"deleted": deleted}), 200

    return app


def main() -> None:
    """Run Flask's development server for local debugging only."""
    create_app().run(host=BIND_HOST, port=URL_SHORTENER_PORT)


if __name__ == "__main__":
    main()
