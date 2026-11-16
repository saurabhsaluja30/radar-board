# SmartMatch: expired jobs must not be visible on job detail / dashboard before a sweep runs
import os
from datetime import date, timedelta

import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def _env(key):
    for line in open("/app/backend/.env"):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


DB = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]


class TestExpiry:
    def test_expired_job_detail_hidden(self):
        tok = requests.post(f"{API}/auth/admin/login", json={"email": "admin@eevolvex.com", "password": "Admin@12345"}).json()["token"]
        h = {"Authorization": f"Bearer {tok}"}
        past = (date.today() - timedelta(days=3)).isoformat()
        r = requests.post(f"{API}/admin/jobs", headers=h, json={
            "title": "TEST_EXP Job", "company": "TEST_EXP Co", "location": "Pune", "status": "Published",
            "verification_status": "Verified", "expiry_date": past})
        assert r.status_code == 200, r.text
        jid = r.json()["job"]["job_id"]
        try:
            created_status = r.json()["job"]["status"]
            detail = requests.get(f"{API}/jobs/{jid}").status_code
            print("created status:", created_status, "detail status before sweep:", detail)
            assert detail == 404, "Expired job detail still publicly visible until a sweep runs"
        finally:
            DB.jobs.delete_one({"job_id": jid})
