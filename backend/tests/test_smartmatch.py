# JobRadar SmartMatch: job verification, duplicates, matching engine, review, share/alerts, candidate matches, RBAC, analytics
import os
import uuid
from datetime import date, timedelta

import pytest
import requests
from pymongo import MongoClient
from envutil import env_value  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}




MONGO = MongoClient(env_value("MONGO_URL"))[env_value("DB_NAME")]
UID = uuid.uuid4().hex[:6]
CREATED = {"jobs": [], "users": []}


def _sess(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _register(tag, consent):
    email = f"test_sm_{tag}_{UID}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "full_name": f"TEST_SM {tag}", "email": email, "mobile": "9876543210", "password": "Test@1234",
        "confirm_password": "Test@1234", "industry": "IT & Technology", "current_designation": "Software Engineer",
        "current_salary": "10 LPA", "preferred_location": "Bengaluru", "preferred_work_mode": "Remote", "consent": True,
        "preferred_industries": ["IT & Technology"]})
    assert r.status_code == 200, r.text
    s = _sess(r.json()["token"])
    uid = r.json()["user"]["user_id"]
    CREATED["users"].append(uid)
    p = s.put(f"{API}/auth/profile", json={
        "total_experience": 5, "primary_skills": ["Python", "React", "FastAPI"], "preferred_titles": ["Software Engineer"],
        "preferred_locations": ["Bengaluru"], "expected_ctc": 1500000, "notice_period": "30 days",
        "job_alert_consent": consent, "job_alert_frequency": "Instant"})
    assert p.status_code == 200, p.text
    return s, uid, email


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/admin/login", json=ADMIN)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return _sess(r.json()["token"])


@pytest.fixture(scope="module")
def cands():
    a = _register("consent", True)
    b = _register("noconsent", False)
    yield a, b
    # cleanup
    ids = CREATED["users"]
    for coll in ("job_matches", "job_notifications", "match_reviews", "candidate_job_activity", "job_tracker", "consent_records",
                 "saved_jobs", "email_logs", "user_sessions"):
        MONGO[coll].delete_many({"candidate_id": {"$in": ids}})
        MONGO[coll].delete_many({"user_id": {"$in": ids}})
    MONGO.users.delete_many({"user_id": {"$in": ids}})
    jids = CREATED["jobs"]
    for coll in ("job_matches", "job_notifications", "match_reviews", "candidate_job_activity", "job_tracker", "saved_jobs"):
        MONGO[coll].delete_many({"job_id": {"$in": jids}})
    MONGO.jobs.delete_many({"job_id": {"$in": jids}})
    granted = MONGO.users.count_documents({"launch_offer": "granted"})
    MONGO.app_settings.update_one({"key": "launch_offer"}, {"$set": {"granted": granted}})


def _job_payload(**kw):
    p = {"title": f"TEST_SM Software Engineer {UID}", "company": f"TEST_SM Co {UID}", "location": "Bengaluru",
         "function": "IT & Technology", "industry_category": "IT & Technology", "work_mode": "Remote",
         "required_skills": "Python, React", "preferred_skills": "FastAPI", "experience_min": 3, "experience_max": 7,
         "salary_min": 1200000, "salary_max": 2000000, "status": "Published", "job_source": "Recruiter submission",
         "description": "Test", "application_link": "https://example.com/apply"}
    p.update(kw)
    return p


@pytest.fixture(scope="module")
def job(admin, cands):
    r = admin.post(f"{API}/admin/jobs", json=_job_payload())
    assert r.status_code == 200, r.text
    j = r.json()["job"]
    CREATED["jobs"].append(j["job_id"])
    return j


class TestSmartMatchFlow:
    def test_new_job_pending_not_public(self, job):
        assert job["verification_status"] == "Pending Verification"
        ids = [x["job_id"] for x in requests.get(f"{API}/jobs", params={"limit": 500}).json()["jobs"]]
        assert job["job_id"] not in ids
        assert requests.get(f"{API}/jobs/{job['job_id']}").status_code == 404

    def test_find_candidates_unverified_400(self, admin, job):
        r = admin.post(f"{API}/admin/smartmatch/jobs/{job['job_id']}/find-candidates")
        assert r.status_code == 400

    def test_duplicates(self, admin, job):
        r = admin.get(f"{API}/admin/smartmatch/duplicates", params={"company": job["company"].upper(), "title": job["title"],
                                                                    "location": "bengaluru"})
        assert r.status_code == 200
        assert any(d["job_id"] == job["job_id"] for d in r.json()["duplicates"])
        r = admin.get(f"{API}/admin/smartmatch/duplicates", params={"company": job["company"], "title": job["title"],
                                                                    "location": "Bengaluru", "exclude": job["job_id"]})
        assert not any(d["job_id"] == job["job_id"] for d in r.json()["duplicates"])

    def test_verify_and_public(self, admin, job):
        assert admin.post(f"{API}/admin/smartmatch/jobs/{job['job_id']}/verify", json={"verification_status": "Bogus"}).status_code == 400
        r = admin.post(f"{API}/admin/smartmatch/jobs/{job['job_id']}/verify", json={"verification_status": "Verified"})
        assert r.status_code == 200
        assert requests.get(f"{API}/jobs/{job['job_id']}").status_code == 200

    def test_find_candidates_and_breakdown(self, admin, job, cands):
        r = admin.post(f"{API}/admin/smartmatch/jobs/{job['job_id']}/find-candidates")
        assert r.status_code == 200, r.text
        assert r.json()["scored"] >= 2
        r = admin.get(f"{API}/admin/smartmatch/matches", params={"job_id": job["job_id"], "page_size": 100})
        ms = r.json()["matches"]
        scores = [m["match_score"] for m in ms]
        assert scores == sorted(scores, reverse=True)
        mine = [m for m in ms if m["candidate_id"] == cands[0][1]][0]
        assert set(mine["components"].keys()) == {"skills", "designation", "experience", "industry", "location", "salary", "work_mode"}
        assert mine["match_score"] >= 80, mine
        assert mine["category"].startswith("Strong")
        assert isinstance(mine["explanation"], list) and mine["explanation"]
        assert mine["status"] == "suggested"

    def _match(self, admin, job, cid):
        ms = admin.get(f"{API}/admin/smartmatch/matches", params={"job_id": job["job_id"], "candidate_id": cid}).json()["matches"]
        return ms[0]

    def test_reject_requires_reason_then_reject(self, admin, job, cands):
        m = self._match(admin, job, cands[1][1])
        assert admin.post(f"{API}/admin/smartmatch/matches/review", json={"match_ids": [m["match_id"]], "action": "reject"}).status_code == 400
        r = admin.post(f"{API}/admin/smartmatch/matches/review", json={"match_ids": [m["match_id"]], "action": "reject",
                                                                        "rejection_reason": "TEST reason"})
        assert r.json()["updated"] == 1
        m2 = self._match(admin, job, cands[1][1])
        assert m2["status"] == "rejected" and m2["rejection_reason"] == "TEST reason"
        h = admin.get(f"{API}/admin/smartmatch/matches/{m['match_id']}/history").json()
        assert h["reviews"][0]["to_status"] == "rejected"

    def test_bulk_approve(self, admin, job, cands):
        ids = [self._match(admin, job, c[1])["match_id"] for c in cands]
        r = admin.post(f"{API}/admin/smartmatch/matches/review", json={"match_ids": ids, "action": "approve"})
        assert r.status_code == 200 and r.json()["updated"] == 2
        assert all(self._match(admin, job, c[1])["status"] == "approved" for c in cands)

    def test_share_consent_and_dedup(self, admin, job, cands):
        ma = self._match(admin, job, cands[0][1])["match_id"]
        mb = self._match(admin, job, cands[1][1])["match_id"]
        r = admin.post(f"{API}/admin/smartmatch/matches/share", json={"match_ids": [ma, mb], "channels": ["in_app", "email"]})
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        a_res = [x for x in res if x["match_id"] == ma]
        assert any(x["channel"] == "in_app" and x["result"] == "sent" for x in a_res), res
        assert any(x["channel"] == "email" and x["result"] in ("sent", "failed") for x in a_res), res
        b_res = [x for x in res if x["match_id"] == mb]
        assert b_res[0]["result"] == "skipped" and "opted out" in b_res[0]["reason"]
        assert self._match(admin, job, cands[0][1])["status"] == "shared"
        r2 = admin.post(f"{API}/admin/smartmatch/matches/share", json={"match_ids": [ma], "channels": ["in_app"]}).json()["results"]
        assert r2[0]["result"] == "skipped" and r2[0]["reason"] == "already sent"
        assert MONGO.job_notifications.count_documents({"candidate_id": cands[0][1], "job_id": job["job_id"], "channel": "in_app"}) == 1

    def test_candidate_me_shared(self, job, cands):
        r = cands[0][0].get(f"{API}/smartmatch/me")
        assert r.status_code == 200
        d = r.json()
        assert any(c["job_id"] == job["job_id"] for c in d["shared"])
        assert any(c["job_id"] == job["job_id"] for c in d["recommended"])

    def test_tracker_applied_syncs_match(self, admin, job, cands):
        s = cands[0][0]
        t = s.post(f"{API}/tracker", json={"job_id": job["job_id"]})
        assert t.status_code == 200, t.text
        assert self._match(admin, job, cands[0][1])["status"] == "interested"
        tid = t.json()["item"]["tracker_id"]
        u = s.put(f"{API}/tracker/{tid}/status", json={"status": "applied"})
        assert u.status_code == 200, u.text
        assert self._match(admin, job, cands[0][1])["status"] == "applied"

    def test_consent_record_created(self, cands):
        s, uid, _ = cands[1]
        n0 = MONGO.consent_records.count_documents({"user_id": uid})
        assert s.put(f"{API}/auth/profile", json={"job_alert_consent": True}).status_code == 200
        assert MONGO.consent_records.count_documents({"user_id": uid}) == n0 + 1
        ps = s.get(f"{API}/smartmatch/profile-status").json()
        assert "completion" in ps

    def test_rbac(self, cands):
        s = cands[0][0]
        for path in ("matches", "candidates", "analytics", "audit", "meta"):
            assert s.get(f"{API}/admin/smartmatch/{path}").status_code == 403, path
        assert requests.get(f"{API}/admin/smartmatch/matches").status_code in (401, 403)
        assert requests.get(f"{API}/smartmatch/me").status_code in (401, 403)

    def test_analytics_counts(self, admin):
        d = admin.get(f"{API}/admin/smartmatch/analytics").json()
        all_jobs = list(MONGO.jobs.find({}, {"job_id": 1}))
        assert d["jobs"]["received"] == len(all_jobs)
        assert d["matches"]["total"] == MONGO.job_matches.count_documents({"job_id": {"$in": [j["job_id"] for j in all_jobs]}})
        assert d["alerts"]["sent"] == MONGO.job_notifications.count_documents({"status": "sent"})
        assert d["candidates"]["total"] == MONGO.users.count_documents({"role": "candidate"})

    def test_paused_then_expired_ineligible(self, admin, job, cands):
        jid = job["job_id"]
        full = admin.get(f"{API}/admin/jobs/{jid}").json()["job"]
        full.update({"status": "Unpublished"})
        assert admin.put(f"{API}/admin/jobs/{jid}", json=full).status_code == 200
        assert admin.post(f"{API}/admin/smartmatch/jobs/{jid}/find-candidates").status_code == 400
        assert not any(c["job_id"] == jid for c in cands[0][0].get(f"{API}/smartmatch/me").json()["recommended"])
        # expired
        full.update({"status": "Published", "expiry_date": (date.today() - timedelta(days=2)).isoformat()})
        r = admin.put(f"{API}/admin/jobs/{jid}", json=full)
        assert r.status_code == 200 and r.json()["job"]["verification_status"] == "Verified"
        assert admin.post(f"{API}/admin/smartmatch/jobs/{jid}/find-candidates").status_code == 400
        assert admin.get(f"{API}/admin/jobs/{jid}").json()["job"]["status"] == "Expired"
        mid = self._match(admin, job, cands[1][1])["match_id"]
        MONGO.job_matches.update_one({"match_id": mid}, {"$set": {"status": "suggested"}})
        r = admin.post(f"{API}/admin/smartmatch/matches/review", json={"match_ids": [mid], "action": "approve"}).json()
        assert r["updated"] == 0 and r["skipped"]
        ids = [x["job_id"] for x in requests.get(f"{API}/jobs", params={"limit": 500}).json()["jobs"]]
        assert jid not in ids
