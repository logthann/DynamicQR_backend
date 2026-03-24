"""OAuth token encryption helpers using Fernet symmetric cryptography."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class TokenCryptoError(Exception):
    """Raised when token encryption/decryption fails."""


class OAuthTokenCrypto:
    """Encrypt and decrypt third-party OAuth tokens for at-rest storage."""

    def __init__(self, encryption_key: str) -> None:
        try:
            self._fernet = Fernet(encryption_key.encode("utf-8"))
        except ValueError as exc:
            raise TokenCryptoError(
                "Invalid OAUTH_TOKEN_ENCRYPTION_KEY; expected Fernet key format",
            ) from exc

    def encrypt_token(self, token: str) -> str:
        """Encrypt a raw provider token for database persistence."""

        try:
            encrypted = self._fernet.encrypt(token.encode("utf-8"))
        except Exception as exc:  # pragma: no cover - cryptography internal failure
            raise TokenCryptoError("Failed to encrypt OAuth token") from exc
        return encrypted.decode("utf-8")

    def decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt an encrypted provider token read from storage."""

        try:
            decrypted = self._fernet.decrypt(encrypted_token.encode("utf-8"))
        except InvalidToken as exc:
            raise TokenCryptoError("Invalid encrypted OAuth token payload") from exc
        except Exception as exc:  # pragma: no cover - cryptography internal failure
            raise TokenCryptoError("Failed to decrypt OAuth token") from exc
        return decrypted.decode("utf-8")


_token_crypto: OAuthTokenCrypto | None = None


def get_token_crypto() -> OAuthTokenCrypto:
    """Return singleton token crypto helper configured from settings."""

    global _token_crypto

    if _token_crypto is None:
        settings = get_settings()
        _token_crypto = OAuthTokenCrypto(
            encryption_key=settings.oauth_token_encryption_key,
        )
    return _token_crypto


def reset_token_crypto() -> None:
    """Reset singleton token crypto helper, primarily for tests."""

    global _token_crypto
    _token_crypto = None

