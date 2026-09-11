"""Environment-backed configuration for the authentication service."""

import os

BIND_HOST = os.environ.get("BIND_HOST", "0.0.0.0")
AUTH_SERVICE_PORT = int(os.environ.get("AUTH_SERVICE_PORT", "5001"))
TOKEN_ISSUER = os.environ.get("TOKEN_ISSUER", "url-shortener-auth")
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", "3600"))
