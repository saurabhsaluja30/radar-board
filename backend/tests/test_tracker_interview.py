# Phase 4: applications added by hand, notes and follow-ups, the Career Success Dashboard counts,
# voice answers in mock interviews and the interview readiness report.
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import requests
from pymongo import MongoClient

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}
TAG = uuid.uuid4().hex[:6]


def _env(key):
    if os.environ.get(key):
        return os.environ[key]
    for path in ("/app/backend/.env", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')


@pytest.mark.skipif(not BASE_URL, reason="needs REACT_APP_BACKEND_URL")
class TestTrackerAndInterviews:
    @classmethod
    def setup_class(cls):
        cls.db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
        cls.ah = {"Authorization": "Bearer " + requests.post(f"{API}/auth/admin/login", json=ADMIN).json()["token"]}
        r = requests.post(f"{API}/auth/register", json={
            "full_name": f"TEST_P4 {TAG}", "email": f"test_p4_{TAG}@example.com", "mobile": "9000000004",
            "password": "secret123", "confirm_password": "secret123", "industry": "HR & Recruitment",
            "current_designation": "Recruiter", "current_salary": "5 LPA", "preferred_location": "Pune",
            "preferred_work_mode": "Hybrid", "consent": True})
        assert r.status_code == 200, r.text
        cls.h = {"Authorization": f"Bearer {r.json()['token']}"}
        cls.uid = r.json()["user"]["user_id"]
        cls.db.subscriptions.delete_many({"candidate_id": cls.uid})  # free tier: job recruiter details are hidden
        j = requests.post(f"{API}/admin/jobs", headers=cls.ah, json={
            "title": f"TEST_P4 Recruiter {TAG}", "company": f"TEST_P4 Co {TAG}", "location": "Pune, India",
            "industry_category": "HR & Recruitment", "recruiter_name": "Job Board Recruiter",
            "recruiter_email": "listed@example.com", "status": "Published", "verification_status": "Verified"})
        assert j.status_code == 200, j.text
        cls.job = j.json()["job"]["job_id"]

    @classmethod
    def teardown_class(cls):
        cls.db.jobs.delete_one({"job_id": cls.job})
        for coll in ("job_tracker", "job_matches", "candidate_job_activity", "job_notifications"):
            cls.db[coll].delete_many({"candidate_id": cls.uid})
        cls.db.interview_sessions.delete_many({"user_id": cls.uid})
        cls.db.resume_analyses.delete_many({"user_id": cls.uid})
        cls.db.match_queue.delete_many({"ref_id": {"$in": [cls.uid, cls.job]}})
        cls.db.users.delete_one({"user_id": cls.uid})

    def items(self):
        return requests.get(f"{API}/tracker", headers=self.h).json()["items"]

    def add(self, **body):
        return requests.post(f"{API}/tracker/external", headers=self.h, json={
            "company": f"Outside Co {TAG}", "designation": "Talent Partner", **body})

    # ------------------------------------------------------------------ applications added by hand
    def test_external_application_validation(self):
        assert requests.post(f"{API}/tracker/external", headers=self.h, json={"company": "", "designation": "X"}).status_code == 400
        assert self.add(application_link="javascript:alert(1)").status_code == 400
        assert self.add(recruiter_email="not-an-email").status_code == 400
        assert self.add(status="hired").status_code == 400, "joined needs company, title and date via Update Progress"
        assert self.add(status="resume_viewed").status_code == 400
        assert self.add(applied_date="31/12/2026").status_code == 400
        assert requests.post(f"{API}/tracker/external", headers=self.ah, json={"company": "A", "designation": "B"}).status_code == 403

    def test_external_application_is_tracked_privately(self):
        r = self.add(application_link="https://careers.example.com/123", applied_date="2026-11-01",
                     recruiter_name="Riya", recruiter_email="riya@example.com", notes="Referred by a friend")
        assert r.status_code == 200, r.text
        item = r.json()["item"]
        assert item["source"] == "external" and item["status"] == "applied" and item["job_id"].startswith("ext_")
        assert item["recruiter_email"] == "riya@example.com", "details the candidate typed are never hidden"
        assert item["status_label"] == "Applied" and "applied" in item["reached"]
        # A second one with the same company is a separate record (no clash on the per-job unique index).
        assert self.add(status="interested").status_code == 200
        success = requests.get(f"{API}/admin/success", headers=self.ah, params={"company": f"Outside Co {TAG}"}).json()
        assert success["total_records"] == 0, "JobRadar success analytics only count jobs found on JobRadar"

    def test_details_and_follow_up_reminder(self):
        item = self.add().json()["item"]
        tid = item["tracker_id"]
        today = datetime.now(timezone.utc).date().isoformat()
        r = requests.put(f"{API}/tracker/{tid}/details", headers=self.h, json={
            "notes": "Call on Monday", "follow_up_date": today, "follow_up_note": "Ask about next round",
            "designation": "Senior Talent Partner"})
        assert r.status_code == 200, r.text
        it = r.json()["item"]
        assert it["notes"] == "Call on Monday" and it["designation"] == "Senior Talent Partner"
        assert it["reminder"]["follow_up"] is True and "Ask about next round" in it["reminder"]["text"]
        requests.post(f"{API}/tracker/{tid}/dismiss-reminder", headers=self.h)
        it = next(i for i in self.items() if i["tracker_id"] == tid)
        assert not (it["reminder"] or {}).get("follow_up"), "a dismissed follow-up stays dismissed"
        later = (date.today() + timedelta(days=5)).isoformat()
        it = requests.put(f"{API}/tracker/{tid}/details", headers=self.h, json={"follow_up_date": later}).json()["item"]
        assert not (it["reminder"] or {}).get("follow_up"), "a future follow-up isn't due yet"
        assert requests.put(f"{API}/tracker/{tid}/details", headers=self.h, json={}).status_code == 400

    def test_jobradar_job_keeps_listed_recruiter_members_only(self):
        t = requests.post(f"{API}/tracker", headers=self.h, json={"job_id": self.job}).json()["item"]
        assert t["recruiter_email"] is None, "listed recruiter details stay a member feature"
        it = requests.put(f"{API}/tracker/{t['tracker_id']}/details", headers=self.h, json={
            "recruiter_name": "Arjun", "recruiter_email": "arjun@example.com", "designation": "ignored"}).json()["item"]
        assert it["my_recruiter"] == {"name": "Arjun", "email": "arjun@example.com"}
        assert it["designation"] == f"TEST_P4 Recruiter {TAG}", "a JobRadar job's own details can't be edited"
        assert it["recruiter_email"] is None

    # ------------------------------------------------------------------ dashboard
    def test_summary_counts_only_verified_interviews_in_conversion(self):
        before = requests.get(f"{API}/tracker/summary", headers=self.h).json()
        a = self.add().json()["item"]["tracker_id"]
        b = self.add().json()["item"]["tracker_id"]
        for tid in (a, b):
            r = requests.put(f"{API}/tracker/{tid}/status", headers=self.h, json={
                "status": "interview_scheduled", "interview_date": "2026-12-01", "interview_mode": "Video"})
            assert r.status_code == 200, r.text
        self.db.job_tracker.update_one({"tracker_id": a}, {"$set": {"interview_verification": "verified"}})
        s = requests.get(f"{API}/tracker/summary", headers=self.h).json()
        assert s["applications"] == before["applications"] + 2
        assert s["interviews_scheduled"] == before["interviews_scheduled"] + 2
        assert s["interviews_verified"] == before["interviews_verified"] + 1
        assert s["application_to_interview_verified"] == round(s["interviews_verified"] * 100 / s["applications"])
        assert s["external"] >= 2 and "saved_jobs" in s

    # ------------------------------------------------------------------ interviews
    def session(self, score, days_ago, dims, status="completed", category="Technical"):
        sid = f"iv_test_{uuid.uuid4().hex[:8]}"
        at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        q = {"question": "Q", "category": category, "status": "answered", "answer": "A",
             "feedback": {"score": score, "dimensions": dims}}
        self.db.interview_sessions.insert_one({
            "session_id": sid, "user_id": self.uid, "job_title": "Recruiter", "interview_type": "HR Interview",
            "status": status, "overall_score": score, "created_at": at, "feedback_mode": "end",
            "questions": [q], "report": {"overall_score": score, "areas_for_improvement": ["Use the STAR method"],
                                         "topics_to_study": ["Boolean search"], "strengths": ["Clear introduction"]}})
        return sid

    def test_readiness_report(self):
        empty = requests.get(f"{API}/career/readiness", headers=self.h).json()
        assert empty["sessions"] == 0 and empty["score"] is None
        self.session(50, 10, {"communication": 4, "role_knowledge": 5})
        self.session(90, 1, {"communication": 9, "role_knowledge": 6}, category="HR")
        self.session(99, 0, {"communication": 10}, status="in_progress")  # not finished: ignored
        d = requests.get(f"{API}/career/readiness", headers=self.h).json()
        assert d["sessions"] == 2
        assert d["score"] == round((90 * 5 + 50 * 4) / 9), "recent sessions count more"
        assert d["level"] == "Nearly ready"
        dims = {x["key"]: x["score"] for x in d["dimensions"]}
        assert dims == {"communication": 65, "role_knowledge": 55}
        assert {c["category"] for c in d["by_category"]} == {"Technical", "HR"}
        assert "Use the STAR method" in d["focus"] and "Study: Boolean search" in d["focus"]
        assert [t["score"] for t in d["trend"]] == [50, 90], "oldest first for the chart"
        assert "Confidence isn't measured" in d["confidence_note"]

    def test_voice_answer_is_recorded_as_text(self):
        sid = f"iv_test_{uuid.uuid4().hex[:8]}"
        self.db.interview_sessions.insert_one({
            "session_id": sid, "user_id": self.uid, "job_title": "Recruiter", "interview_type": "HR Interview",
            "status": "in_progress", "feedback_mode": "end", "created_at": datetime.now(timezone.utc).isoformat(),
            "questions": [{"question": "Tell me about yourself", "category": "Introduction", "status": "pending"}]})
        r = requests.post(f"{API}/career/interviews/{sid}/answer", headers=self.h,
                          json={"index": 0, "answer": "I am a recruiter with five years of experience.", "mode": "voice"})
        assert r.status_code == 200, r.text
        q = r.json()["session"]["questions"][0]
        assert q["answer_mode"] == "voice" and q["status"] == "answered"
