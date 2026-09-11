"""Authentication service application factory."""

import os
import re
from pathlib import Path
from typing import Any

import jwt
from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from .config import AUTH_SERVICE_PORT, BIND_HOST, TOKEN_ISSUER, TOKEN_TTL_SECONDS
from .users import UserStore
from .utils import TokenManager

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_LENGTH = 12


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


def _credentials(data: dict[str, Any], *, require_strong_password: bool = True) -> tuple[str, str]:
    username = data["username"]
    password = data["password"]
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        raise ApiError(
            400,
            "invalid_username",
            "Username must be 3-64 characters using letters, numbers, dot, dash, or underscore",
        )
    minimum_length = MIN_PASSWORD_LENGTH if require_strong_password else 1
    if not isinstance(password, str) or not minimum_length <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ApiError(
            400,
            "invalid_password",
            f"Password must be {minimum_length}-{MAX_PASSWORD_LENGTH} characters",
        )
    return username, password


def create_app(instance_path: str | None = None, jwt_secret: str | None = None) -> Flask:
    resolved_instance = Path(
        instance_path
        or os.environ.get("INSTANCE_PATH")
        or Path(__file__).resolve().parent / "instance"
    ).resolve()
    app = Flask(__name__, instance_path=str(resolved_instance), instance_relative_config=True)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    secret = jwt_secret if jwt_secret is not None else os.environ.get("JWT_SECRET")
    if secret is None:
        raise RuntimeError("JWT_SECRET is required")

    users = UserStore(app.instance_path)
    tokens = TokenManager(secret, TOKEN_ISSUER, TOKEN_TTL_SECONDS)
    app.extensions["user_store"] = users
    app.extensions["token_manager"] = tokens

    @app.errorhandler(ApiError)
    def handle_api_error(exc: ApiError) -> tuple[Response, int]:
        return _error(exc.code, exc.message, exc.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException) -> tuple[Response, int]:
        return _error(exc.name.lower().replace(" ", "_"), exc.description, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception) -> tuple[Response, int]:
        app.logger.exception("Unhandled authentication service error", exc_info=exc)
        return _error("internal_error", "An unexpected error occurred", 500)

    @app.after_request
    def prevent_sensitive_response_caching(response: Response) -> Response:
        if request.path in {"/users/login", "/users/password", "/validate"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    def health() -> tuple[Response, int]:
        return jsonify({"status": "ok"}), 200

    @app.post("/users")
    def create_user() -> tuple[Response, int]:
        username, password = _credentials(_json_object({"username", "password"}))
        if not users.create(username, password):
            return _error("username_exists", "Username is already registered", 409)
        return jsonify({"username": username}), 201

    @app.post("/users/login")
    def login_user() -> tuple[Response, int]:
        username, password = _credentials(
            _json_object({"username", "password"}), require_strong_password=False
        )
        if not users.authenticate(username, password):
            response, status = _error("invalid_credentials", "Invalid username or password", 401)
            response.headers["WWW-Authenticate"] = "Bearer"
            return response, status
        return (
            jsonify(
                {
                    "access_token": tokens.create(username),
                    "token_type": "Bearer",
                    "expires_in": tokens.ttl_seconds,
                }
            ),
            200,
        )

    @app.put("/users/password")
    def update_password() -> tuple[Response, int] | tuple[str, int]:
        data = _json_object({"username", "old_password", "new_password"})
        username = data["username"]
        old_password = data["old_password"]
        new_password = data["new_password"]
        _credentials(
            {"username": username, "password": old_password}, require_strong_password=False
        )
        _credentials({"username": username, "password": new_password})
        if not users.update_password(username, old_password, new_password):
            return _error("invalid_credentials", "Invalid username or password", 401)
        return "", 204

    @app.post("/validate")
    def validate_token() -> tuple[Response, int]:
        token = _json_object({"token"})["token"]
        if not isinstance(token, str) or not token or len(token) > 4096:
            return _error("invalid_token", "Token is invalid or expired", 401)
        try:
            username = tokens.validate(token)
        except jwt.InvalidTokenError:
            return _error("invalid_token", "Token is invalid or expired", 401)
        if not users.exists(username):
            return _error("invalid_token", "Token is invalid or expired", 401)
        return jsonify({"username": username}), 200

    return app


def main() -> None:
    """Run Flask's development server for local debugging only."""
    create_app().run(host=BIND_HOST, port=AUTH_SERVICE_PORT)


if __name__ == "__main__":
    main()
