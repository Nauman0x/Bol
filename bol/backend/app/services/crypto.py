"""Encrypts secret header values (API keys, bearer tokens) an org enters for
a Tool (app/models/tool.py). Decryption only ever happens on the
/internal/agents/{id}/tools path the worker calls — every dashboard-facing
response masks these values instead (see app/schemas/tool.py).
"""

import json

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretsKeyNotConfigured(RuntimeError):
    """Raised instead of silently storing a secret in plaintext."""


def _fernet() -> Fernet:
    if not settings.secrets_key:
        raise SecretsKeyNotConfigured(
            "SECRETS_KEY is not set — cannot store an encrypted tool secret. "
            "Generate one with `python -c \"from cryptography.fernet import "
            "Fernet; print(Fernet.generate_key().decode())\"` and set it in .env."
        )
    return Fernet(settings.secrets_key.encode())


def encrypt_secrets(values: dict[str, str]) -> bytes:
    """values: {secret_ref: plaintext}. Raises SecretsKeyNotConfigured if no
    key is set — callers must not fall back to storing plaintext."""
    return _fernet().encrypt(json.dumps(values).encode())


def decrypt_secrets(blob: bytes | None) -> dict[str, str]:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob).decode())
    except InvalidToken:
        # Key rotated out from under existing rows — fail closed (no
        # secret values) rather than raising and taking a whole call down.
        return {}
