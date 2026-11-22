# Phase 6: platform analytics, background-processing status and Starter resource monitoring.
import os
import sys
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import SCHEDULES, recommend  # noqa: E402

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}


# --------------------------------------------------------------------------- unit
def test_recommendation_needs_sustained_pressure():
    assert recommend({"samples": 10})["upgrade"] is False, "too little data never recommends an upgrade"
    calm = {"samples": 600, "cpu_high_pct": 0, "mem_high_pct": 1, "slow_pct": 0}
    assert recommend(calm) == {**recommend(calm), "level": "ok", "upgrade": False}
    assert recommend({**calm, "cpu_high_pct": 8})["level"] == "notice"
    hot = recommend({**calm, "mem_high_pct": 40})
    assert hot["upgrade"] is True and "memory" in hot["message"]


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
class TestOps:
    @classmethod
    def setup_class(cls):
        cls.db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
        cls.h = {"Authorization": "Bearer " + requests.post(f"{API}/auth/admin/login", json=ADMIN).json()["token"]}
        cls.tag = uuid.uuid4().hex[:6]
        cls.jobs = []

    @classmethod
    def teardown_class(cls):
        cls.db.jobs.delete_many({"job_id": {"$in": cls.jobs}})
        cls.db.job_matches.delete_many({"job_id": {"$in": cls.jobs}})
        cls.db.match_queue.delete_many({"ref_id": {"$in": cls.jobs}})
        cls.db.job_log.delete_many({"name": "resume-retry", "at_dt": {"$gte": cls.started}} if hasattr(cls, "started") else {"_id": None})

    def platform(self, **q):
        r = requests.get(f"{API}/admin/analytics/platform", headers=self.h, params=q)
        assert r.status_code == 200, r.text
        return r.json()

    def test_admin_only(self):
        for path in ("/admin/analytics/platform", "/admin/system/health"):
            assert requests.get(f"{API}{path}").status_code in (401, 403)
        assert requests.post(f"{API}/admin/system/sample").status_code in (401, 403)

    def test_platform_sections_and_counts(self):
        before = self.platform()
        for k in ("candidates", "jobs", "smartmatch", "apify", "storage"):
            assert k in before
        assert len(before["candidates"]["resume_trend"]) == 30, "trend defaults to the last 30 days"
        assert before["jobs"]["total"] == self.db.jobs.count_documents({})
        assert before["candidates"]["total"] == self.db.users.count_documents({"role": "candidate"})
        ind = f"TEST_OPS {self.tag}"
        r = requests.post(f"{API}/admin/jobs", headers=self.h, json={
            "title": f"TEST_OPS Analyst {self.tag}", "company": f"TEST_OPS Co {self.tag}", "location": "Pune, India",
            "industry_category": "Finance & Accounting", "job_source": "Company Career Page"})
        assert r.status_code == 200, r.text
        self.jobs.append(r.json()["job"]["job_id"])
        self.db.jobs.update_one({"job_id": self.jobs[-1]}, {"$set": {"industry_category": ind}})
        after = self.platform()
        assert after["jobs"]["total"] == before["jobs"]["total"] + 1
        assert after["jobs"]["added_trend"][-1]["count"] == before["jobs"]["added_trend"][-1]["count"] + 1
        only = self.platform(industry=ind)
        assert only["jobs"]["total"] == 1 and only["jobs"]["by_industry"] == [{"name": ind, "count": 1}]
        assert ind in after["options"]["industries"]

    def test_date_range(self):
        d = self.platform(start="2026-01-01", end="2026-01-07")
        assert len(d["candidates"]["resume_trend"]) == 7 and d["range"] == {"start": "2026-01-01", "end": "2026-01-07"}
        assert d["candidates"]["new_in_range"] is not None
        assert requests.get(f"{API}/admin/analytics/platform", headers=self.h, params={"start": "07/01/2026"}).status_code == 400

    def test_apify_budget_figures(self):
        a = self.platform()["apify"]
        assert len(a["monthly"]) == 6 and a["monthly"][-1]["usd"] == a["month_spend_usd"]
        assert a["month_budget_inr"] == round(a["month_budget_usd"] * a["usd_inr_rate"])
        assert a["month_projected_usd"] >= a["month_spend_usd"]

    def test_health_lists_scheduled_jobs_and_queues(self):
        r = requests.get(f"{API}/admin/system/health", headers=self.h)
        assert r.status_code == 200, r.text
        d = r.json()
        assert [j["name"] for j in d["jobs"]][:len(SCHEDULES)] == list(SCHEDULES)
        assert {"smartmatch", "resumes", "email", "apify"} <= set(d["queues"])
        res = d["resources"]
        assert res["this_replica"]["rss_mb"] > 0 and res["this_replica"]["last_15_min"]["requests"] >= 1
        assert res["database"]["collections"]["jobs"] >= 0 and res["recommendation"]["message"]

    def test_cron_runs_are_recorded(self):
        from datetime import datetime, timezone
        type(self).started = datetime.now(timezone.utc)
        secret = _env("WEBHOOK_CRON_SECRET")
        r = requests.post(f"{API}/cron/resume-retry", headers={"Authorization": f"Bearer {secret}", "X-Webhook-Id": f"test-ops-{self.tag}"}, json={})
        assert r.status_code == 200
        end = time.time() + 10
        while time.time() < end and not self.db.job_log.find_one({"name": "resume-retry", "at_dt": {"$gte": self.started}}):
            time.sleep(0.3)
        log = self.db.job_log.find_one({"name": "resume-retry", "at_dt": {"$gte": self.started}})
        assert log and log["status"] == "ok" and log["duration_ms"] >= 0
        job = next(j for j in requests.get(f"{API}/admin/system/health", headers=self.h).json()["jobs"] if j["name"] == "resume-retry")
        assert job["health"] == "ok" and job["runs_7d"] >= 1 and job["last"]["duration_ms"] is not None
        self.db.cron_runs.delete_one({"run_id": f"test-ops-{self.tag}"})

    def test_manual_sample(self):
        r = requests.post(f"{API}/admin/system/sample", headers=self.h)
        assert r.status_code == 200
        s = r.json()["sample"]
        assert s["rss_mb"] > 0 and "vcpu" in s and s["db_ping_ms"] >= 0
        assert self.db.system_metrics.find_one({"at": s["at"]})
        assert self.db.storage_snapshots.find_one({"day": s["at"][:10]}), "first sample of the day also snapshots storage"
