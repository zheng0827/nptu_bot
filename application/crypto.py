"""3DES-ECB parameter encryption with exact JavaScript encodeURIComponent parity."""
from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import quote

from Crypto.Cipher import DES3
from Crypto.Util.Padding import pad


def js_encode_uri_component(value: Any) -> str:
    """Replicate JavaScript encodeURIComponent encoding rules."""
    return quote(str(value), safe="-_.!~*'()", encoding="utf-8", errors="strict")


def serialize_params(params: Mapping[str, Any]) -> str:
    """Serialize ordered key-value pairs omitting None, empty strings, and 'method'."""
    return "&".join(
        f"{js_encode_uri_component(k)}={js_encode_uri_component(v)}"
        for k, v in params.items()
        if k != "method" and v is not None and v != ""
    )


def encrypt_path_params(params: Mapping[str, Any], key: str) -> str:
    """Encrypt serialized params using 3DES-ECB + PKCS7 padding and return lowercase hex."""
    if not key:
        raise ValueError("NPTU_APP_3DES_KEY is not configured in .env")
    key_bytes = key.encode("utf-8")
    if len(key_bytes) != 24:
        raise ValueError("NPTU_APP_3DES_KEY must be exactly 24 UTF-8 bytes")
    cipher = DES3.new(key_bytes, DES3.MODE_ECB)
    raw = serialize_params(params).encode("utf-8")
    return cipher.encrypt(pad(raw, DES3.block_size)).hex()
