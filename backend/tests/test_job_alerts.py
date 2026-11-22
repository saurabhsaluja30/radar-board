# JobRadar default job alerts: tri-state consent, share rules, notifications, Alert Manager APIs, analytics, email cron + fast register
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient
from envutil import env_value  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}




MONGO = MongoClient(env_value("MONGO_URL"))[env_value("DB_NAME")]
CRON = env_value("WEBHOOK_CRON_SECRET")
UID = uuid.uuid4().hex[:6]
CREATED = {"jobs": [], "users": []}
STATE = {}


def _sess(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


def _register(tag, consent="unset", profile=None, timed=False):
    email = f"test_ja_{tag}_{UID}@example.com"
    body = {"full_name": f"TEST_JA {tag}", "email": email, "mobile": "9876543210", "password": "Test@1234",
            "confirm_password": "Test@1234", "industry": "IT & Technology", "current_designation": "Software Engineer",
            "current_salary": "10 LPA", "preferred_location": "Bengaluru", "preferred_work_mode": "Remote", "consent": True,
            "preferred_industries": ["IT & Technology"]}
    if profile and profile.get("_reg"):
        body.update(profile.pop("_reg"))
    t0 = time.time()
    r = requests.post(f"{API}/auth/register", json=body)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    s = _sess(r.json()["token"])
    uid = r.json()["user"]["user_id"]
    CREATED["users"].append(uid)
    p = {"total_experience": 5, "primary_skills": ["Python", "React", "FastAPI"], "preferred_titles": ["Software Engineer"],
         "preferred_locations": ["Bengaluru"], "expected_ctc": 1500000, "notice_period": "30 days"}
    if profile:
        p = profile
    if consent != "unset":
        p["job_alert_consent"] = consent
    pr = s.put(f"{API}/auth/profile", json=p)
    assert pr.status_code == 200, pr.text
    return {"s": s, "uid": uid, "email": email, "elapsed": elapsed}


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/admin/login", json=ADMIN)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    return _sess(r.json()["token"])


@pytest.fixture(scope="module")
def cands():
    c = {"none": _register("none", timed=True), "on": _register("on", True), "off": _register("off", False),
         "low": _register("low", "unset", profile={
             "_reg": {"industry": "Healthcare", "current_designation": "Staff Nurse", "preferred_location": "Kolkata",
                      "preferred_work_mode": "On-site", "preferred_industries": ["Healthcare"], "current_salary": "90 LPA"},
             "total_experience": 25, "primary_skills": ["Nursing", "Patient care"], "preferred_titles": ["Head Nurse"],
             "preferred_locations": ["Kolkata"], "expected_ctc": 9000000, "notice_period": "90 days"})}
    yield c
    ids = CREATED["users"]
    for coll in ("job_matches", "job_notifications", "match_reviews", "candidate_job_activity", "job_tracker", "consent_records",
                 "saved_jobs", "email_logs", "user_sessions", "subscriptions"):
        MONGO[coll].delete_many({"candidate_id": {"$in": ids}})
        MONGO[coll].delete_many({"user_id": {"$in": ids}})
    MONGO.users.delete_many({"user_id": {"$in": ids}})
    jids = CREATED["jobs"]
    for coll in ("job_matches", "job_notifications", "match_reviews", "candidate_job_activity", "job_tracker", "saved_jobs"):
        MONGO[coll].delete_many({"job_id": {"$in": jids}})
    MONGO.jobs.delete_many({"job_id": {"$in": jids}})
    MONGO.app_settings.update_one({"key": "launch_offer"}, {"$set": {"granted": MONGO.users.count_documents({"launch_offer": "granted"})}})


@pytest.fixture(scope="module")
def job(admin, cands):
    r = admin.post(f"{API}/admin/jobs", json={
        "title": f"TEST_JA Software Engineer {UID}", "company": f"TEST_JA Co {UID}", "location": "Bengaluru",
        "function": "IT & Technology", "industry_category": "IT & Technology", "work_mode": "Remote",
        "required_skills": "Python, React", "preferred_skills": "FastAPI", "experience_min": 3, "experience_max": 7,
        "salary_min": 1200000, "salary_max": 2000000, "status": "Published", "job_source": "Recruiter submission",
        "description": "Test", "application_link": "https://example.com/apply"})
    assert r.status_code == 200, r.text
    j = r.json()["job"]
    CREATED["jobs"].append(j["job_id"])
    assert admin.post(f"{API}/admin/smartmatch/jobs/{j['job_id']}/verify", json={"verification_status": "Verified"}).status_code == 200
    return j


def _match(admin, job, cid):
    ms = admin.get(f"{API}/admin/smartmatch/matches", params={"job_id": job["job_id"], "candidate_id": cid}).json()["matches"]
    assert len(ms) == 1, ms
    return ms[0]


class TestJobAlerts:
    def test_register_fast_and_consent_missing(self, cands):
        assert cands["none"]["elapsed"] < 5, cands["none"]["elapsed"]
        u = MONGO.users.find_one({"user_id": cands["none"]["uid"]})
        assert "job_alert_consent" not in u or u["job_alert_consent"] is None
        assert MONGO.users.find_one({"user_id": cands["off"]["uid"]})["job_alert_consent"] is False
        assert MONGO.users.find_one({"user_id": cands["on"]["uid"]})["job_alert_consent"] is True

    def test_profile_save_keeps_consent_missing(self, cands):
        r = cands["none"]["s"].put(f"{API}/auth/profile", json={"current_company": "TEST_JA Corp", "total_experience": 5})
        assert r.status_code == 200
        u = MONGO.users.find_one({"user_id": cands["none"]["uid"]})
        assert u.get("job_alert_consent") is None and "job_alert_consent" not in u
        assert MONGO.consent_records.count_documents({"user_id": cands["none"]["uid"]}) == 0

    def test_no_implicit_false_without_record(self):
        explicit = MONGO.consent_records.distinct("user_id", {"type": "job_alerts"})
        n = MONGO.users.count_documents({"role": "candidate", "job_alert_consent": False, "user_id": {"$nin": explicit}})
        assert n == 0

    def test_recommended_for_no_pref(self, admin, job, cands):
        r = cands["none"]["s"].get(f"{API}/smartmatch/me")
        assert r.status_code == 200
        d = r.json()
        assert d["alerts"]["pref"] == "none"
        assert job["job_id"] in [c["job_id"] for c in d["recommended"]]

    def test_find_and_filters(self, admin, job, cands):
        r = admin.post(f"{API}/admin/smartmatch/jobs/{job['job_id']}/find-candidates")
        assert r.status_code == 200, r.text
        def ids(**p):
            return {m["candidate_id"] for m in admin.get(f"{API}/admin/smartmatch/matches",
                                                          params={"job_id": job["job_id"], "page_size": 100, **p}).json()["matches"]}
        u = cands
        assert u["off"]["uid"] in ids(alert_pref="opted_out")
        assert u["none"]["uid"] not in ids(alert_pref="opted_out")
        el = ids(alert_pref="eligible")
        assert u["none"]["uid"] in el and u["on"]["uid"] in el and u["off"]["uid"] not in el
        assert ids(alert_pref="enabled") & set(CREATED["users"]) == {u["on"]["uid"]}
        assert {u["none"]["uid"], u["low"]["uid"]} <= ids(alert_pref="none")
        comp, inc = ids(profile="complete", alert_pref="eligible"), ids(profile="incomplete", alert_pref="eligible")
        assert not (comp & inc)
        m = _match(admin, job, u["none"]["uid"])
        assert m["candidate"]["alert_pref"] == "none"
        low = _match(admin, job, u["low"]["uid"])
        print("low score", low["match_score"], "none score", m["match_score"])
        assert low["match_score"] < 50, low["match_score"]
        assert m["match_score"] >= 50

    def test_share_unapproved_skipped(self, admin, job, cands):
        m = _match(admin, job, cands["none"]["uid"])
        r = admin.post(f"{API}/admin/smartmatch/matches/share", json={"match_ids": [m["match_id"]], "channels": ["in_app"]})
        assert r.json()["results"][0]["reason"] == "match is not approved"

    def test_approve_and_share_rules(self, admin, job, cands):
        ms = {k: _match(admin, job, cands[k]["uid"])["match_id"] for k in ("none", "on", "off", "low")}
        STATE["ms"] = ms
        r = admin.post(f"{API}/admin/smartmatch/matches/review", json={"match_ids": list(ms.values()), "action": "approve"})
        assert r.status_code == 200 and r.json()["updated"] == 4, r.text
        r = admin.post(f"{API}/admin/smartmatch/matches/share", json={"match_ids": list(ms.values()), "channels": ["in_app", "email"]})
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        print(res)
        by = lambda mid: [x for x in res if x["match_id"] == mid]  # noqa: E731
        none = {x["channel"]: x for x in by(ms["none"])}
        assert none["in_app"]["result"] == "sent"
        assert none["email"]["result"] == "skipped" and "opt-in" in none["email"]["reason"]
        on = {x["channel"]: x for x in by(ms["on"])}
        assert on["in_app"]["result"] == "sent"
        assert on["email"]["result"] in ("sent", "failed")
        off = by(ms["off"])
        assert len(off) == 1 and off[0]["result"] == "skipped" and "opted out" in off[0]["reason"]
        low = by(ms["low"])
        assert len(low) == 1 and "low relevance" in low[0]["reason"]
        assert MONGO.email_logs.count_documents({"candidate_id": cands["on"]["uid"], "email_type": "smartmatch_alert"}) == 1
        assert MONGO.email_logs.count_documents({"candidate_id": cands["none"]["uid"], "email_type": "smartmatch_alert"}) == 0
        assert MONGO.job_notifications.count_documents({"candidate_id": cands["off"]["uid"]}) == 0

    def test_duplicate_share_skipped(self, admin, job, cands):
        ms = STATE["ms"]
        r = admin.post(f"{API}/admin/smartmatch/matches/share", json={"match_ids": [ms["on"], ms["none"]], "channels": ["in_app"]})
        res = r.json()["results"]
        assert all(x["result"] == "skipped" and x["reason"] == "already sent" for x in res), res

    def test_candidate_notifications(self, job, cands):
        d = cands["none"]["s"].get(f"{API}/smartmatch/notifications").json()
        assert d["pref"] == "none" and any(n["job_id"] == job["job_id"] for n in d["notifications"]) and d["unread"] >= 1
        me = cands["none"]["s"].get(f"{API}/smartmatch/me").json()
        assert job["job_id"] in [c["job_id"] for c in me["shared"]]
        off = cands["off"]["s"].get(f"{API}/smartmatch/notifications").json()
        assert off["notifications"] == [] and off["pref"] == "opted_out"
        assert cands["off"]["s"].get(f"{API}/smartmatch/me").json()["shared"] == []

    def test_alert_manager_jobs_recipients(self, admin, job, cands):
        r = admin.get(f"{API}/admin/alert-manager/jobs")
        assert r.status_code == 200
        j = [x for x in r.json()["jobs"] if x["job_id"] == job["job_id"]]
        assert j and j[0]["notified"] == 2 and j[0]["approved"] >= 2
        rec = admin.get(f"{API}/admin/alert-manager/jobs/{job['job_id']}/recipients").json()["recipients"]
        cids = {(x["candidate_id"], x["channel"]) for x in rec}
        assert (cands["none"]["uid"], "in_app") in cids and (cands["on"]["uid"], "in_app") in cids
        assert (cands["on"]["uid"], "email") in cids
        assert all(x["candidate_email"] for x in rec)
        got = {m["candidate_id"] for m in admin.get(f"{API}/admin/smartmatch/matches", params={"job_id": job["job_id"], "received": "yes"}).json()["matches"]}
        assert got == {cands["none"]["uid"], cands["on"]["uid"]}
        notgot = {m["candidate_id"] for m in admin.get(f"{API}/admin/smartmatch/matches", params={"job_id": job["job_id"], "received": "no", "page_size": 100}).json()["matches"]}
        assert cands["off"]["uid"] in notgot and cands["none"]["uid"] not in notgot

    def test_analytics_alert_prefs_match_db(self, admin):
        ap = admin.get(f"{API}/admin/smartmatch/analytics").json()["alert_prefs"]
        users = list(MONGO.users.find({"role": "candidate"}, {"job_alert_consent": 1, "suspended": 1, "profile_status": 1}))
        on = sum(1 for u in users if u.get("job_alert_consent") is True)
        off = sum(1 for u in users if u.get("job_alert_consent") is False)
        assert ap["enabled"] == on and ap["opted_out"] == off and ap["none"] == len(users) - on - off
        assert ap["active_candidates"] == sum(1 for u in users if not u.get("suspended") and u.get("profile_status") != "Inactive")
        notes = list(MONGO.job_notifications.find({}, {"status": 1, "job_id": 1}))
        jids = set(MONGO.jobs.distinct("job_id"))
        notes = [n for n in notes if n["job_id"] in jids]
        assert ap["notifications_delivered"] == sum(1 for n in notes if n["status"] == "sent")
        assert ap["notifications_failed"] == sum(1 for n in notes if n["status"] == "failed")

    def test_opt_out_after_share_hides(self, job, cands):
        s = cands["on"]["s"]
        assert s.put(f"{API}/auth/profile", json={"job_alert_consent": False}).status_code == 200
        assert s.get(f"{API}/smartmatch/notifications").json()["notifications"] == []
        assert MONGO.consent_records.count_documents({"user_id": cands["on"]["uid"], "granted": False}) == 1

    def test_rbac(self, cands):
        s = cands["none"]["s"]
        assert s.get(f"{API}/admin/alert-manager/jobs").status_code == 403
        assert s.get(f"{API}/admin/alert-manager/jobs/x/recipients").status_code == 403
        assert requests.get(f"{API}/admin/alert-manager/jobs").status_code == 401


class TestEmailCron:
    def test_bad_token(self):
        assert requests.post(f"{API}/cron/email-retry", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert requests.post(f"{API}/cron/email-retry").status_code == 401

    def test_ok(self):
        t0 = time.time()
        r = requests.post(f"{API}/cron/email-retry", headers={"Authorization": f"Bearer {CRON}"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["accepted"] is True and isinstance(d["queued"], int) and d["queued"] <= 8
        assert time.time() - t0 < 5
