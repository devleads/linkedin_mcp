from cryptography.fernet import Fernet, InvalidToken

from linkedin_mcp.config import get_settings


ENVELOPE_PREFIX = "fernet:v1:"


def _credential_fernet() -> Fernet:
    key = get_settings().linkedin_credential_encryption_key.strip()
    if not key:
        raise ValueError("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY is required for LinkedIn credential encryption")
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        raise ValueError("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from exc


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _credential_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _credential_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt LinkedIn credential with configured encryption key") from exc


def encrypt_envelope(value: str | None) -> str | None:
    """Encrypt a value with a version marker for safe legacy detection."""
    encrypted = encrypt_secret(value)
    return f"{ENVELOPE_PREFIX}{encrypted}" if encrypted else None


def decrypt_envelope(value: str | None) -> str | None:
    """Decrypt a versioned value, accepting legacy plaintext during migration."""
    if not value:
        return None
    if not value.startswith(ENVELOPE_PREFIX):
        return value
    return decrypt_secret(value[len(ENVELOPE_PREFIX):])
