# JobRadar: Success Tracker, Demand/Registration analytics, cron reminders, launch-offer privacy
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient
from envutil import env_value  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}




CRON_SECRET = env_value("WEBHOOK_CRON_SECRET")
MONGO_URL = env_value("MONGO_URL")
DB_NAME = env_value("DB_NAME")
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/admin/login", json=ADMIN)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def cand():
    uid = uuid.uuid4().hex[:8]
    r = requests.post(f"{API}/auth/register", json={
        "full_name": f"TEST_Tracker {uid}", "email": f"test_trk_{uid}@example.com", "mobile": "9876543210",
        "password": "Test@1234", "confirm_password": "Test@1234", "industry": "IT & Technology",
        "current_designation": "Engineer", "current_salary": "8 LPA", "preferred_location": "Dubai",
        "preferred_work_mode": "Remote", "consent": True, "preferred_industries": ["IT & Technology", "HR & Recruitment"],
    })
    assert r.status_code == 200, r.text
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s, r.json()["user"]


@pytest.fixture(scope="module")
def job_id():
    r = requests.get(f"{API}/jobs")
    assert r.status_code == 200
    d = r.json()
    jobs = d.get("jobs") if isinstance(d, dict) else d
    assert jobs
    return jobs[0]["job_id"]


@pytest.fixture(scope="module")
def tracker(cand, job_id):
    s, _ = cand
    r = s.post(f"{API}/tracker", json={"job_id": job_id})
    assert r.status_code == 200, r.text
    return r.json()["item"]


class TestPublic:
    def test_launch_offer_no_counts(self):
        d = requests.get(f"{API}/launch-offer").json()
        assert "spots_left" not in d and "spots_total" not in d and "granted" not in d and "free_spots" not in d
        assert isinstance(d["spots_available"], bool)


class TestTracker:
    def test_track_idempotent(self, cand, job_id, tracker):
        s, _ = cand
        r = s.post(f"{API}/tracker", json={"job_id": job_id})
        assert r.json()["item"]["tracker_id"] == tracker["tracker_id"]
        items = s.get(f"{API}/tracker").json()["items"]
        assert len([i for i in items if i["job_id"] == job_id]) == 1
        assert tracker["status"] == "interested"

    def test_track_unknown_job(self, cand):
        assert cand[0].post(f"{API}/tracker", json={"job_id": "nope_x"}).status_code == 404

    def test_tracker_for_job(self, cand, job_id, tracker):
        d = cand[0].get(f"{API}/tracker/job/{job_id}").json()
        assert d["item"]["tracker_id"] == tracker["tracker_id"]

    def test_interview_requires_fields(self, cand, tracker):
        s = cand[0]
        r = s.put(f"{API}/tracker/{tracker['tracker_id']}/status", json={"status": "interview_scheduled"})
        assert r.status_code == 400
        r = s.put(f"{API}/tracker/{tracker['tracker_id']}/status", json={"status": "interview_scheduled", "interview_date": "2026-02-10", "interview_mode": "Bogus"})
        assert r.status_code == 400

    def test_status_flow(self, cand, tracker):
        s, tid = cand[0], tracker["tracker_id"]
        assert s.put(f"{API}/tracker/{tid}/status", json={"status": "contacted"}).status_code == 200
        assert s.put(f"{API}/tracker/{tid}/status", json={"status": "applied"}).status_code == 200
        r = s.put(f"{API}/tracker/{tid}/status", json={"status": "interview_scheduled", "interview_date": "2026-02-10",
                                                      "interview_mode": "Video", "interview_company": "TEST_Co"})
        assert r.status_code == 200, r.text
        it = r.json()["item"]
        assert it["interview"]["mode"] == "Video" and it["interview_verification"] == "candidate_reported"
        assert [h["status"] for h in it["status_history"]] == ["interested", "contacted", "applied", "interview_scheduled"]
        assert all(h["at"] for h in it["status_history"])
        assert s.put(f"{API}/tracker/{tid}/status", json={"status": "bogus"}).status_code == 400

    def test_hired_requires_fields(self, cand, tracker):
        s, tid = cand[0], tracker["tracker_id"]
        assert s.put(f"{API}/tracker/{tid}/status", json={"status": "hired", "hire_company": "X"}).status_code == 400

    def test_evidence_validation(self, cand, tracker):
        s, tid = cand[0], tracker["tracker_id"]
        u = f"{API}/tracker/{tid}/evidence"
        r = s.post(u, data={"kind": "interview_invite", "redacted": "false"}, files={"file": ("a.pdf", PDF, "application/pdf")})
        assert r.status_code == 400
        r = s.post(u, data={"kind": "interview_invite", "redacted": "true"}, files={"file": ("a.txt", b"hi", "text/plain")})
        assert r.status_code == 400
        r = s.post(u, data={"kind": "interview_invite", "redacted": "true"}, files={"file": ("a.pdf", b"%PDF" + b"0" * (5 * 1024 * 1024 + 10), "application/pdf")})
        assert r.status_code == 400
        r = s.post(u, data={"kind": "weird", "redacted": "true"}, files={"file": ("a.pdf", PDF, "application/pdf")})
        assert r.status_code == 400

    def test_evidence_upload_and_admin_view(self, cand, tracker, admin):
        s, tid = cand[0], tracker["tracker_id"]
        r = s.post(f"{API}/tracker/{tid}/evidence", data={"kind": "interview_invite", "redacted": "true"},
                   files={"file": ("TEST_invite.pdf", PDF, "application/pdf")})
        assert r.status_code == 200, r.text
        ev = r.json()["evidence_id"]
        assert s.get(f"{API}/admin/success/evidence/{ev}").status_code == 403
        r = admin.get(f"{API}/admin/success/evidence/{ev}")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_reminder_and_dismiss(self, cand, tracker, db):
        s, tid = cand[0], tracker["tracker_id"]
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        db.job_tracker.update_one({"tracker_id": tid}, {"$set": {"updated_at": old}})
        it = [i for i in s.get(f"{API}/tracker").json()["items"] if i["tracker_id"] == tid][0]
        assert it["reminder"] and it["reminder"]["days"] == 7
        assert s.post(f"{API}/tracker/{tid}/dismiss-reminder").status_code == 200
        it = [i for i in s.get(f"{API}/tracker").json()["items"] if i["tracker_id"] == tid][0]
        assert it["reminder"] is None

    def test_other_user_cannot_touch(self, tracker, admin):
        assert admin.put(f"{API}/tracker/{tracker['tracker_id']}/status", json={"status": "applied"}).status_code == 404


class TestAdminAccess:
    @pytest.mark.parametrize("path", ["/admin/success", "/admin/analytics/demand", "/admin/analytics/registration",
                                      "/admin/analytics/candidates/export", "/admin/success/export",
                                      "/admin/analytics/candidates", "/admin/success/evidence/ev_x"])
    def test_candidate_forbidden(self, cand, path):
        assert cand[0].get(f"{API}{path}").status_code == 403

    def test_unauth(self):
        assert requests.get(f"{API}/admin/success").status_code in (401, 403)


class TestAnalytics:
    def test_registration_matches_db(self, admin, db):
        d = admin.get(f"{API}/admin/analytics/registration").json()
        total = db.users.count_documents({"role": "candidate"})
        paid = len(set(db.payments.distinct("candidate_id", {"status": "successful"})) &
                   set(db.users.distinct("user_id", {"role": "candidate"})))
        assert d["total_registered"] == total
        assert d["paid"] == paid
        assert d["free_registered"] == total - paid

    def test_demand_shape_and_preferred(self, admin, cand):
        d = admin.get(f"{API}/admin/analytics/demand").json()
        assert d["total_candidates"] >= 1
        cur = {r["name"]: r for r in d["current_industry"]}
        pref = {r["name"]: r for r in d["preferred_industry"]}
        assert cur["IT & Technology"]["count"] >= 1 and pref["HR & Recruitment"]["count"] >= 1
        assert sum(r["count"] for r in d["current_industry"]) == d["total_candidates"]
        assert all(r["level"] in ("High", "Moderate", "Low") for r in d["recommendations"])

    def test_demand_filter(self, admin):
        allc = admin.get(f"{API}/admin/analytics/demand").json()["total_candidates"]
        f = admin.get(f"{API}/admin/analytics/demand", params={"membership": "Paid"}).json()["total_candidates"]
        assert f <= allc
        assert admin.get(f"{API}/admin/analytics/demand", params={"start": "bad"}).status_code == 400

    def test_candidates_list_and_export(self, admin, cand):
        email = cand[1]["email"]
        d = admin.get(f"{API}/admin/analytics/candidates", params={"industry": "HR & Recruitment", "dimension": "preferred"}).json()
        assert email in [c["email"] for c in d["candidates"]]
        r = admin.get(f"{API}/admin/analytics/candidates/export", params={"industry": "IT & Technology"})
        assert r.status_code == 200 and "text/csv" in r.headers["content-type"] and email in r.text

    def test_success_and_verify(self, admin, tracker, cand):
        tid = tracker["tracker_id"]
        cand[0].put(f"{API}/tracker/{tid}/status", json={"status": "interview_scheduled", "interview_date": "2026-02-10", "interview_mode": "Video"})
        d = admin.get(f"{API}/admin/success", params={"job_id": tracker["job_id"]}).json()
        rec = [x for x in d["records"] if x["tracker_id"] == tid][0]
        assert rec["candidate_email"] == cand[1]["email"]
        assert d["totals"]["interview_scheduled"]["records"] >= 1
        conv = {c["label"]: c for c in d["conversions"]}
        c = conv["Applied → Interview Scheduled"]
        assert c["numerator"] <= c["denominator"]
        before = admin.get(f"{API}/admin/success").json()["verification"]["interview_verified"]
        r = admin.post(f"{API}/admin/success/{tid}/verify", json={"kind": "interview", "verified": True})
        assert r.status_code == 200, r.text
        after = admin.get(f"{API}/admin/success").json()["verification"]["interview_verified"]
        assert after == before + 1
        assert admin.post(f"{API}/admin/success/{tid}/verify", json={"kind": "hire", "verified": True}).status_code == 400
        r = admin.get(f"{API}/admin/success/export", params={"job_id": tracker["job_id"]})
        assert r.status_code == 200 and tid in r.text

    def test_success_filters(self, admin, tracker):
        d = admin.get(f"{API}/admin/success", params={"company": "zzz_nonexistent_zzz"}).json()
        assert d["total_records"] == 0
        d = admin.get(f"{API}/admin/success", params={"start": "2099-01-01"}).json()
        assert d["total_records"] == 0


class TestCron:
    def test_cron_unauthorized(self):
        assert requests.post(f"{API}/cron/tracker-reminders", json={}).status_code == 401
        assert requests.post(f"{API}/cron/tracker-reminders", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401

    def test_cron_ok(self):
        r = requests.post(f"{API}/cron/tracker-reminders", json={"run_id": f"TEST_{uuid.uuid4().hex}"},
                          headers={"Authorization": f"Bearer {CRON_SECRET}"})
        assert r.status_code == 200 and r.json() == {"accepted": True}


class TestCleanup:
    def test_untrack(self, cand, tracker):
        s = cand[0]
        assert s.delete(f"{API}/tracker/{tracker['tracker_id']}").status_code == 200
        assert tracker["tracker_id"] not in [i["tracker_id"] for i in s.get(f"{API}/tracker").json()["items"]]
