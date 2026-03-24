"""Tests for OAuth token encryption helpers."""

from __future__ import annotations

import pytest

from app.core.token_crypto import OAuthTokenCrypto, TokenCryptoError


FERNET_TEST_KEY = "oTP_EcEzN_G9ksvcjmcBbN1q8A5xj9Pf3Y8V97tXWW0="


def test_encrypt_decrypt_roundtrip() -> None:
    crypto = OAuthTokenCrypto(FERNET_TEST_KEY)

    raw_token = "ya29.a0AWY7CkkExample"
    encrypted = crypto.encrypt_token(raw_token)

    assert encrypted != raw_token
    assert crypto.decrypt_token(encrypted) == raw_token


def test_decrypt_invalid_payload_raises_token_crypto_error() -> None:
    crypto = OAuthTokenCrypto(FERNET_TEST_KEY)

    with pytest.raises(TokenCryptoError, match="Invalid encrypted OAuth token payload"):
        crypto.decrypt_token("not-a-valid-token")

