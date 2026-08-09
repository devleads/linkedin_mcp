"""Unit tests for security module (encrypt/decrypt)."""

import pytest
from cryptography.fernet import Fernet

from linkedin_mcp.security import encrypt_secret, decrypt_secret, _credential_fernet


class TestEncryptDecrypt:
    """Test round-trip encryption and edge cases."""

    def test_roundtrip(self, env_test):
        """Encrypt then decrypt should return the original value."""
        original = "my_secret_password_123"
        encrypted = encrypt_secret(original)
        assert encrypted is not None
        assert encrypted != original
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original

    def test_encrypt_none(self, env_test):
        """encrypt_secret(None) should return None."""
        assert encrypt_secret(None) is None

    def test_encrypt_empty_string(self, env_test):
        """encrypt_secret('') should return None (falsy)."""
        assert encrypt_secret("") is None

    def test_decrypt_none(self, env_test):
        """decrypt_secret(None) should return None."""
        assert decrypt_secret(None) is None

    def test_decrypt_empty_string(self, env_test):
        """decrypt_secret('') should return None (falsy)."""
        assert decrypt_secret("") is None

    def test_decrypt_invalid_token(self, env_test):
        """decrypt_secret with garbage should raise ValueError."""
        with pytest.raises(ValueError, match="Unable to decrypt"):
            decrypt_secret("not_a_valid_fernet_token")

    def test_encrypt_produces_different_ciphertexts(self, env_test):
        """Same plaintext should produce different ciphertexts (Fernet uses random IV)."""
        text = "same_password"
        ct1 = encrypt_secret(text)
        ct2 = encrypt_secret(text)
        assert ct1 != ct2
        assert decrypt_secret(ct1) == text
        assert decrypt_secret(ct2) == text

    def test_missing_encryption_key(self, monkeypatch):
        """Should raise ValueError when no encryption key is set."""
        monkeypatch.setenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", "")
        import linkedin_mcp.config as cfg
        cfg._settings = None
        with pytest.raises(ValueError, match="LINKEDIN_CREDENTIAL_ENCRYPTION_KEY is required"):
            encrypt_secret("test")

    def test_invalid_fernet_key(self, monkeypatch):
        """Should raise ValueError for invalid Fernet key."""
        monkeypatch.setenv("LINKEDIN_CREDENTIAL_ENCRYPTION_KEY", "not_a_valid_key")
        import linkedin_mcp.config as cfg
        cfg._settings = None
        with pytest.raises(ValueError, match="must be a valid Fernet key"):
            encrypt_secret("test")

    def test_unicode_roundtrip(self, env_test):
        """Unicode characters should survive encrypt/decrypt."""
        original = "пароль_密码_🔒"
        encrypted = encrypt_secret(original)
        decrypted = decrypt_secret(encrypted)
        assert decrypted == original
