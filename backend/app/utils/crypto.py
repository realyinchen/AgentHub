"""
API key handling utilities.

Note: API keys are now stored as-is (plaintext) in the database.
HTTPS provides encryption in transit, and the database should be
properly secured at rest (e.g., encrypted disk, field-level encryption).

For legacy compatibility, this module still provides decryption for
keys that were previously encrypted with AES-GCM.
"""

import base64


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Return the API key as-is (no longer encrypted by frontend).

    For legacy compatibility, attempts to decrypt AES-GCM encrypted keys
    if the key appears to be encrypted (base64 with IV prefix).

    Args:
        encrypted_key: The API key (plaintext or legacy encrypted format)

    Returns:
        The API key string
    """
    if not encrypted_key:
        return ""

    # Check if this looks like a legacy encrypted key (base64 with 12-byte IV prefix)
    # Legacy keys were base64 encoded with IV + ciphertext format
    # They typically start with random bytes, not "sk-" or other API key prefixes
    if encrypted_key.startswith("sk-") or encrypted_key.startswith("api-"):
        # This is a plaintext API key, return as-is
        return encrypted_key

    # Try to detect if this is a legacy encrypted key
    try:
        import os
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        # Decode base64
        combined = base64.b64decode(encrypted_key)

        # Check if it has the expected format (at least 12 bytes IV + some ciphertext)
        if len(combined) < 13:
            # Too short to be encrypted, return as-is
            return encrypted_key

        # Extract IV (first 12 bytes) and ciphertext
        iv = combined[:12]
        ciphertext = combined[12:]

        # Get encryption key
        encryption_key = os.getenv(
            "API_KEY_ENCRYPTION_KEY", "AgentHub2026SecureKey!@#$%"
        )
        key_bytes = encryption_key.encode("utf-8")

        # Try to decrypt
        aesgcm = AESGCM(key_bytes)
        plaintext = aesgcm.decrypt(iv, ciphertext, None)

        return plaintext.decode("utf-8")

    except Exception:
        # Not a legacy encrypted key or decryption failed
        # Return as-is (it's a plaintext key)
        return encrypted_key


def encrypt_api_key(plain_key: str) -> str:
    """
    No-op for compatibility. Returns the key as-is.

    Note: We no longer encrypt API keys. HTTPS provides transport security.

    Args:
        plain_key: Plain text API key

    Returns:
        The same API key (no encryption)
    """
    return plain_key
