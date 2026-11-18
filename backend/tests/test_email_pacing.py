# JobRadar email pacing: bulk announcement (paced, background), resend-skip, retryable/retry-failed, RBAC, welcome regression
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@eevolvex.com", "password": "Admin@12345"}
CAND = {"email": "test@jobradar.com", "password": "Test@12345"}
N = int(os.environ.get("PACE_N", "12"))


def _env(path, key):
    for line in open(path):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


MONGO = MongoClient(_env("/app/backend/.env", "MONGO_URL"))[_env("/app/backend/.env", "DB_NAME")]
UID = uuid.uuid4().hex[:6]
SUBJECT = f"TEST_Announcement {UID}"
STATE = {"users": [], "emails": [], "inserted_log_ids": [], "suspended_real": []}


def _sess(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/admin/login", json=ADMIN)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return _sess(r.json()["token"])


@pytest.fixture(scope="module")
def cands():
    # Temporarily exclude real (non-test, non-seeded) candidates so the test announcement doesn't email real people
    real = list(MONGO.users.find({"role": "candidate", "suspended": {"$ne": True},
                                  "email": {"$not": {"$regex": "example\\.com$|^test@jobradar\\.com$"}}},
                                 {"_id": 0, "user_id": 1}))
    STATE["suspended_real"] = [u["user_id"] for u in real]
    if STATE["suspended_real"]:
        MONGO.users.update_many({"user_id": {"$in": STATE["suspended_real"]}}, {"$set": {"suspended": True}})
    t0 = time.time()
    for i in range(N):
        email = f"test_pace_{i}_{UID}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "full_name": f"TEST_PACE {i}", "email": email, "mobile": "9876543210", "password": "Test@123",
            "confirm_password": "Test@123", "industry": "IT & Technology", "current_designation": "Engineer",
            "current_salary": "10 LPA", "preferred_location": "Bengaluru", "preferred_work_mode": "Remote",
            "consent": True}, timeout=90)
        assert r.status_code == 200, r.text
        STATE["users"].append(r.json()["user"]["user_id"])
        STATE["emails"].append(email)
    print(f"registered {N} in {time.time() - t0:.1f}s")
    yield STATE["users"]
    try:
        ids = STATE["users"]
        for coll in ("subscriptions", "user_sessions", "email_logs", "payments", "consent_records"):
            MONGO[coll].delete_many({"candidate_id": {"$in": ids}})
            MONGO[coll].delete_many({"user_id": {"$in": ids}})
        MONGO.email_logs.delete_many({"email_id": {"$in": STATE["inserted_log_ids"]}})
        MONGO.email_logs.delete_many({"subject": SUBJECT, "to": {"$regex": f"{UID}@example\\.com$|^test@jobradar\\.com$"}})
        MONGO.users.delete_many({"user_id": {"$in": ids}})
        granted = MONGO.users.count_documents({"launch_offer": "granted"})
        MONGO.app_settings.update_one({"key": "launch_offer"}, {"$set": {"granted": granted}})
    finally:
        if STATE["suspended_real"]:
            MONGO.users.update_many({"user_id": {"$in": STATE["suspended_real"]}}, {"$set": {"suspended": False}})


class TestEmailPacing:
    def test_welcome_emails_logged(self, cands):
        # welcome email is sent in background (429 -> 3s backoff), so poll
        for _ in range(30):
            logs = list(MONGO.email_logs.find({"candidate_id": {"$in": cands}, "email_type": "welcome"}, {"_id": 0}))
            if len(logs) >= N:
                break
            time.sleep(2)
        assert len(logs) == N
        statuses = [l["delivery_status"] for l in logs]
        print("welcome statuses:", statuses, [l.get("error_message") for l in logs if l["delivery_status"] != "sent"])
        # when provider is quota-limited, failures must be retryable with a friendly message
        for l in logs:
            if l["delivery_status"] == "failed":
                raw = MONGO.email_logs.find_one({"email_id": l["email_id"]})
                assert "retry_html" in raw and "rate limit" in (l.get("error_message") or "").lower()
        assert all(s in ("sent", "failed") for s in statuses), statuses

    def test_announcement_queues_fast_and_delivers(self, admin, cands):
        t0 = time.time()
        r = admin.post(f"{API}/admin/announcement", json={"subject": SUBJECT, "message": "Pacing test"})
        elapsed = time.time() - t0
        assert r.status_code == 200, r.text
        d = r.json()
        print("announce resp", d, f"{elapsed:.2f}s")
        assert elapsed < 5
        assert d["queued"] >= N and d["skipped_already_received"] == 0
        STATE["queued1"] = d["queued"]
        deadline = time.time() + float(os.environ.get("PACE_WAIT", "90"))
        while time.time() < deadline:
            logs = list(MONGO.email_logs.find({"subject": SUBJECT}, {"_id": 0}))
            if len(logs) >= d["queued"]:
                break
            time.sleep(3)
        logs = list(MONGO.email_logs.find({"subject": SUBJECT}, {"_id": 0}))
        print(f"after {time.time() - t0:.1f}s: {len(logs)} logs", [(l["delivery_status"], l.get("error_message")) for l in logs if l["delivery_status"] != "sent"])
        assert len(logs) == d["queued"]
        failed = [l for l in logs if l["delivery_status"] == "failed"]
        for l in failed:
            assert "retry_html" in MONGO.email_logs.find_one({"email_id": l["email_id"]})
        # provider quota (~10/window) -> failed-with-retry is acceptable; cron /api/cron/email-retry re-sends later
        assert all(l["delivery_status"] in ("sent", "failed") for l in logs)

    def test_resend_same_subject_skips(self, admin, cands):
        # dedupe covers sent + failed-with-retry recipients
        sent = len(MONGO.email_logs.distinct("candidate_id", {"subject": SUBJECT, "$or": [{"delivery_status": "sent"}, {"delivery_status": "failed", "retry_html": {"$exists": True}}]}))
        r = admin.post(f"{API}/admin/announcement", json={"subject": SUBJECT, "message": "Pacing test"})
        assert r.status_code == 200
        d = r.json()
        print("resend", d)
        assert d["skipped_already_received"] == sent
        assert d["queued"] == STATE["queued1"] - sent

    def test_admin_emails_shape(self, admin, cands):
        r = admin.get(f"{API}/admin/emails")
        assert r.status_code == 200
        d = r.json()
        assert isinstance(d["retryable"], int)
        assert all("retry_html" not in e and "_id" not in e for e in d["emails"])

    def test_retry_failed(self, admin, cands):
        eid = f"email_test{UID}"
        STATE["inserted_log_ids"].append(eid)
        before = admin.get(f"{API}/admin/emails").json()["retryable"]
        MONGO.email_logs.insert_one({
            "email_id": eid, "candidate_id": cands[0], "to": STATE["emails"][0], "email_type": "announcement",
            "subject": f"TEST_Retry {UID}", "date_sent": "2026-01-01T00:00:00+00:00", "delivery_status": "failed",
            "error_message": "Email service rate limit reached — use Retry failed", "created_at": "2026-01-01T00:00:00+00:00",
            "retry_html": "<p>TEST retry</p>"})
        d = admin.get(f"{API}/admin/emails").json()
        assert d["retryable"] == before + 1
        row = next(e for e in d["emails"] if e["email_id"] == eid)
        assert "retry_html" not in row
        r = admin.post(f"{API}/admin/emails/retry-failed")
        assert r.status_code == 200
        assert r.json()["queued"] >= 1
        orig = MONGO.email_logs.find_one({"email_id": eid})
        assert orig["delivery_status"] == "retried" and "retry_html" not in orig
        new = None
        for _ in range(int(os.environ.get("PACE_WAIT", "90")) // 2):
            new = MONGO.email_logs.find_one({"subject": f"TEST_Retry {UID}", "email_id": {"$ne": eid}})
            if new:
                break
            time.sleep(2)
        assert new is not None
        print("retry new log", new["delivery_status"], new.get("error_message"))
        STATE["inserted_log_ids"].append(new["email_id"])
        assert new["delivery_status"] in ("sent", "failed"), new.get("error_message")

    def test_candidate_forbidden(self, cands):
        r = requests.post(f"{API}/auth/login", json=CAND)
        if r.status_code != 200:
            pytest.skip("candidate login failed")
        s = _sess(r.json()["token"])
        assert s.get(f"{API}/admin/emails").status_code == 403
        assert s.post(f"{API}/admin/announcement", json={"subject": "x", "message": "y"}).status_code == 403
        assert s.post(f"{API}/admin/emails/retry-failed").status_code == 403

    def test_unauth(self):
        assert requests.get(f"{API}/admin/emails").status_code == 401
        assert requests.post(f"{API}/admin/emails/retry-failed").status_code == 401
