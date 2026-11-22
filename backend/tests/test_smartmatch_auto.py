# SmartMatch phase 4: configurable weights, resume data in scoring, event-driven matching queue, Control Room.
import os
import sys
import time
import uuid

import pytest
import requests
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from smartmatch import WEIGHTS, score_match  # noqa: E402

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}

JOB = {"title": "Ticketing Executive", "required_skills": "Sabre, Amadeus", "experience_min": 3, "experience_max": 6,
       "industry_category": "Travel & Hospitality", "location": "Mumbai, India", "city": "Mumbai", "work_mode": "Hybrid",
       "salary_min": 400000, "salary_max": 800000, "currency": "INR"}
CAND = {"current_designation": "Ticketing Executive", "primary_skills": ["Customer Service"], "tools": ["Sabre", "Amadeus"],
        "total_experience": 5, "relevant_experience": 2, "industry_experience": ["Travel & Hospitality"],
        "current_location": "Mumbai", "expected_ctc": 600000, "expected_ctc_currency": "INR", "preferred_work_mode": "Hybrid"}


# --------------------------------------------------------------------------- unit
def test_resume_data_counts_in_scoring():
    r = score_match(CAND, JOB, [])
    c = r["components"]
    assert c["skills"]["score"] == WEIGHTS["skills"], "tools confirmed from the resume count as skills"
    assert c["industry"]["detail"] == "Industry experience (from resume)" and c["industry"]["score"] == 8
    assert c["location"]["detail"].startswith("Currently based in") and c["location"]["score"] == 8
    assert any("Relevant experience 2 yrs" in f for f in r["flags"])


def test_missing_information_is_not_a_match():
    r = score_match({}, JOB, [])
    assert r["match_score"] == 0 and all(not v["assessed"] for v in r["components"].values() if v["score"] == 0)


def test_custom_weights_rescale_components():
    w = {"skills": 50, "designation": 10, "experience": 10, "industry": 10, "location": 10, "salary": 5, "work_mode": 5}
    base, custom = score_match(CAND, JOB, []), score_match(CAND, JOB, [], w)
    assert custom["components"]["skills"] == {**base["components"]["skills"], "score": 50.0, "max": 50}
    assert custom["components"]["salary"]["score"] == pytest.approx(base["components"]["salary"]["score"] / 2)
    assert sum(v["max"] for v in custom["components"].values()) == 100
    assert custom["match_score"] == round(sum(v["score"] for v in custom["components"].values()))


# --------------------------------------------------------------------------- live backend
def _env(key):
    if os.environ.get(key):
        return os.environ[key]
    for path in ("/app/backend/.env", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')


@pytest.mark.skipif(not BASE_URL, reason="needs REACT_APP_BACKEND_URL")
class TestAutoMatching:
    @classmethod
    def setup_class(cls):
        cls.db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
        cls.h = {"Authorization": "Bearer " + requests.post(f"{API}/auth/admin/login", json=ADMIN).json()["token"]}
        cls.prev = cls.db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0, "weights": 1}) or {}
        cls.users, cls.jobs = [], []

    @classmethod
    def teardown_class(cls):
        if cls.prev.get("weights"):
            cls.db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"weights": cls.prev["weights"]}})
        else:
            cls.db.app_settings.update_one({"key": "smartmatch"}, {"$unset": {"weights": ""}})
        cls.db.users.delete_many({"user_id": {"$in": cls.users}})
        cls.db.jobs.delete_many({"job_id": {"$in": cls.jobs}})
        cls.db.job_matches.delete_many({"$or": [{"candidate_id": {"$in": cls.users}}, {"job_id": {"$in": cls.jobs}}]})
        cls.db.match_queue.delete_many({"ref_id": {"$in": cls.users + cls.jobs}})
        cls.db.job_notifications.delete_many({"$or": [{"candidate_id": {"$in": cls.users}}, {"job_id": {"$in": cls.jobs}}]})

    def register(self, **profile):
        uid = uuid.uuid4().hex[:8]
        r = requests.post(f"{API}/auth/register", json={
            "full_name": f"TEST_SM4 {uid}", "email": f"test_sm4_{uid}@example.com", "mobile": "9000000001", "password": "secret123",
            "confirm_password": "secret123", "industry": "Travel & Hospitality", "current_designation": "Ticketing Executive",
            "current_salary": "5 LPA", "preferred_location": "Mumbai", "preferred_work_mode": "Hybrid", "consent": True})
        assert r.status_code == 200, r.text
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        user_id = r.json()["user"]["user_id"]
        self.users.append(user_id)
        if profile:
            assert requests.put(f"{API}/auth/profile", headers=h, json=profile).status_code == 200
        return h, user_id

    def wait_done(self, ref_id, n=1, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if self.db.match_queue.count_documents({"ref_id": ref_id, "status": "done"}) >= n \
                    and not self.db.match_queue.count_documents({"ref_id": ref_id, "status": {"$in": ["queued", "processing"]}}):
                return
            time.sleep(0.3)
        raise AssertionError(f"matching for {ref_id} did not finish: {list(self.db.match_queue.find({'ref_id': ref_id}, {'_id': 0}))}")

    def test_weights_validation(self):
        bad = {**WEIGHTS, "skills": 29}
        r = requests.put(f"{API}/admin/smartmatch/weights", headers=self.h, json={"weights": bad})
        assert r.status_code == 400 and "100" in r.json()["detail"]
        assert requests.put(f"{API}/admin/smartmatch/weights", headers=self.h, json={"weights": {"skills": 100}}).status_code == 400
        good = {**WEIGHTS, "skills": 35, "work_mode": 0}
        assert requests.put(f"{API}/admin/smartmatch/weights", headers=self.h, json={"weights": good}).status_code == 200
        assert requests.get(f"{API}/admin/smartmatch/weights", headers=self.h).json()["weights"] == good
        requests.put(f"{API}/admin/smartmatch/weights", headers=self.h, json={"weights": WEIGHTS})

    def test_event_driven_matching(self):
        good_h, good = self.register(primary_skills=["Customer Service"], tools=["Sabre", "Amadeus"], total_experience=5,
                                     current_location="Mumbai", expected_ctc=600000, preferred_locations=["Mumbai"])
        _, weak = self.register(primary_skills=["Python"], total_experience=1, preferred_locations=["Delhi"])
        self.wait_done(good)

        # Publishing a job queues matching automatically; only relevant scores create match rows.
        r = requests.post(f"{API}/admin/jobs", headers=self.h, json={**JOB, "title": "TEST_SM4 Ticketing Executive", "company": "TEST_SM4 Air",
                                                                     "status": "Published", "verification_status": "Verified"})
        jid = r.json()["job"]["job_id"]
        self.jobs.append(jid)
        self.wait_done(jid)
        m = self.db.job_matches.find_one({"job_id": jid, "candidate_id": good})
        assert m and m["match_score"] >= 65
        assert not self.db.job_matches.find_one({"job_id": jid, "candidate_id": weak}), "low scores are not stored automatically"

        # Saving a profile with no match-relevant change queues nothing; a real change queues one rematch.
        before = self.db.match_queue.count_documents({"ref_id": good})
        requests.put(f"{API}/auth/profile", headers=good_h, json={"full_name": "TEST_SM4 renamed"})
        assert self.db.match_queue.count_documents({"ref_id": good}) == before
        requests.put(f"{API}/auth/profile", headers=good_h, json={"tools": ["Sabre", "Amadeus", "Galileo"]})
        self.wait_done(good, n=before + 1)

        # Editing a job's non-scoring field doesn't rematch; unpublishing makes it unmatchable.
        jb = self.db.match_queue.count_documents({"ref_id": jid})
        requests.post(f"{API}/admin/jobs/{jid}/feature", headers=self.h, json={"featured": True})
        assert self.db.match_queue.count_documents({"ref_id": jid}) == jb

        # Internal tracking markers and the Control Room.
        rv = requests.post(f"{API}/admin/smartmatch/matches/review", headers=self.h,
                           json={"match_ids": [m["match_id"]], "action": "mark_shortlisted"})
        assert rv.json()["updated"] == 1 and self.db.job_matches.find_one({"match_id": m["match_id"]})["shortlisted_at"]
        cr = requests.get(f"{API}/admin/smartmatch/control-room", headers=self.h).json()
        assert cr["active_jobs"] >= 1 and cr["shortlisted"] >= 1 and cr["strong_matches"] + cr["potential_matches"] >= 1
        assert jid not in {j["job_id"] for j in cr["jobs_without_suitable_list"]}

    def test_one_queued_item_per_ref(self):
        ref = f"TEST_SM4_{uuid.uuid4().hex[:6]}"
        self.users.append(ref)
        self.db.match_queue.insert_one({"queue_id": f"mq_t{ref}", "kind": "candidate", "ref_id": ref, "status": "queued"})
        with pytest.raises(DuplicateKeyError):
            self.db.match_queue.insert_one({"queue_id": f"mq_t2{ref}", "kind": "candidate", "ref_id": ref, "status": "queued"})
        self.db.match_queue.delete_many({"ref_id": ref})

    def test_cron_requires_secret(self):
        assert requests.post(f"{API}/cron/smartmatch-queue").status_code == 401
        sec = _env("WEBHOOK_CRON_SECRET")
        if sec:
            assert requests.post(f"{API}/cron/smartmatch-queue", headers={"Authorization": f"Bearer {sec}"}).status_code == 200


FIN_JOB = {"title": "TEST_SM5 Accountant", "company": "TEST_SM5 Ledger Co", "required_skills": "Tally, GST",
           "experience_min": 2, "experience_max": 8, "industry_category": "Finance & Accounting", "location": "Pune, India",
           "city": "Pune", "work_mode": "Hybrid", "salary_min": 300000, "salary_max": 900000, "currency": "INR",
           "status": "Published", "verification_status": "Verified"}
FIN_PROFILE = {"current_designation": "TEST_SM5 Accountant", "tools": ["Tally", "GST"], "total_experience": 4,
               "preferred_industries": ["Finance & Accounting"], "preferred_locations": ["Pune"], "expected_ctc": 500000,
               "expected_ctc_currency": "INR", "preferred_work_mode": "Hybrid"}


@pytest.mark.skipif(not BASE_URL, reason="needs REACT_APP_BACKEND_URL")
class TestAutoAlerts(TestAutoMatching):
    @classmethod
    def setup_class(cls):
        super().setup_class()
        cls.prev_alerts = (cls.db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0, "auto_alerts": 1}) or {}).get("auto_alerts")

    @classmethod
    def teardown_class(cls):
        cls.db.job_notifications.delete_many({"job_id": {"$in": cls.jobs}})
        if cls.prev_alerts:
            cls.db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"auto_alerts": cls.prev_alerts}})
        else:
            cls.db.app_settings.update_one({"key": "smartmatch"}, {"$unset": {"auto_alerts": ""}})
        super().teardown_class()

    def publish(self, n):
        r = requests.post(f"{API}/admin/jobs", headers=self.h, json={**FIN_JOB, "title": FIN_JOB["title"], "company": f"{FIN_JOB['company']} {n}"})
        jid = r.json()["job"]["job_id"]
        self.jobs.append(jid)
        self.wait_done(jid)
        return jid

    def alerts(self, uid):
        return list(self.db.job_notifications.find({"candidate_id": uid, "job_id": {"$in": self.jobs}, "channel": "in_app"}, {"_id": 0}))

    def test_settings_validation(self):
        assert requests.put(f"{API}/admin/smartmatch/auto-alerts", headers=self.h,
                            json={"enabled": True, "min_score": 20, "max_per_day": 5, "max_job_age_days": 14}).status_code == 400

    def test_alerts(self):
        r = requests.put(f"{API}/admin/smartmatch/auto-alerts", headers=self.h,
                         json={"enabled": True, "min_score": 80, "max_per_day": 1, "max_job_age_days": 14})
        assert r.status_code == 200
        ha, a = self.register(**FIN_PROFILE)                               # no alert preference chosen yet
        _, b = self.register(**FIN_PROFILE, job_alert_consent=False)       # opted out
        _, c = self.register(**FIN_PROFILE, alert_muted_industries=["Finance & Accounting"])
        for u in (a, b, c):
            self.wait_done(u)

        j1 = self.publish(1)
        m = self.db.job_matches.find_one({"job_id": j1, "candidate_id": a})
        assert m["match_score"] >= 80 and {"tally", "gst"} <= set(m["matched_skills"])
        got = self.alerts(a)
        assert len(got) == 1 and got[0]["source"] == "auto" and got[0]["status"] == "sent" and "TEST_SM5 Accountant" in got[0]["subject"]
        assert not self.alerts(b), "opted-out candidates get no alerts"
        assert not self.alerts(c), "muted categories get no alerts"
        assert self.db.job_matches.find_one({"job_id": j1, "candidate_id": b})["match_score"] >= 80, "they still have the match"

        # Daily cap: a second strong job the same day doesn't alert A again.
        self.publish(2)
        assert len(self.alerts(a)) == 1

        # Rescoring never duplicates an alert.
        self.db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"auto_alerts.max_per_day": 5}})
        requests.post(f"{API}/admin/smartmatch/rescore-all", headers=self.h)
        self.wait_done(j1, n=2)
        assert len([x for x in self.alerts(a) if x["job_id"] == j1]) == 1

        # The candidate sees it and can mark it read.
        notes = requests.get(f"{API}/smartmatch/notifications", headers=ha).json()["notifications"]
        n = next(x for x in notes if x["job_id"] == j1)
        assert requests.post(f"{API}/smartmatch/notifications/{n['notification_id']}/read", headers=ha).status_code == 200
        me = requests.get(f"{API}/smartmatch/me", headers=ha).json()
        assert any(x["job_id"] == j1 and x["match"]["matched_skills"] for x in me["shared"])

    test_weights_validation = test_event_driven_matching = test_one_queued_item_per_ref = test_cron_requires_secret = None
