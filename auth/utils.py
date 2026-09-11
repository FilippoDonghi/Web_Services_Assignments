"""JWT creation and verification."""

from datetime import UTC, datetime, timedelta

import jwt


class TokenManager:
    """Issue and verify short-lived, HMAC-signed access tokens."""

    def __init__(self, secret: str, issuer: str, ttl_seconds: int) -> None:
        if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
            raise RuntimeError("JWT_SECRET must contain at least 32 bytes")
        if not isinstance(issuer, str) or not issuer:
            raise RuntimeError("TOKEN_ISSUER must not be empty")
        if ttl_seconds < 1:
            raise RuntimeError("TOKEN_TTL_SECONDS must be positive")

        self._secret = secret
        self._issuer = issuer
        self._ttl_seconds = ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def create(self, username: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": username,
                "iss": self._issuer,
                "iat": now,
                "exp": now + timedelta(seconds=self._ttl_seconds),
            },
            self._secret,
            algorithm="HS256",
        )

    def validate(self, token: str) -> str:
        payload = jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            issuer=self._issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        subject = payload["sub"]
        if not isinstance(subject, str) or not subject:
            raise jwt.InvalidTokenError("token subject is invalid")
        return subject
