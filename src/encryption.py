"""Fernet symmetric encryption for API keys at rest.

Generates a machine-local key on first use and stores it alongside the
encrypted data.  Anyone with filesystem access to both files can decrypt,
but the keys are protected if only providers.json is leaked.
"""

import logging
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet(data_dir: Path) -> Fernet:
    """Return a cached Fernet instance, generating the key file if needed."""
    global _fernet
    if _fernet is not None:
        return _fernet

    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / "fernet.key"

    if key_path.exists():
        key = key_path.read_bytes().strip()
    else:
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        key_path.chmod(0o600)
        log.info("Generated new encryption key at %s", key_path)

    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str, data_dir: Path) -> str:
    """Encrypt a string, returning a URL-safe base64 token."""
    f = _get_fernet(data_dir)
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str, data_dir: Path) -> str:
    """Decrypt a token back to the original string."""
    f = _get_fernet(data_dir)
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        log.error("Failed to decrypt value — key file may have changed")
        raise ValueError("Decryption failed — encryption key may have been regenerated")
