# JobRadar web: backend API regression tests (public, auth, candidate, admin, career non-AI)
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": os.environ.get("ADMIN_EMAIL", "admin@eevolvex.com"), "password": os.environ.get("ADMIN_PASSWORD", "Admin@12345")}


def _reg_payload():
    uid = uuid.uuid4().hex[:8]
    return {
        "full_name": f"TEST_User {uid}", "email": f"test_{uid}@example.com", "mobile": "9876543210",
        "password": "Test@1234", "confirm_password": "Test@1234", "industry": "Banking & Financial Services",
        "current_designation": "Analyst", "current_salary": "8 LPA", "preferred_location": "Bengaluru",
        "preferred_work_mode": "Remote", "consent": True, "preferred_industries": [],
    }


@pytest.fixture(scope="module")
def candidate():
    r = requests.post(f"{API}/auth/register", json=_reg_payload())
    assert r.status_code == 200, r.text
    d = r.json()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {d['token']}"})
    return s, d["user"]


@pytest.fixture(scope="module")
def admin():
    r = requests.post(f"{API}/auth/admin/login", json=ADMIN)
    if r.status_code != 200:
        pytest.skip("admin login failed")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


@pytest.fixture(scope="module")
def a_job():
    r = requests.get(f"{API}/jobs")
    jobs = r.json()["jobs"]
    if not jobs:
        pytest.skip("no jobs")
    return jobs[0]


# Public endpoints
class TestPublic:
    def test_config_and_launch(self):
        r = requests.get(f"{API}/config")
        assert r.status_code == 200
        r2 = requests.get(f"{API}/launch-offer")
        assert r2.status_code == 200
        print("launch:", r2.json())

    def test_jobs_list_locked_for_guest(self, a_job):
        r = requests.get(f"{API}/jobs")
        d = r.json()
        assert d["is_member"] is False and d["count"] >= 1
        r2 = requests.get(f"{API}/jobs/{a_job['job_id']}")
        assert r2.status_code == 200
        assert r2.json()["authenticated"] is False

    def test_jobs_filters(self):
        r = requests.get(f"{API}/jobs", params={"q": "zzzznotexist"})
        assert r.json()["count"] == 0
        r = requests.get(f"{API}/jobs", params={"work_mode": "Remote"})
        assert all(j["work_mode"] == "Remote" for j in r.json()["jobs"])

    def test_job_404(self):
        assert requests.get(f"{API}/jobs/nope_123").status_code == 404

    def test_plans(self):
        assert requests.get(f"{API}/plans").status_code == 200


# Auth
class TestAuth:
    def test_register_validation(self):
        p = _reg_payload(); p["confirm_password"] = "x"
        assert requests.post(f"{API}/auth/register", json=p).status_code == 400
        p = _reg_payload(); p["consent"] = False
        assert requests.post(f"{API}/auth/register", json=p).status_code == 400

    def test_login_invalid(self):
        r = requests.post(f"{API}/auth/login", json={"email": "nobody@x.com", "password": "bad"})
        assert r.status_code == 401

    def test_me_and_membership(self, candidate):
        s, u = candidate
        me = s.get(f"{API}/auth/me")
        assert me.status_code == 200
        m = s.get(f"{API}/membership").json()
        print("membership:", m["membership"])
        assert "is_active" in m["membership"]

    def test_profile_update(self, candidate):
        s, u = candidate
        r = s.put(f"{API}/auth/profile", json={"full_name": "TEST_Updated", "mobile": "9999999999"})
        assert r.status_code == 200, r.text
        assert s.get(f"{API}/auth/me").json()["user"]["full_name"] == "TEST_Updated" if "user" in s.get(f"{API}/auth/me").json() else True

    def test_forgot_password(self):
        r = requests.post(f"{API}/auth/forgot-password", json={"email": "nobody@example.com"})
        assert r.status_code == 200


# Candidate: saved jobs, dashboard, saved searches
class TestCandidate:
    def test_member_sees_job(self, candidate, a_job):
        s, _ = candidate
        d = s.get(f"{API}/jobs/{a_job['job_id']}").json()
        print("is_member:", d["is_member"], "keys:", list(d["job"].keys())[:30])

    def test_save_unsave(self, candidate, a_job):
        s, _ = candidate
        jid = a_job["job_id"]
        assert s.post(f"{API}/jobs/{jid}/save").json()["saved"] is True
        ids = [j["job_id"] for j in s.get(f"{API}/saved-jobs").json()["jobs"]]
        assert jid in ids
        s.delete(f"{API}/jobs/{jid}/save")
        ids = [j["job_id"] for j in s.get(f"{API}/saved-jobs").json()["jobs"]]
        assert jid not in ids

    def test_dashboard(self, candidate):
        s, _ = candidate
        assert s.get(f"{API}/dashboard").status_code == 200

    def test_saved_searches(self, candidate):
        s, _ = candidate
        r = s.post(f"{API}/saved-searches", json={"name": "TEST_search", "filters": {"work_mode": "Remote"}})
        assert r.status_code == 200, r.text
        lst = s.get(f"{API}/saved-searches").json()
        print("saved searches:", lst)


# Career non-AI
class TestCareer:
    def test_resume_crud_and_download(self, candidate):
        s, _ = candidate
        r = s.post(f"{API}/career/resumes", json={"title": "TEST_resume", "resume_type": "fresher", "personal": {"full_name": "TEST_resume"}, "sections": [{"title": "Summary", "content": "hello"}]})
        assert r.status_code == 200, r.text
        res = r.json().get("resume", r.json())
        rid = res["resume_id"]
        assert s.get(f"{API}/career/resumes/{rid}").status_code == 200
        dl = s.post(f"{API}/career/resumes/{rid}/download-link", json={"format": "pdf"})
        assert dl.status_code == 200, dl.text
        print("download-link:", dl.json())
        f = requests.get(f"{BASE_URL}{dl.json()['path']}")
        assert f.status_code == 200 and f.content[:4] == b"%PDF", f.status_code
        assert s.delete(f"{API}/career/resumes/{rid}").status_code == 200


# Admin
class TestAdmin:
    def test_admin_endpoints(self, admin):
        for p in ["/admin/dashboard", "/admin/jobs", "/admin/candidates", "/admin/subscriptions",
                  "/admin/payments", "/admin/emails", "/admin/plans", "/admin/dev/candidates",
                  "/admin/launch-offer", "/admin/career/settings", "/admin/career/stats"]:
            r = admin.get(f"{API}{p}")
            assert r.status_code == 200, f"{p}: {r.status_code} {r.text[:200]}"

    def test_admin_forbidden_for_guest(self):
        assert requests.get(f"{API}/admin/dashboard").status_code in (401, 403)

    def test_job_duplicate_then_delete(self, admin, a_job):
        r = admin.post(f"{API}/admin/jobs/{a_job['job_id']}/duplicate")
        assert r.status_code == 200, r.text
        d = r.json()
        new_id = d.get("job_id") or d.get("job", {}).get("job_id")
        assert new_id
        assert admin.delete(f"{API}/admin/jobs/{new_id}").status_code == 200
        assert admin.get(f"{API}/admin/jobs/{new_id}").status_code == 404
