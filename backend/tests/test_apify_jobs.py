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
from apify_jobs import demand_pairs, linkedin_filters, linkedin_search_url, norm_url, normalise  # noqa: E402

BACKEND = os.environ.get("APIFY_TEST_BACKEND_URL")


def _today():
    return datetime.now(timezone.utc).date()  # the server uses UTC dates
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}
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


ZETA_DESC = ("Zeta is a next-generation banking technology company. Responsibilities: deploy and manage container "
             "orchestration, service mesh and CI/CD. Skills: Kubernetes, Terraform, Python. Experience: 2-8 years of "
             "relevant work experience in distributed systems and micro-service based architectures.")


def test_normalise_real_ats_jobs_search_item():
    """Shape copied from a real yugenox/ats-jobs-search run (Nov 2026): countries come as ISO codes."""
    real = {"ats": "lever", "company": "Zeta", "companyToken": "zeta", "jobId": "f827a249-2537-4f7f-aade-25b829fc13f2",
            "title": "Site Reliability Engineer- II", "url": "https://jobs.lever.co/zeta/f827a249-2537-4f7f-aade-25b829fc13f2",
            "applyUrl": "https://jobs.lever.co/zeta/f827a249-2537-4f7f-aade-25b829fc13f2/apply", "location": "Bangalore",
            "allLocations": ["Bangalore"], "countries": ["IN"], "workplaceType": "onsite", "isRemote": False,
            "employmentType": "full-time", "postedAt": _today().isoformat() + "T13:09:24.922Z", "applicationDeadline": None,
            "salaryMin": None, "salaryMax": None, "salaryCurrency": None, "salaryText": None, "descriptionText": ZETA_DESC,
            "internalJobId": None, "companyBoardUrl": "https://jobs.lever.co/zeta"}
    n = normalise(real)
    assert n["country"] == "India" and n["region"] == "India", "ISO code IN must count as India"
    assert (n["city"], n["work_mode"], n["employment_type"]) == ("Bangalore", "Work From Office", "Full-time")
    assert n["application_link"].endswith("/apply") and n["external_id"] == real["jobId"]
    assert n["experience_min"] == 2 and n["experience_max"] == 8 and n["flags"] == []
    assert normalise({**real, "countries": ["US"], "location": "New York"})["region"] == "International"
    assert normalise({**real, "countries": [], "location": "Gurugram"})["region"] == "India"


# Shape copied from a real bebity/linkedin-jobs-scraper run (Nov 2026).
LINKEDIN_ITEM = {
    "id": "4477826957", "publishedAt": "2026-11-21", "salary": "", "title": "Software Development Engineer, AWS DynamoDB",
    "jobUrl": "https://in.linkedin.com/jobs/view/software-development-engineer-aws-dynamodb-at-amazon-web-services-aws-4477826957"
              "?trk=public_jobs_topcard-title",
    "companyName": "Amazon Web Services (AWS)", "companyUrl": "https://www.linkedin.com/company/amazon-web-services?trk=x",
    "location": "Bengaluru, Karnataka, India", "postedTime": "3 days ago", "applicationsCount": "Over 200 applicants",
    "description": ZETA_DESC, "contractType": "Full-time", "experienceLevel": "Mid-Senior level", "workType": "Hybrid",
    "sector": "IT Services and IT Consulting", "applyType": "EXTERNAL", "applyUrl": "", "companyId": "2382910",
    "scrapingInfo": {"page": 1, "index": 2, "inputUrl": "", "title": "Software Engineer", "location": "Bengaluru"},
}


def test_normalise_real_linkedin_item():
    n = normalise({**LINKEDIN_ITEM, "publishedAt": _today().isoformat()})
    assert (n["title"], n["company"]) == ("Software Development Engineer, AWS DynamoDB", "Amazon Web Services (AWS)")
    assert n["original_url"] == "https://www.linkedin.com/jobs/view/4477826957"
    assert n["application_link"].startswith("https://in.linkedin.com/jobs/view/"), "no applyUrl: apply on LinkedIn"
    assert (n["region"], n["city"], n["work_mode"], n["employment_type"]) == ("India", "Bengaluru", "Hybrid", "Full-time")
    assert n["external_id"] == "4477826957" and n["salary_range"] == "" and n["flags"] == []
    assert normalise({**LINKEDIN_ITEM, "applyUrl": "https://acme.com/apply"})["application_link"] == "https://acme.com/apply"


def test_linkedin_levels_and_experience_fit():
    from apify_jobs import experience_fits, linkedin_levels
    assert linkedin_levels(0) == ["1", "2"] and linkedin_levels(5) == ["3", "4"] and linkedin_levels(12) == ["4", "5"]
    assert experience_fits(5, 3, 6) and experience_fits(5, None, None) and experience_fits(5, 6, None)
    assert not experience_fits(5, 10, 15) and not experience_fits(5, 0, 2)


def test_norm_url_linkedin_canonical():
    assert norm_url("https://www.linkedin.com/jobs/view/4485302230/?refId=a&trackingId=b") == \
        "https://www.linkedin.com/jobs/view/4485302230"


def test_demand_pairs_counts_and_caps():
    cands = [
        {"preferred_titles": ["Data Analyst", "Any"], "preferred_locations": ["Pune", "Anywhere"]},
        {"preferred_designation": "data  analyst", "preferred_location": "pune"},  # same pair, other spelling
        {"preferred_titles": "Data Analyst; Travel Consultant", "preferred_locations": "Pune, Mumbai"},
        {"preferred_titles": ["Data Analyst"], "preferred_locations": ["Pune"], "suspended": True},  # ignored
        {"preferred_titles": ["Data Analyst"], "preferred_locations": ["Pune"], "role": "admin"},  # ignored
        {"preferred_titles": ["Travel Consultant"], "preferred_locations": ["Mumbai"]},
        {"preferred_titles": ["Data Analyst"]},  # no city: no pair
    ]
    rows = demand_pairs(cands, max_pairs=20, min_candidates=2)
    assert rows == [{"title": "Data Analyst", "city": "Pune", "candidates": 3},
                    {"title": "Travel Consultant", "city": "Mumbai", "candidates": 2}]
    assert demand_pairs(cands, max_pairs=1, min_candidates=1) == rows[:1]
    assert len(demand_pairs(cands, max_pairs=20, min_candidates=1)) == 4  # + Data Analyst·Mumbai, Travel Consultant·Pune
    assert all(set(r) == {"title", "city", "candidates"} for r in rows), "nothing identifying a candidate"


def test_linkedin_search_url_and_filters():
    assert linkedin_search_url("UI/UX Designer", "Navi Mumbai", 7) == \
        "https://www.linkedin.com/jobs/search?keywords=UI%2FUX+Designer&location=Navi+Mumbai&f_TPR=r604800"
    assert linkedin_search_url("x", "y", 30).endswith("f_TPR=r2592000")
    assert linkedin_filters({"experience": ["Entry level", "Director"], "work_mode": ["Remote"], "employment": ["Internship"],
                             "bogus": ["x"]}) == {"experienceLevels": ["2", "5"], "workTypes": ["2"], "contractTypes": ["I"]}
    assert linkedin_filters({}) == {}


def test_personal_search_helpers():
    from datetime import timedelta as td
    from personal_search import ist_day, next_reset_utc, pair_key, pick_pair, years_of
    late = datetime(2026, 11, 27, 18, 29, tzinfo=timezone.utc)  # 23:59 IST
    assert ist_day(late) == "2026-11-27" and ist_day(late + td(minutes=1)) == "2026-11-28"
    assert next_reset_utc(late) == datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc)
    pairs = {pick_pair(["A", "B"], ["X", "Y"], f"2026-11-{d:02d}") for d in range(1, 5)}
    assert pairs == {("A", "X"), ("A", "Y"), ("B", "X"), ("B", "Y")}, "rotates through every title × city"
    assert pair_key("Data Analyst", "Pune", ["3", "4"]) == pair_key("data analyst", "PUNE", ["4", "3"])
    assert pair_key("Data Analyst", "Pune", ["3", "4"]) != pair_key("Data Analyst", "Pune", ["4"])
    assert (years_of("2-5 years"), years_of(4), years_of(None), years_of("fresher")) == (2.0, 4.0, None, None)


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
        cls.db.users.delete_many({"email": {"$regex": "^test_apify_"}})
        ps_users = [u["user_id"] for u in cls.db.users.find({"email": {"$regex": "^test_ps_"}}, {"user_id": 1})]
        for coll in ("personal_quota", "personal_results", "user_sessions", "job_notifications", "subscriptions"):
            key = "candidate_id" if coll in ("job_notifications", "subscriptions") else "user_id"
            cls.db[coll].delete_many({key: {"$in": ps_users}})
        cls.db.users.delete_many({"user_id": {"$in": ps_users}})
        cls.db.personal_searches.delete_many({"title": {"$regex": "^TEST_PS"}})
        cls.db.apify_runs.delete_many({"trigger": "personal"})
        cls.db.job_sources.delete_many({"source_type": "Personal search", "keywords": {"$regex": "^TEST_PS"}})
        cls.db.jobs.delete_many({"company": {"$regex": "^TEST_PS"}})
        cls.db.apify_runs.delete_many({"source_ids": "src_demand"})
        cls.db.job_sources.delete_many({"source_id": "src_demand"})
        cls.db.jobs.delete_many({"source_id": "src_demand"})

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
        bad = {"name": "TEST_APIFY Naukri", "url": "https://www.naukri.com/jobs", "permission_status": "Approved", "enabled": True}
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

    def test_poll_imports_a_run_without_webhook(self):
        api, h = self.api, self.h
        self.settings()
        r = requests.post(f"{api}/admin/sources", headers=h, json={
            "name": "TEST_APIFY Poll Co", "url": "https://jobs.lever.co/testapifypoll", "enabled": True,
            "permission_status": "Approved", "permission_note": "Public Lever board"})
        assert r.status_code == 200, r.text
        sid = r.json()["source"]["source_id"]
        Fake.items, Fake.events, Fake.status = [item(91, company="TEST_APIFY Poll Co", countries=["IN"], location="Pune")], 1, "SUCCEEDED"
        run = requests.post(f"{api}/admin/sources/run", headers=h, json={"source_ids": [sid]}).json()["runs"][0]
        secret = os.environ.get("WEBHOOK_CRON_SECRET", "local-dev-cron-secret")
        assert requests.post(f"{api}/cron/apify-poll", headers={"Authorization": "Bearer wrong"}).status_code == 401
        # No webhook is sent: the poll alone must import the finished run.
        assert requests.post(f"{api}/cron/apify-poll", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
        for _ in range(40):
            doc = self.db.apify_runs.find_one({"run_id": run["run_id"]})
            if doc.get("processed"):
                break
            time.sleep(0.25)
        assert doc["processed"] and doc["summary"]["created"] == 1
        job = self.db.jobs.find_one({"source_id": sid})
        assert job["region"] == "India" and job["country"] == "India" and job["review_status"] == "new_import"

    def test_linkedin_source_uses_linkedin_actor(self):
        api, h = self.api, self.h
        self.settings(default_keywords=["Software Engineer"], default_locations=["Bengaluru"], max_items_per_run=40,
                      posted_within_days=7)
        r = requests.post(f"{api}/admin/sources", headers=h, json={
            "name": "TEST_APIFY LinkedIn Co", "url": "https://www.linkedin.com/company/testapifyli/", "enabled": True,
            "permission_status": "Approved", "permission_note": "LinkedIn via Apify"})
        assert r.status_code == 200, r.text
        src = r.json()["source"]
        assert src["actor_id"] == "bebity/linkedin-jobs-scraper"
        li = {**LINKEDIN_ITEM, "companyName": "TEST_APIFY LinkedIn Co", "title": "TEST_APIFY SDE",
              "companyUrl": "https://www.linkedin.com/company/testapifyli?trk=x"}
        Fake.started.clear()
        doc = self.run_and_import(src["source_id"], [li, {**li, "jobUrl": li["jobUrl"].replace("in.linkedin", "www.linkedin")}], 2)
        started = Fake.started[-1]
        assert started["actor"] == "bebity~linkedin-jobs-scraper"
        assert started["input"]["titles"] == ["Software Engineer"] and started["input"]["locations"] == ["Bengaluru"]
        assert started["input"]["companyUrls"] == ["https://www.linkedin.com/company/testapifyli/"]
        assert started["input"]["rows"] == 40 and started["input"]["publishedAt"] == "r604800"
        assert started["input"]["enrichCompany"] is False
        # The same job seen on in.linkedin.com and www.linkedin.com is one job.
        assert doc["summary"]["created"] == 1 and doc["summary"]["skipped"] == 1
        job = self.db.jobs.find_one({"source_id": src["source_id"]})
        assert job["original_url"] == "https://www.linkedin.com/jobs/view/4477826957" and job["region"] == "India"

    def test_job_search_needs_no_url(self):
        api, h = self.api, self.h
        self.settings(posted_within_days=7, max_items_per_run=60)
        base = {"name": "TEST_APIFY Search Travel", "source_type": "Job search (LinkedIn)", "permission_status": "Approved",
                "enabled": True}
        assert requests.post(f"{api}/admin/sources", headers=h, json={**base, "keywords": ["Travel Consultant"]}).status_code == 400
        assert requests.post(f"{api}/admin/sources", headers=h, json={**base, "keywords": ["x"], "locations": ["y"],
                                                                      "filters": {"work_mode": ["Moon"]}}).status_code == 400
        body = {**base, "keywords": ["Travel Consultant", "Ticketing Executive"], "locations": ["Mumbai"],
                "filters": {"experience": ["Entry level", "Associate"], "work_mode": ["Hybrid"]}}
        r = requests.post(f"{api}/admin/sources", headers=h, json=body)
        assert r.status_code == 200, r.text
        src = r.json()["source"]
        assert src["url"] == "" and src["actor_id"] == "bebity/linkedin-jobs-scraper"
        assert requests.post(f"{api}/admin/sources", headers=h, json=body).status_code == 400, "same search twice"
        li = {**LINKEDIN_ITEM, "companyName": "TEST_APIFY Skyways", "title": "TEST_APIFY Travel Consultant",
              "jobUrl": "https://in.linkedin.com/jobs/view/travel-consultant-4400000101", "location": "Mumbai, Maharashtra, India"}
        doc = self.run_and_import(src["source_id"], [li], 1)
        inp = Fake.started[-1]["input"]
        assert Fake.started[-1]["actor"] == "bebity~linkedin-jobs-scraper"
        assert inp["titles"] == ["Travel Consultant", "Ticketing Executive"] and inp["locations"] == ["Mumbai"]
        assert sorted(inp["experienceLevels"]) == ["2", "3"]
        assert inp["workTypes"] == ["3"] and inp["rows"] == 30 and inp["publishedAt"] == "r604800"
        assert doc["summary"]["created"] == 1
        job = self.db.jobs.find_one({"source_id": src["source_id"]})
        assert job["review_status"] == "new_import" and job["status"] == "Draft" and job["region"] == "India"

    def test_candidate_demand_search(self):
        api, h = self.api, self.h
        for i, (title, city) in enumerate([("TEST_APIFY Pilot", "Testpur"), ("TEST_APIFY Pilot", "Testpur"),
                                           ("test_apify pilot", "TESTPUR"), ("TEST_APIFY Cabin Crew", "Testpur")]):
            self.db.users.insert_one({"user_id": f"user_testapify{i}", "email": f"test_apify_{i}@example.com", "role": "candidate",
                                      "full_name": f"Secret Name {i}", "preferred_titles": [title], "preferred_locations": [city],
                                      "suspended": False})
        self.settings(demand_search_enabled=False, demand_min_candidates=3, demand_max_pairs=20, demand_jobs_per_pair=5)
        pv = requests.get(f"{api}/admin/apify/demand-preview", headers=h).json()
        mine = [p for p in pv["pairs"] if p["title"].lower().startswith("test_apify")]
        assert mine == [{"title": "TEST_APIFY Pilot", "city": "Testpur", "candidates": 3}], pv
        assert not (self.db.job_sources.find_one({"source_id": "src_demand"}) or {}).get("enabled")

        self.settings(demand_search_enabled=True, demand_min_candidates=3, demand_max_pairs=20, demand_jobs_per_pair=5)
        row = self.db.job_sources.find_one({"source_id": "src_demand"})
        assert row["enabled"] and row["managed"] and row["source_type"] == "Candidate demand search"
        url = "https://www.linkedin.com/jobs/search?keywords=TEST_APIFY+Pilot&location=Testpur&f_TPR=r2592000"
        assert url in row["actor_input"]["startUrls"]
        assert requests.put(f"{api}/admin/sources/src_demand", headers=h, json={
            "name": "x", "url": "https://jobs.lever.co/x", "permission_status": "Approved"}).status_code == 400
        li = {**LINKEDIN_ITEM, "companyName": "TEST_APIFY Airways", "title": "TEST_APIFY Pilot",
              "jobUrl": "https://www.linkedin.com/jobs/view/4400000102", "location": "Testpur, India"}
        doc = self.run_and_import("src_demand", [li], 1)
        started = Fake.started[-1]
        assert started["actor"] == "bebity~linkedin-jobs-scraper" and url in started["input"]["startUrls"]
        assert started["input"]["maxRowsPerUrl"] == 5 and started["input"]["enrichCompany"] is False
        assert "Secret Name" not in json.dumps(started["input"]) and "example.com" not in json.dumps(started["input"])
        assert doc["summary"]["created"] == 1
        assert self.db.jobs.find_one({"source_id": "src_demand"})["review_status"] == "new_import"

        self.settings(demand_search_enabled=False)
        assert self.db.job_sources.find_one({"source_id": "src_demand"})["enabled"] is False

    def test_admin_linkedin_search_by_title_and_experience(self):
        api, h = self.api, self.h
        self.settings(default_locations=["Bengaluru"])
        body = {"title": "TEST_APIFY Software Engineer", "experience_years": 5, "max_items": 30}
        self.settings(default_locations=["Bengaluru"], paid_runs_approved=False)
        assert requests.post(f"{api}/admin/apify/linkedin-search", headers=h, json=body).status_code == 409
        assert not self.db.job_sources.find_one({"name": {"$regex": "TEST_APIFY Software Engineer"}}), "nothing saved when it can't run"
        self.settings(default_locations=["Bengaluru"])
        Fake.started.clear()
        r = requests.post(f"{api}/admin/apify/linkedin-search", headers=h, json=body)
        assert r.status_code == 200, r.text
        src, run = r.json()["source"], r.json()["runs"][0]
        inp = Fake.started[-1]["input"]
        assert Fake.started[-1]["actor"] == "bebity~linkedin-jobs-scraper"
        assert inp["titles"] == ["TEST_APIFY Software Engineer"] and inp["locations"] == ["Bengaluru"]
        assert inp["experienceLevels"] == ["3", "4"] and inp["rows"] == 30
        assert src["frequency"] == "manual" and src["name"].startswith("LinkedIn: TEST_APIFY Software Engineer, 5 yrs")
        # Import: a 4-7 year job fits, a 10-15 year job is flagged.
        senior = ZETA_DESC.replace("2-8 years", "10-15 years")
        Fake.items = [{**LINKEDIN_ITEM, "id": "4400000002", "jobUrl": "https://in.linkedin.com/jobs/view/sde-4400000002", "title": "TEST_APIFY SDE II", "companyName": "TEST_APIFY Li", "description": ZETA_DESC.replace("2-8", "4-7")},
                      {**LINKEDIN_ITEM, "id": "4400000001", "jobUrl": "https://in.linkedin.com/jobs/view/staff-4400000001",
                       "title": "TEST_APIFY Staff Engineer", "companyName": "TEST_APIFY Li", "description": senior}]
        Fake.events, Fake.status = 2, "SUCCEEDED"
        requests.post(f"{api}/apify/webhook", json={"resource": {"id": run["apify_run_id"]}}, headers={"X-JobRadar-Webhook": "hook-secret"})
        for _ in range(40):
            doc = self.db.apify_runs.find_one({"run_id": run["run_id"]})
            if doc.get("processed"):
                break
            time.sleep(0.25)
        assert doc["summary"]["created"] == 2, doc
        flags = {j["title"]: j["flags"] for j in self.db.jobs.find({"source_id": src["source_id"]})}
        assert "experience_mismatch" not in flags["TEST_APIFY SDE II"]
        assert "experience_mismatch" in flags["TEST_APIFY Staff Engineer"]
        # The same search again within 15 minutes is refused; bad input is rejected.
        assert requests.post(f"{api}/admin/apify/linkedin-search", headers=h, json=body).status_code == 409
        assert requests.post(f"{api}/admin/apify/linkedin-search", headers=h, json={**body, "experience_years": 99}).status_code == 400
        assert requests.post(f"{api}/admin/apify/linkedin-search", headers=h, json={**body, "title": " "}).status_code == 400
        self.db.job_sources.delete_one({"source_id": src["source_id"]})
        self.db.jobs.delete_many({"source_id": src["source_id"]})
        self.db.apify_runs.delete_many({"source_ids": src["source_id"]})

    # ------------------------------------------------------------------ candidate "Find jobs for me"
    def candidate(self, name, title, city, years=3, paid=False):
        from datetime import timedelta as td
        uid = f"user_testps_{name}"
        self.db.users.insert_one({"user_id": uid, "email": f"test_ps_{name}@example.com", "role": "candidate",
                                  "full_name": f"PS {name}", "preferred_titles": [title], "preferred_locations": [city],
                                  "total_experience": years, "suspended": False, "created_at": datetime.now(timezone.utc).isoformat()})
        tok = f"tok_testps_{name}_{uuid.uuid4().hex[:6]}"
        self.db.user_sessions.insert_one({"session_token": tok, "user_id": uid,
                                          "expires_at": (datetime.now(timezone.utc) + td(days=1)).isoformat()})
        if paid:
            self.db.subscriptions.insert_one({"subscription_id": f"sub_testps_{name}", "candidate_id": uid, "status": "active",
                                              "plan_id": "monthly", "plan_name": "Monthly",
                                              "start_date": datetime.now(timezone.utc).isoformat(),
                                              "expiry_date": (datetime.now(timezone.utc) + td(days=30)).isoformat(),
                                              "created_at": datetime.now(timezone.utc).isoformat()})
        return uid, {"Authorization": f"Bearer {tok}"}

    def ps_items(self, base, n, title="TEST_PS Analyst"):
        return [{**LINKEDIN_ITEM, "id": str(base + i), "title": f"{title} {i}", "companyName": f"TEST_PS Co {i}",
                 "jobUrl": f"https://www.linkedin.com/jobs/view/{base + i}", "location": "Testabad, India"} for i in range(n)]

    def finish(self, run_id, items):
        Fake.items, Fake.events, Fake.status = items, len(items), "SUCCEEDED"
        apify_run = self.db.apify_runs.find_one({"run_id": run_id})["apify_run_id"]
        requests.post(f"{self.api}/apify/webhook", json={"resource": {"id": apify_run}}, headers={"X-JobRadar-Webhook": "hook-secret"})
        for _ in range(40):
            if self.db.apify_runs.find_one({"run_id": run_id}).get("processed"):
                time.sleep(0.3)  # delivery runs right after the import
                return
            time.sleep(0.25)
        raise AssertionError("run was not imported")

    def test_personal_search(self):
        from concurrent.futures import ThreadPoolExecutor
        api = self.api
        self.settings(personal_search_enabled=False)
        a_id, a = self.candidate("a", "TEST_PS Analyst", "Testabad")
        assert requests.post(f"{api}/me/job-search", headers=a).status_code == 503, "off by default"
        self.settings(personal_search_enabled=True, personal_free_jobs=5, personal_paid_jobs=10, personal_daily_cap_usd=2,
                      personal_db_threshold=10, personal_max_parallel=5, posted_within_days=7)
        assert requests.get(f"{api}/me/job-search", headers=self.h).status_code == 403, "candidates only"

        # Ten clicks at once start exactly one Apify run.
        before = len(Fake.started)
        with ThreadPoolExecutor(10) as ex:
            codes = list(ex.map(lambda _: requests.post(f"{api}/me/job-search", headers=a).status_code, range(10)))
        assert codes == [200] * 10, codes
        assert len(Fake.started) == before + 1
        inp = Fake.started[-1]["input"]
        assert inp["titles"] == ["TEST_PS Analyst"] and inp["locations"] == ["Testabad"] and inp["rows"] == 10
        assert inp["experienceLevels"] == ["3", "4"] and inp["publishedAt"] == "r604800"
        assert "PS a" not in json.dumps(inp) and "example.com" not in json.dumps(inp)
        st = requests.get(f"{api}/me/job-search", headers=a).json()
        assert st["status"] == "running" and st["searching_for"]["title"] == "TEST_PS Analyst"
        run_id = self.db.apify_runs.find({"trigger": "personal"}).sort("started_at", -1)[0]["run_id"]
        assert self.db.job_sources.find_one({"source_id": self.db.apify_runs.find_one({"run_id": run_id})["source_ids"][0]})["hidden"]
        srcs = requests.get(f"{api}/admin/sources", headers=self.h).json()["sources"]
        assert not [x for x in srcs if x.get("source_type") == "Personal search"], "hidden from the admin list"

        # A paid candidate wanting the same search joins it: no second Apify run.
        b_id, b = self.candidate("b", "TEST_PS Analyst", "Testabad", years=4, paid=True)
        assert requests.post(f"{api}/me/job-search", headers=b).json()["mode"] == "shared"
        assert len(Fake.started) == before + 1

        self.finish(run_id, self.ps_items(4600000100, 7))
        st_a = requests.get(f"{api}/me/job-search", headers=a).json()
        st_b = requests.get(f"{api}/me/job-search", headers=b).json()
        assert (st_a["status"], st_a["delivered_today"], len(st_a["jobs"]), st_a["limit"]) == ("done", 5, 5, 5)
        assert (st_b["status"], st_b["delivered_today"], len(st_b["jobs"]), st_b["limit"]) == ("done", 7, 7, 10)
        assert self.db.job_notifications.count_documents({"candidate_id": a_id, "source": "personal_search"}) == 1
        job = self.db.jobs.find_one({"job_id": st_a["jobs"][0]["job_id"]})
        assert job["status"] == "Draft" and job["review_status"] == "new_import", "still goes to admin review"

        # Done for today: another click starts nothing.
        assert requests.post(f"{api}/me/job-search", headers=a).json()["mode"] == "already"
        assert len(Fake.started) == before + 1

        # A third candidate joining the finished search later gets it instantly, at no Apify cost.
        c_id, c = self.candidate("c", "TEST_PS Analyst", "Testabad")
        res = requests.post(f"{api}/me/job-search", headers=c).json()
        assert res["mode"] == "shared" and res["status"] == "done" and res["delivered_today"] == 5
        assert len(Fake.started) == before + 1

        # Delivered jobs are visible to their candidate only, before an admin publishes them.
        jid = st_a["jobs"][0]["job_id"]
        assert requests.get(f"{api}/jobs/{jid}", headers=a).status_code == 200
        d_id, d = self.candidate("d", "TEST_PS Painter", "Testabad")
        assert requests.get(f"{api}/jobs/{jid}", headers=d).status_code == 404
        assert requests.get(f"{api}/jobs/{jid}").status_code == 404

        # An empty search gives the day back.
        assert requests.post(f"{api}/me/job-search", headers=d).json()["mode"] == "started"
        run_d = self.db.apify_runs.find({"trigger": "personal"}).sort("started_at", -1)[0]["run_id"]
        self.finish(run_d, [])
        assert requests.get(f"{api}/me/job-search", headers=d).json()["status"] == "free"

        # A search stuck for over 10 minutes is released on the next click.
        e_id, e = self.candidate("e", "TEST_PS Welder", "Testabad")
        assert requests.post(f"{api}/me/job-search", headers=e).json()["mode"] == "started"
        n = len(Fake.started)
        old = (datetime.now(timezone.utc) - __import__("datetime").timedelta(minutes=11)).isoformat()
        self.db.personal_quota.update_one({"user_id": e_id}, {"$set": {"started_at": old}})
        self.db.personal_searches.update_one({"title": "TEST_PS Welder"}, {"$set": {"created_at": old}})
        assert requests.post(f"{api}/me/job-search", headers=e).json()["mode"] == "started"
        assert len(Fake.started) == n + 1

        # The daily spending cap pauses live searches.
        self.settings(personal_search_enabled=True, personal_daily_cap_usd=0)
        f_id, f = self.candidate("f", "TEST_PS Baker", "Testabad")
        r = requests.post(f"{api}/me/job-search", headers=f)
        assert r.status_code == 429 and "paused" in r.json()["detail"]
        assert requests.get(f"{api}/me/job-search", headers=f).json()["status"] == "free"

        # No preferences: ask for a CV first.
        g_id, g = self.candidate("g", "", "")
        self.db.users.update_one({"user_id": g_id}, {"$set": {"preferred_titles": [], "preferred_locations": []}})
        self.settings(personal_search_enabled=True)
        assert requests.post(f"{api}/me/job-search", headers=g).status_code == 400
        assert requests.get(f"{api}/admin/apify/overview", headers=self.h).json()["personal_today"]["runs"] >= 3
        self.settings(personal_search_enabled=False)

    def test_cron_once_per_day(self):
        secret = os.environ.get("WEBHOOK_CRON_SECRET", "local-dev-cron-secret")
        assert requests.post(f"{self.api}/cron/apify-daily", headers={"Authorization": "Bearer wrong"}).status_code == 401
        for _ in range(2):
            assert requests.post(f"{self.api}/cron/apify-daily", headers={"Authorization": f"Bearer {secret}"}).status_code == 200
        assert self.db.cron_runs.count_documents({"run_id": f"apify-daily-{_today().isoformat()}"}) == 1
