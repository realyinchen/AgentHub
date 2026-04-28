"""
API key handling utilities.

API keys are encrypted using AES-GCM before storing in the database.
This provides security at rest, complementing HTTPS encryption in transit.
"""

import base64
import os
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _get_encryption_key() -> bytes:
    """Get the encryption key from environment variable.

    AES-GCM requires a 16, 24, or 32 byte key.
    We use SHA-256 to derive a 32-byte key from the secret.

    Raises:
        RuntimeError: In production mode, if API_KEY_ENCRYPTION_KEY is not set.
    """
    import hashlib

    encryption_key = os.getenv("API_KEY_ENCRYPTION_KEY")

    if encryption_key is None:
        # Check if we're in production mode
        env = os.getenv("ENVIRONMENT", os.getenv("PYTHON_ENV", "development")).lower()
        is_production = env in {"prod", "production"}

        if is_production:
            raise RuntimeError(
                "API_KEY_ENCRYPTION_KEY must be set in production mode. "
                "Please set this environment variable to a secure random string."
            )

        # Development mode: use a default key and issue a warning
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(
            "Using default API_KEY_ENCRYPTION_KEY in development mode. "
            "This is NOT secure for production!"
        )
        encryption_key = "AgentHub2026SecureKey!@#$%"

    # Derive a 32-byte key using SHA-256
    return hashlib.sha256(encryption_key.encode("utf-8")).digest()


def encrypt_api_key(plain_key: str) -> str:
    """
    Encrypt an API key using AES-GCM.

    Args:
        plain_key: Plain text API key

    Returns:
        Base64 encoded encrypted key (IV + ciphertext)
    """
    if not plain_key:
        return ""

    # Generate a random 12-byte IV
    iv = secrets.token_bytes(12)

    # Get encryption key
    key_bytes = _get_encryption_key()

    # Encrypt using AES-GCM
    aesgcm = AESGCM(key_bytes)
    ciphertext = aesgcm.encrypt(iv, plain_key.encode("utf-8"), None)

    # Combine IV and ciphertext, then base64 encode
    combined = iv + ciphertext
    return base64.b64encode(combined).decode("utf-8")


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key that was encrypted with AES-GCM.

    For legacy compatibility, also handles plaintext keys (keys starting with
    common API key prefixes like "sk-" or "api-").

    Args:
        encrypted_key: The encrypted API key (base64 encoded) or plaintext key

    Returns:
        The decrypted API key string
    """
    if not encrypted_key:
        return ""

    # Check if this looks like a plaintext key (not encrypted)
    if encrypted_key.startswith("sk-") or encrypted_key.startswith("api-"):
        return encrypted_key

    try:
        # Decode base64
        combined = base64.b64decode(encrypted_key)

        # Check if it has the expected format (at least 12 bytes IV + some ciphertext + 16 bytes tag)
        if len(combined) < 28:
            # Too short to be encrypted, return as-is
            return encrypted_key

        # Extract IV (first 12 bytes) and ciphertext (rest)
        iv = combined[:12]
        ciphertext = combined[12:]

        # Get encryption key
        key_bytes = _get_encryption_key()

        # Decrypt
        aesgcm = AESGCM(key_bytes)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)

        return plaintext.decode("utf-8")

    except Exception:
        # Not an encrypted key or decryption failed
        # Return as-is (it might be a plaintext key)
        return encrypted_key
