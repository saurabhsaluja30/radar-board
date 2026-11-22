# Phase 3: profile-matched job feed, candidate JD match check, and the ten application tracker stages.
import os
import sys
import uuid

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jd_match import check, jd_to_job, suitability  # noqa: E402
from tracker import STAGES, STATUSES  # noqa: E402

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@eevolvex.com", "password": "Admin@12345"}
TAG = uuid.uuid4().hex[:6]
PROFILE = {"current_designation": "Accountant", "tools": ["Tally", "GST"], "primary_skills": ["Reconciliation"],
           "total_experience": 4, "preferred_industries": ["Finance & Accounting"], "preferred_locations": ["Pune"],
           "expected_ctc": 500000, "expected_ctc_currency": "INR", "preferred_work_mode": "Hybrid"}
JD = """Accounts Executive
Location: Pune (Hybrid)
2-6 years of experience in accounting.
Must have: Tally, GST, reconciliation.
Good to have: SAP.
Salary 4 - 7 LPA."""


def _env(key):
    if os.environ.get(key):
        return os.environ[key]
    for path in ("/app/backend/.env", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')


# --------------------------------------------------------------------------- unit
def test_jd_is_read_into_job_fields():
    j = jd_to_job(JD, PROFILE)
    assert j["title"] == "Accounts Executive"
    assert {"tally", "gst", "reconciliation"} <= set(j["required_skills"]) and "sap" in j["preferred_skills"]
    assert (j["experience_min"], j["experience_max"]) == (2.0, 6.0)
    assert j["work_mode"] == "Hybrid" and j["location"] == "Pune" and j["salary_max"] == 700000
    assert "accounts executive" not in j["required_skills"], "the title line is not a skill list"


def test_check_verdicts():
    good = check(JD, PROFILE, [])
    assert good["verdict"] == "Suitable" and set(good["matched_skills"]) >= {"tally", "gst"}
    assert "sap" in good["missing_preferred_skills"] and good["missing_mandatory_skills"] == []
    gap = check(JD, {**PROFILE, "tools": ["Tally"]}, [])
    assert gap["missing_mandatory_skills"] == ["gst"] and gap["verdict"] != "Suitable", "missing required skill is never Suitable"
    weak = check(JD, {"current_designation": "Chef", "primary_skills": ["Cooking"], "total_experience": 1,
                      "preferred_locations": ["Delhi"], "preferred_work_mode": "On-site"}, [])
    assert weak["verdict"] == "Not Currently Suitable"
    assert any("experience" in r.lower() for r in weak["recommendations"])


def test_unknown_profile_details_are_not_assessed_not_guessed():
    r = check(JD, {"tools": ["Tally", "GST", "Reconciliation"]}, [])
    assert r["assessed_factors"] < r["total_factors"]
    assert "Candidate total experience" in r["not_assessed"]


def test_suitability_scales_to_assessed_factors():
    comps = {"skills": {"score": 30, "max": 30, "assessed": True}, "salary": {"score": 0, "max": 10, "assessed": False}}
    s = suitability({"components": comps, "mandatory_gap": False, "flags": []})
    assert s["score"] == 100 and s["verdict"] == "Suitable" and s["assessed_factors"] == 1


def test_ten_stages_in_order_and_old_keys_kept():
    assert [STATUSES[k] for k in STAGES] == ["Interested", "Applied", "Resume Viewed", "Shortlisted", "Interview Scheduled",
                                             "Interview Completed", "Selected", "Rejected", "Offer Received", "Joined"]
    assert {"contacted", "responded", "no_response", "hired", "not_selected"} <= set(STATUSES)


# --------------------------------------------------------------------------- live
@pytest.mark.skipif(not BASE_URL, reason="needs REACT_APP_BACKEND_URL")
class TestDiscovery:
    @classmethod
    def setup_class(cls):
        cls.db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
        cls.ah = {"Authorization": "Bearer " + requests.post(f"{API}/auth/admin/login", json=ADMIN).json()["token"]}
        cls.users, cls.jobs = [], []
        r = requests.post(f"{API}/auth/register", json={
            "full_name": f"TEST_DISC {TAG}", "email": f"test_disc_{TAG}@example.com", "mobile": "9000000002",
            "password": "secret123", "confirm_password": "secret123", "industry": "Finance & Accounting",
            "current_designation": "Accountant", "current_salary": "4 LPA", "preferred_location": "Pune",
            "preferred_work_mode": "Hybrid", "consent": True})
        assert r.status_code == 200, r.text
        cls.h = {"Authorization": f"Bearer {r.json()['token']}"}
        cls.uid = r.json()["user"]["user_id"]
        cls.users.append(cls.uid)
        assert requests.put(f"{API}/auth/profile", headers=cls.h, json=PROFILE).status_code == 200
        base = {"company": f"TEST_DISC Co {TAG}", "experience_min": 2, "experience_max": 6, "location": "Pune, India",
                "city": "Pune", "work_mode": "Hybrid", "salary_min": 300000, "salary_max": 700000, "currency": "INR",
                "status": "Published", "verification_status": "Verified", "industry_category": "Finance & Accounting"}
        cls.fit = cls.job({**base, "title": f"TEST_DISC Accountant {TAG}", "required_skills": "Tally, GST"})
        cls.gap = cls.job({**base, "title": f"TEST_DISC Accountant SAP {TAG}", "required_skills": "Tally, SAP FICO"})
        cls.other = cls.job({**base, "title": f"TEST_DISC Java Developer {TAG}", "required_skills": "Java, Spring",
                             "industry_category": "IT & Technology", "location": "Chennai, India", "city": "Chennai",
                             "work_mode": "On-site"})
        cls.unverified = cls.job({**base, "title": f"TEST_DISC Accountant Pending {TAG}", "required_skills": "Tally, GST",
                                  "verification_status": "Pending Verification"})

    @classmethod
    def job(cls, body):
        r = requests.post(f"{API}/admin/jobs", headers=cls.ah, json=body)
        assert r.status_code == 200, r.text
        cls.jobs.append(r.json()["job"]["job_id"])
        return cls.jobs[-1]

    @classmethod
    def teardown_class(cls):
        cls.db.jobs.delete_many({"job_id": {"$in": cls.jobs}})
        for coll in ("job_matches", "job_notifications", "candidate_job_activity", "job_tracker", "tracker_evidence"):
            cls.db[coll].delete_many({"$or": [{"candidate_id": {"$in": cls.users}}, {"job_id": {"$in": cls.jobs}}]})
        cls.db.match_queue.delete_many({"ref_id": {"$in": cls.users + cls.jobs}})
        cls.db.users.delete_many({"user_id": {"$in": cls.users}})
        cls.db.subscriptions.delete_many({"candidate_id": {"$in": cls.users}})

    def feed(self, **q):
        r = requests.get(f"{API}/smartmatch/feed", headers=self.h, params=q)
        assert r.status_code == 200, r.text
        return r.json()

    def test_feed_shows_only_relevant_verified_jobs(self):
        d = self.feed()
        ids = [j["job_id"] for j in d["jobs"]]
        assert self.fit in ids
        assert self.gap not in ids, "a missing required skill keeps a job out of the feed"
        assert self.other not in ids, "unrelated jobs are hidden"
        assert self.unverified not in ids, "only verified jobs are matched"
        assert d["hidden_unrelated"] >= 2
        fit = next(j for j in d["jobs"] if j["job_id"] == self.fit)
        assert fit["match"]["explanation"] and fit["match"]["missing_mandatory_skills"] == []

    def test_filters_only_narrow(self):
        assert self.fit in [j["job_id"] for j in self.feed(location="Pune", work_mode="Hybrid")["jobs"]]
        assert self.feed(location="Chennai")["jobs"] == [] or self.other not in [j["job_id"] for j in self.feed(location="Chennai")["jobs"]]
        assert self.fit not in [j["job_id"] for j in self.feed(location="Chennai")["jobs"]]
        assert self.fit not in [j["job_id"] for j in self.feed(min_salary=900000)["jobs"]]
        assert self.fit not in [j["job_id"] for j in self.feed(max_experience=1)["jobs"]]
        assert self.fit in [j["job_id"] for j in self.feed(max_experience=4, designation="accountant")["jobs"]]

    def test_my_matches_never_recommend_a_mandatory_gap(self):
        me = requests.get(f"{API}/smartmatch/me", headers=self.h).json()
        assert self.gap not in [j["job_id"] for j in me["recommended"] + me["strong"]]

    def test_feed_is_for_candidates_only(self):
        assert requests.get(f"{API}/smartmatch/feed", headers=self.ah).status_code == 403
        assert requests.get(f"{API}/smartmatch/feed").status_code in (401, 403)

    def test_jd_check_text_and_job(self):
        r = requests.post(f"{API}/smartmatch/jd-check", headers=self.h, json={"jd_text": JD})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["verdict"] == "Suitable" and d["score"] >= 80 and d["disclaimer"]
        r = requests.post(f"{API}/smartmatch/jd-check", headers=self.h, json={"job_id": self.gap})
        assert r.json()["missing_mandatory_skills"] == ["sap fico"] and r.json()["verdict"] != "Suitable"
        assert requests.post(f"{API}/smartmatch/jd-check", headers=self.h, json={"jd_text": "too short"}).status_code == 400

    def test_resume_viewed_needs_verified_proof(self):
        t = requests.post(f"{API}/tracker", headers=self.h, json={"job_id": self.fit}).json()["item"]
        tid = t["tracker_id"]
        r = requests.put(f"{API}/tracker/{tid}/status", headers=self.h, json={"status": "resume_viewed"})
        assert r.status_code == 400, "candidates can't mark Resume Viewed themselves"
        assert requests.put(f"{API}/tracker/{tid}/status", headers=self.h, json={"status": "applied"}).status_code == 200
        for s in ("shortlisted", "selected", "not_selected"):
            assert requests.put(f"{API}/tracker/{tid}/status", headers=self.h, json={"status": s}).json()["item"]["status"] == s
        requests.put(f"{API}/tracker/{tid}/status", headers=self.h, json={"status": "applied"})
        # Proof shared, then verified by an admin: the application moves to Resume Viewed.
        self.db.job_tracker.update_one({"tracker_id": tid}, {"$set": {"resume_viewed_verification": "candidate_reported"}})
        assert requests.post(f"{API}/admin/success/{tid}/verify", headers=self.ah,
                             json={"kind": "resume_viewed", "verified": True}).status_code == 200
        item = next(i for i in requests.get(f"{API}/tracker", headers=self.h).json()["items"] if i["tracker_id"] == tid)
        assert item["status"] == "resume_viewed" and item["status_label"] == "Resume Viewed"
        assert requests.post(f"{API}/admin/success/{tid}/verify", headers=self.ah,
                             json={"kind": "resume_viewed", "verified": False}).status_code == 200
        item = next(i for i in requests.get(f"{API}/tracker", headers=self.h).json()["items"] if i["tracker_id"] == tid)
        assert item["status"] == "applied", "removing verification moves it back"

    def test_tracker_lists_stages(self):
        d = requests.get(f"{API}/tracker", headers=self.h).json()
        assert d["stages"] == STAGES and d["verified_only"] == ["resume_viewed"]
