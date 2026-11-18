# Setup helper for UI tests of job alerts: creates TEST job (verified) + TEST candidates (no pref, to-opt-out). Prints ids as JSON.
import json
import os
import sys
import uuid

import requests

BASE = open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0].rstrip("/")
API = f"{BASE}/api"
UID = sys.argv[1] if len(sys.argv) > 1 else uuid.uuid4().hex[:6]
a = requests.post(f"{API}/auth/admin/login", json={"email": "admin@eevolvex.com", "password": "Admin@12345"}).json()["token"]
H = {"Authorization": f"Bearer {a}"}
j = requests.post(f"{API}/admin/jobs", headers=H, json={
    "title": f"TEST_UI Python Developer {UID}", "company": f"TEST_UI Co {UID}", "location": "Bengaluru",
    "function": "IT & Technology", "industry_category": "IT & Technology", "work_mode": "Remote",
    "required_skills": "Python, React", "preferred_skills": "FastAPI", "experience_min": 3, "experience_max": 7,
    "salary_min": 1200000, "salary_max": 2000000, "status": "Published", "job_source": "Recruiter submission",
    "description": "Test", "application_link": "https://example.com/apply"}).json()["job"]
requests.post(f"{API}/admin/smartmatch/jobs/{j['job_id']}/verify", headers=H, json={"verification_status": "Verified"})
out = {"job_id": j["job_id"], "users": {}}
for tag in ("none", "off"):
    email = f"test_ui_{tag}_{UID}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "full_name": f"TEST_UI {tag}", "email": email, "mobile": "9876543210", "password": "Test@123",
        "confirm_password": "Test@123", "industry": "IT & Technology", "current_designation": "Software Engineer",
        "current_salary": "10 LPA", "preferred_location": "Bengaluru", "preferred_work_mode": "Remote", "consent": True,
        "preferred_industries": ["IT & Technology"]}).json()
    requests.put(f"{API}/auth/profile", headers={"Authorization": f"Bearer {r['token']}"}, json={
        "total_experience": 5, "primary_skills": ["Python", "React", "FastAPI"], "preferred_titles": ["Software Engineer"],
        "preferred_locations": ["Bengaluru"], "expected_ctc": 1500000, "notice_period": "30 days"})
    out["users"][tag] = {"email": email, "uid": r["user"]["user_id"]}
print(json.dumps(out))
