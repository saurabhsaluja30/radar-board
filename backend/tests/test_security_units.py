# Unit tests for the consolidation security fixes. No backend, database or network needed.
import base64
import os
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import payments  # noqa: E402
import ratelimit  # noqa: E402
import storage  # noqa: E402


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ratelimit.reset()
    for k in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_API_BASE", "RESUME_KEK", "RATE_LIMITS"):
        monkeypatch.delenv(k, raising=False)
    yield
    ratelimit.reset()


def test_rate_limit_blocks_after_limit_and_is_per_key():
    for _ in range(3):
        ratelimit.check("login:ip:1.2.3.4", 3, 60)
    with pytest.raises(HTTPException) as e:
        ratelimit.check("login:ip:1.2.3.4", 3, 60)
    assert e.value.status_code == 429 and int(e.value.headers["Retry-After"]) >= 1
    ratelimit.check("login:ip:5.6.7.8", 3, 60)  # another client is unaffected


def test_razorpay_base_override_only_for_test_keys_on_localhost(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "s")
    monkeypatch.setenv("RAZORPAY_API_BASE", "http://127.0.0.1:8790/v1")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_x")
    assert payments.api_base() == "http://127.0.0.1:8790/v1"
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_x")
    assert payments.api_base() == payments.API, "live keys must never go to an override host"
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_x")
    monkeypatch.setenv("RAZORPAY_API_BASE", "https://evil.example.com/v1")
    assert payments.api_base() == payments.API, "non-loopback hosts are ignored"


def test_resume_key_wrapping_round_trip(monkeypatch):
    monkeypatch.setenv("RESUME_KEK", base64.b64encode(os.urandom(32)).decode())
    key = storage.new_key()
    rec = {"enc_key_wrapped": storage.wrap_key(key)}
    assert storage.unwrap_key(rec) == key
    assert base64.b64decode(rec["enc_key_wrapped"]) != key
    blob = storage.encrypt(key, b"resume bytes")
    assert storage.decrypt(storage.unwrap_key(rec), blob) == b"resume bytes"


def test_wrapped_key_unreadable_without_or_with_wrong_master(monkeypatch):
    monkeypatch.setenv("RESUME_KEK", base64.b64encode(os.urandom(32)).decode())
    rec = {"enc_key_wrapped": storage.wrap_key(storage.new_key())}
    monkeypatch.delenv("RESUME_KEK")
    with pytest.raises(RuntimeError):
        storage.unwrap_key(rec)
    monkeypatch.setenv("RESUME_KEK", base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(Exception):
        storage.unwrap_key(rec)


def test_legacy_plain_key_still_readable_and_destroyed_key_is_none():
    key = storage.new_key()
    assert storage.unwrap_key({"enc_key": base64.b64encode(key).decode()}) == key
    assert storage.unwrap_key({}) is None


def test_bad_kek_length_rejected(monkeypatch):
    monkeypatch.setenv("RESUME_KEK", base64.b64encode(b"short").decode())
    with pytest.raises(ValueError):
        storage.kek()
