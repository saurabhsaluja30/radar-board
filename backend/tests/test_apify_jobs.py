# Apify job discovery: normalisation (unit) and the full source → run → import → review flow against a fake Apify API.
#
# The flow test needs a backend started with:
#   APIFY_API_BASE=http://127.0.0.1:8099 APIFY_TOKEN=test-token APIFY_WEBHOOK_SECRET=hook-secret
#   PUBLIC_BACKEND_URL=http://127.0.0.1:<port> WEBHOOK_CRON_SECRET=<secret>
# and APIFY_TEST_BACKEND_URL pointing at it. It is skipped otherwise.
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apify_jobs import norm_url, normalise  # noqa: E402

BACKEND = os.environ.get("APIFY_TEST_BACKEND_URL")


def _today():
    return datetime.now(timezone.utc).date()  # the server uses UTC dates
ADMIN = {"email": "admin@eevolvex.com", "password": "Admin@12345"}
LONG = "We are hiring a travel consultant to handle ticketing on Sabre and Amadeus. " * 5 + "Requires 2-5 years experience."


def item(n, **kw):
    base = {"title": f"TEST_APIFY Travel Consultant {n}", "company": "TEST_APIFY Air", "location": "Mumbai, India",
            "countries": ["India"], "url": f"https://job-boards.greenhouse.io/testapifyair/jobs/{n}?gh_src=abc",
            "applyUrl": f"https://job-boards.greenhouse.io/testapifyair/jobs/{n}#app", "descriptionText": LONG,
            "postedAt": _today().isoformat() + "T00:00:00Z", "workplaceType": "hybrid", "employmentType": "Full-time",
            "companyBoardUrl": "https://job-boards.greenhouse.io/testapifyair", "changeType": "new", "jobId": str(n)}
    base.update(kw)
    return base


# --------------------------------------------------------------------------- unit
def test_norm_url_strips_tracking():
    assert norm_url("https://Jobs.Lever.co/acme/123/?utm_source=x&lever-source=y&team=ops") == "https://jobs.lever.co/acme/123?team=ops"
    assert norm_url("javascript:alert(1)") is None


def test_normalise_ats_item():
    n = normalise(item(1))
    assert n["title"] == "TEST_APIFY Travel Consultant 1" and n["company"] == "TEST_APIFY Air"
    assert n["original_url"] == "https://job-boards.greenhouse.io/testapifyair/jobs/1"
    assert n["work_mode"] == "Hybrid" and n["employment_type"] == "Full-time" and n["region"] == "India"
    assert n["experience_min"] == 2 and n["experience_max"] == 5
    assert "sabre" in n["required_skills"] and n["flags"] == []


def test_normalise_never_invents():
    n = normalise({"title": "Analyst", "url": "https://example.com/j/1", "description": "Pay a registration fee to apply"})
    assert n["work_mode"] is None and n["employment_type"] is None and n["salary_min"] is None
    assert n["experience_min"] is None and n["company"] == "" and n["region"] is None
    assert set(n["flags"]) == {"incomplete", "suspicious"}


def test_normalise_fantastic_jobs_shape():
    n = normalise({"title": "HR Executive", "organization": "Acme", "url": "https://acme.wd3.myworkdayjobs.com/x/job/1",
                   "description_text": "x" * 300, "locations_derived": ["Pune, Maharashtra, India"],
                   "countries_derived": ["India"], "ai_work_arrangement": "Remote OK", "employment_type": ["FULL_TIME"],
                   "date_posted": "2026-11-01T10:00:00", "ai_salary_min_value": 500000, "ai_salary_currency": "INR"})
    assert (n["company"], n["location"], n["work_mode"], n["employment_type"]) == ("Acme", "Pune, Maharashtra, India", "Remote", "Full-time")
    assert n["salary_min"] == 500000 and n["currency"] == "INR" and n["original_posted_at"] == "2026-11-01"


# --------------------------------------------------------------------------- fake Apify API
class Fake:
    items: list = []
    status = "SUCCEEDED"
    started: list = []
    events = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlsplit(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if u.path.startswith("/v2/acts/") and u.path.endswith("/runs"):
            rid = f"fake_{uuid.uuid4().hex[:8]}"
            Fake.started.append({"actor": u.path.split("/")[3], "input": body, "params": parse_qs(u.query),
                                 "auth": self.headers.get("Authorization"), "id": rid})
            return self.send({"data": {"id": rid, "defaultDatasetId": f"ds_{rid}", "status": "RUNNING"}}, 201)
        self.send({"error": "not found"}, 404)

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path.startswith("/v2/actor-runs/"):
            return self.send({"data": {"id": u.path.rsplit("/", 1)[-1], "status": Fake.status, "finishedAt": "2026-11-19T10:00:00Z",
                                       "chargedEventCounts": {"Job": Fake.events},
                                       "pricingInfo": {"pricingPerEvent": {"actorChargeEvents": {"Job": {"eventPriceUsd": 0.002}}}}}})
        if u.path.startswith("/v2/datasets/"):
            return self.send(Fake.items)
        if u.path == "/v2/users/me/limits":
            return self.send({"data": {"current": {"monthlyUsageUsd": 0.42}, "limits": {"maxMonthlyUsageUsd": 5}}})
        self.send({"error": "not found"}, 404)


@pytest.mark.skipif(not BACKEND, reason="needs a backend wired to the fake Apify API (APIFY_TEST_BACKEND_URL)")
class TestApifyFlow:
    @classmethod
    def setup_class(cls):
        from pymongo import MongoClient
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 8099), Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.api = BACKEND.rstrip("/") + "/api"
        tok = requests.post(f"{cls.api}/auth/admin/login", json=ADMIN).json()["token"]
        cls.h = {"Authorization": f"Bearer {tok}"}
        cls.db = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))[os.environ.get("DB_NAME", "radar_board")]
        cls.prev = cls.db.app_settings.find_one({"key": "apify"}, {"_id": 0})
        cls.cleanup()

    @classmethod
    def cleanup(cls):
        cls.db.jobs.delete_many({"company": {"$regex": "^TEST_APIFY"}})
        srcs = [s["source_id"] for s in cls.db.job_sources.find({"name": {"$regex": "^TEST_APIFY"}})]
        cls.db.job_sources.delete_many({"source_id": {"$in": srcs}})
        cls.db.apify_runs.delete_many({"source_ids": {"$in": srcs}})
        cls.db.job_import_logs.delete_many({"title": {"$regex": "^TEST_APIFY"}})

    @classmethod
    def teardown_class(cls):
        cls.srv.shutdown()
        cls.cleanup()
        cls.db.app_settings.delete_one({"key": "apify"})
        if cls.prev:
            cls.db.app_settings.insert_one(cls.prev)

    def settings(self, **kw):
        body = {"actor_id": "yugenox/ats-jobs-search", "default_keywords": ["consultant"], "default_locations": ["India"],
                "max_items_per_run": 50, "max_items_per_company": 25, "posted_within_days": 30, "monthly_budget_usd": 5,
                "per_run_cap_usd": 1, "paid_runs_approved": True, "auto_daily": True}
        body.update(kw)
        r = requests.put(f"{self.api}/admin/apify/settings", headers=self.h, json=body)
        assert r.status_code == 200, r.text

    def run_and_import(self, sid, items, events):
        Fake.items, Fake.events, Fake.status = items, events, "SUCCEEDED"
        r = requests.post(f"{self.api}/admin/sources/run", headers=self.h, json={"source_ids": [sid]})
        assert r.status_code == 200, r.text
        run = r.json()["runs"][0]
        bad = requests.post(f"{self.api}/apify/webhook", json={"resource": {"id": run["apify_run_id"]}},
                            headers={"X-JobRadar-Webhook": "wrong"})
        assert bad.status_code == 401
        ok = requests.post(f"{self.api}/apify/webhook", json={"resource": {"id": run["apify_run_id"]}},
                           headers={"X-JobRadar-Webhook": "hook-secret"})
        assert ok.json()["accepted"] is True
        for _ in range(40):
            doc = self.db.apify_runs.find_one({"run_id": run["run_id"]})
            if doc.get("processed"):
                return doc
            time.sleep(0.25)
        raise AssertionError("run was not imported")

    def test_flow(self):
        api, h = self.api, self.h
        self.settings(paid_runs_approved=False)
        bad = {"name": "TEST_APIFY LinkedIn", "url": "https://www.linkedin.com/jobs", "permission_status": "Approved", "enabled": True}
        assert requests.post(f"{api}/admin/sources", headers=h, json=bad).status_code == 400
        pending = {"name": "TEST_APIFY Air", "url": "https://job-boards.greenhouse.io/testapifyair", "enabled": True,
                   "permission_status": "Pending review"}
        assert requests.post(f"{api}/admin/sources", headers=h, json=pending).status_code == 400
        r = requests.post(f"{api}/admin/sources", headers=h, json={**pending, "permission_status": "Approved",
                                                                    "permission_note": "Public Greenhouse board"})
        assert r.status_code == 200, r.text
        sid = r.json()["source"]["source_id"]

        # Paid runs need admin approval first.
        assert requests.post(f"{api}/admin/sources/run", headers=h, json={"source_ids": [sid]}).status_code == 409
        self.settings()

        # A manual job with the same company/title/location as an import → flagged as possible duplicate.
        manual = requests.post(f"{api}/admin/jobs", headers=h, json={
            "title": "TEST_APIFY Travel Consultant 3", "company": "TEST_APIFY Air", "location": "Mumbai, India",
            "status": "Draft", "verification_status": "Pending Verification"}).json()["job"]
        items = [item(1), item(2, descriptionText="Pay a registration fee via WhatsApp us now"), item(3),
                 item(4, title=""), item(1)]
        doc = self.run_and_import(sid, items, events=4)
        started = Fake.started[-1]
        assert started["auth"] == "Bearer test-token" and started["input"]["companies"] == [pending["url"]]
        assert started["input"]["onlyNewOrChanged"] is True and float(started["params"]["maxTotalChargeUsd"][0]) <= 1
        assert "webhooks" in started["params"]
        assert doc["status"] == "SUCCEEDED" and doc["cost_usd"] == 0.008
        assert doc["summary"]["created"] == 3 and doc["summary"]["skipped"] == 2 and doc["summary"]["duplicates"] == 1

        jobs = {j["title"]: j for j in self.db.jobs.find({"source_id": sid})}
        j1, j2, j3 = (jobs[f"TEST_APIFY Travel Consultant {n}"] for n in (1, 2, 3))
        assert (j1["status"], j1["verification_status"], j1["review_status"]) == ("Draft", "Pending Verification", "new_import")
        assert "suspicious" in j2["flags"] and j3["duplicate_of"] == manual["job_id"]
        public = {j["job_id"] for j in requests.get(f"{api}/jobs", params={"q": "TEST_APIFY"}).json()["jobs"]}
        assert not public & {j1["job_id"], j2["job_id"], j3["job_id"]}, "unreviewed imports must not be public"

        # Review: publishing needs an industry; then the job is public.
        res = requests.post(f"{api}/admin/imports/action", headers=h, json={"job_ids": [j1["job_id"]], "action": "publish"}).json()
        assert res["skipped"] and not res["done"]
        res = requests.post(f"{api}/admin/imports/action", headers=h, json={
            "job_ids": [j1["job_id"]], "action": "publish", "industry_category": "Travel & Hospitality"}).json()
        assert res["done"] == [j1["job_id"]]
        requests.post(f"{api}/admin/imports/action", headers=h, json={"job_ids": [j2["job_id"]], "action": "reject"})
        assert j1["job_id"] in {j["job_id"] for j in requests.get(f"{api}/jobs", params={"q": "TEST_APIFY"}).json()["jobs"]}
        assert self.db.jobs.find_one({"job_id": j2["job_id"]})["verification_status"] == "Rejected"

        # Next run: the published job changed at source (kept, flagged) and job 3 closed (expires, leaves the site).
        self.db.job_sources.update_one({"source_id": sid}, {"$set": {"last_checked_at": None}})
        doc2 = self.run_and_import(sid, [item(1, title="TEST_APIFY Travel Consultant 1", descriptionText=LONG + " Updated."),
                                         item(3, changeType="closed")], events=1)
        assert doc2["summary"]["changed_at_source"] == 1 and doc2["summary"]["closed"] == 1
        j1b = self.db.jobs.find_one({"job_id": j1["job_id"]})
        assert "source_changed" in j1b["flags"] and j1b["description"] == LONG and "Updated" in j1b["source_snapshot"]["description"]
        assert self.db.jobs.find_one({"job_id": j3["job_id"]})["expiry_date"] == _today().isoformat()
        hist = requests.get(f"{api}/admin/imports/{j1['job_id']}", headers=h).json()["history"]
        acts = [x["action"] for x in hist]
        assert acts[0] == "changed_at_source" and "created" in acts and "skipped" in acts  # skipped = repeated within run 1

        # Overview: spend, totals and Apify's own usage figure.
        ov = requests.get(f"{api}/admin/apify/overview", headers=h).json()
        assert ov["token_configured"] and ov["webhook_configured"] and ov["apify_usage"]["month_usage_usd"] == 0.42
        assert ov["month_spend_usd"] >= 0.01

        # Budget guard: nothing starts once the month's budget is used up.
        self.settings(monthly_budget_usd=0.005)
        self.db.job_sources.update_one({"source_id": sid}, {"$set": {"last_checked_at": None}})
        r = requests.post(f"{api}/admin/sources/run", headers=h, json={"source_ids": [sid]})
        assert r.status_code == 409 and "budget" in r.json()["detail"]
        self.db.jobs.delete_one({"job_id": manual["job_id"]})

    def test_cron_once_per_day(self):
        secret = os.environ.get("WEBHOOK_CRON_SECRET", "local-dev-cron-secret")
        assert requests.post(f"{self.api}/cron/apify-daily", headers={"Authorization": "Bearer wrong"}).status_code == 401
        for _ in range(2):
            assert requests.post(f"{self.api}/cron/apify-daily", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
        assert self.db.cron_runs.count_documents({"run_id": f"apify-daily-{_today().isoformat()}"}) == 1
