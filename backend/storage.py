"""Object storage used for tracker evidence and candidate resumes.

Production uses Emergent object storage. Its documented API only offers init, PUT and GET; there is no delete.
Resumes are therefore encrypted with a per-file key (see encrypt/decrypt below): destroying the key makes the
stored bytes permanently unreadable, and delete_object additionally overwrites the object.

STORAGE_BACKEND=local writes to a folder instead; it is for local development and tests only.
"""
import os
from pathlib import Path

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "jobradar"
_storage = {"key": None}


def _local_root():
    if (os.environ.get("STORAGE_BACKEND") or "").lower() != "local":
        return None
    root = Path(os.environ.get("LOCAL_STORAGE_DIR") or Path(__file__).parent / ".local_storage")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _local_path(path: str) -> Path:
    root = _local_root()
    p = (root / path).resolve()
    if root.resolve() not in p.parents:
        raise ValueError("Invalid storage path")
    return p


def _init_storage(force: bool = False):
    if _storage["key"] and not force:
        return _storage["key"]
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": os.environ.get("EMERGENT_LLM_KEY")}, timeout=30)
    resp.raise_for_status()
    _storage["key"] = resp.json()["storage_key"]
    return _storage["key"]


def _put_object(path: str, data: bytes, content_type: str) -> dict:
    if _local_root():
        p = _local_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return {"path": path, "size": len(data)}
    for attempt in (0, 1):
        resp = requests.put(f"{STORAGE_URL}/objects/{path}", data=data, timeout=120,
                            headers={"X-Storage-Key": _init_storage(force=attempt == 1), "Content-Type": content_type})
        if resp.status_code != 404:
            break
    resp.raise_for_status()
    return resp.json()


def _get_object(path: str) -> bytes:
    if _local_root():
        return _local_path(path).read_bytes()
    for attempt in (0, 1):
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", timeout=60,
                            headers={"X-Storage-Key": _init_storage(force=attempt == 1)})
        if resp.status_code != 404:
            break
    resp.raise_for_status()
    return resp.content


def delete_object(path: str) -> str:
    """Best-effort removal. Returns "deleted" if the store removed the object, else "overwritten" after
    replacing it with zero bytes. Callers must also destroy the file's encryption key."""
    if _local_root():
        _local_path(path).unlink(missing_ok=True)
        return "deleted"
    try:
        resp = requests.delete(f"{STORAGE_URL}/objects/{path}", timeout=30, headers={"X-Storage-Key": _init_storage()})
        if resp.status_code in (200, 202, 204):
            return "deleted"
    except requests.RequestException:
        pass
    _put_object(path, b"", "application/octet-stream")
    return "overwritten"


def check_storage() -> dict:
    """Reachability check for the admin storage panel."""
    if _local_root():
        return {"backend": "local", "reachable": True}
    try:
        _init_storage(force=True)
        return {"backend": "emergent", "reachable": True}
    except Exception as e:  # noqa: BLE001 - shown to admins as a diagnostic
        return {"backend": "emergent", "reachable": False, "error": str(e)[:200]}


def warm_storage(logger):
    if _local_root():
        return
    try:
        _init_storage()
    except Exception as e:
        logger.warning(f"Storage init failed: {e}")


# --------------------------------------------------------------------------- per-file encryption
def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt(key: bytes, blob: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], None)
