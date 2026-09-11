"""Environment-backed configuration for the URL shortener service."""

import os

BIND_HOST = os.environ.get("BIND_HOST", "0.0.0.0")
URL_SHORTENER_PORT = int(os.environ.get("URL_SHORTENER_PORT", "5000"))
PUBLIC_PATH_PREFIX = os.environ.get("PUBLIC_PATH_PREFIX", "").rstrip("/")
