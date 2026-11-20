# Resume upload, parsing, confirmation, deletion and the Admin Candidate Talent Database.
# Runs against a live backend (REACT_APP_BACKEND_URL), like the other API tests.
import io
import os
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ADMIN = {"email": "admin@eevolvex.com", "password": "Admin@12345"}


def _env(key):
    if os.environ.get(key):
        return os.environ[key]
    for path in ("/app/backend/.env", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")):
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')


DB = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
CRON = {"Authorization": f"Bearer {_env('WEBHOOK_CRON_SECRET')}"}

RESUME = """ANITA RAO
anita.rao@example.com | +91 99887 76655
Location: Mumbai

Work Experience
Travel Consultant | Horizon Trips | Feb 2019 - Present
- Ticketing on Sabre and Amadeus
Reservations Agent | FlyEasy | Jan 2016 - Jan 2019

Education
B.Com, University of Mumbai

Skills
Sabre, Amadeus, Galileo, Excel
Notice Period: 30 days
"""


def docx(text: str, macro: bool = False) -> bytes:
    from docx import Document
    d = Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    if not macro:
        return buf.getvalue()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as src, zipfile.ZipFile(out, "w") as dst:
        for item in src.infolist():
            dst.writestr(item, src.read(item.filename))
        dst.writestr("word/vbaProject.bin", b"macro")
    return out.getvalue()


def admin_h():
    return {"Authorization": f"Bearer {requests.post(f'{API}/auth/admin/login', json=ADMIN).json()['token']}"}


def register(consent: bool):
    email = f"test_resume_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "full_name": "TEST Resume User", "email": email, "mobile": "9000000000", "password": "secret123",
        "confirm_password": "secret123", "industry": "Travel & Hospitality", "current_designation": "Agent",
        "current_salary": "5 LPA", "preferred_location": "Mumbai", "preferred_work_mode": "Hybrid", "consent": True,
        "talent_db_consent": consent})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["user"]["user_id"]


def upload(h, data: bytes, name="cv.docx"):
    return requests.post(f"{API}/resume/upload", headers=h, files={"file": (name, data)})


def wait_parsed(h, rid, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        cur = next((x for x in requests.get(f"{API}/resume", headers=h).json()["resumes"] if x["resume_id"] == rid), None)
        if cur and cur["status"] in ("parsed", "failed"):
            return cur
        time.sleep(0.5)
    raise AssertionError("resume was not parsed in time")


class TestResumes:
    @classmethod
    def setup_class(cls):
        cls.adm = admin_h()
        cls.prev = requests.get(f"{API}/admin/resumes/settings", headers=cls.adm).json()
        cls.users = []

    @classmethod
    def teardown_class(cls):
        requests.put(f"{API}/admin/resumes/settings", headers=cls.adm, json=cls.prev)
        for uid in cls.users:
            DB.users.delete_one({"user_id": uid})
            DB.candidate_resumes.delete_many({"candidate_id": uid})
            DB.consent_records.delete_many({"user_id": uid})

    def enable(self, on=True, max_mb=2):
        r = requests.put(f"{API}/admin/resumes/settings", headers=self.adm,
                         json={"uploads_enabled": on, "max_mb": max_mb, "outdated_months": 12})
        assert r.status_code == 200, r.text

    def test_full_flow(self):
        h, uid = register(True)
        self.users.append(uid)
        self.enable(False)
        assert upload(h, docx(RESUME)).status_code == 503
        self.enable(True)

        # Validation: fake PDF, macro DOCX, oversize.
        assert upload(h, b"not a pdf at all", "cv.pdf").status_code == 400
        assert upload(h, docx(RESUME, macro=True)).status_code == 400
        assert upload(h, b"%PDF-1.4\n/JavaScript (x)\n", "cv.pdf").status_code == 400
        self.enable(True, max_mb=0.1)
        assert upload(h, b"%PDF-1.4\n" + b"0" * 200_000, "cv.pdf").status_code == 400
        self.enable(True)

        first = docx(RESUME)
        r = upload(h, first)
        assert r.status_code == 200, r.text
        rid = r.json()["resume"]["resume_id"]
        assert "enc_key" not in r.json()["resume"]
        rec = wait_parsed(h, rid)
        assert rec["status"] == "parsed", rec
        ex = rec["extracted"]
        assert ex["current_company"] == "Horizon Trips" and "sabre" in ex["tools"]
        # Stored bytes are encrypted, not the original document.
        raw = DB.candidate_resumes.find_one({"resume_id": rid})
        assert raw["enc_key"] and raw["status"] == "parsed"

        # Same file again: nothing new stored.
        dup = upload(h, first)
        assert dup.json()["duplicate"] is True and DB.candidate_resumes.count_documents({"candidate_id": uid}) == 1

        # Candidate can download their own file.
        f = requests.get(f"{API}/resume/{rid}/file", headers=h)
        assert f.status_code == 200 and f.content[:2] == b"PK" and "no-store" in f.headers["Cache-Control"]

        # Confirm, then a new upload must not overwrite confirmed fields.
        c = requests.post(f"{API}/resume/{rid}/confirm", headers=h, json={"fields": {
            "current_company": "Horizon Trips", "tools": ex["tools"], "skills": ex.get("skills", []),
            "total_experience": ex["total_experience"], "expected_ctc": "9 LPA", "notice_period": "30 days"}})
        assert c.status_code == 200, c.text
        u = DB.users.find_one({"user_id": uid})
        assert u["current_company"] == "Horizon Trips" and u["expected_ctc"] == 900000 and "tools" in u["confirmed_fields"]
        r2 = upload(h, docx(RESUME.replace("Horizon Trips", "Other Travels")))
        rid2 = r2.json()["resume"]["resume_id"]
        assert wait_parsed(h, rid2)["extracted"]["current_company"] == "Other Travels"
        assert DB.users.find_one({"user_id": uid})["current_company"] == "Horizon Trips"
        assert requests.get(f"{API}/resume", headers=h).json()["current"]["resume_id"] == rid2

        # Another candidate and a non-admin can't reach this resume or the talent database.
        h_other, other = register(False)
        self.users.append(other)
        assert requests.get(f"{API}/resume/{rid}/file", headers=h_other).status_code == 404
        assert requests.get(f"{API}/admin/talent", headers=h_other).status_code == 403
        assert requests.get(f"{API}/admin/talent/{uid}/resume/{rid}", headers=h).status_code == 403

        # Talent search: consenting candidate is found by resume keyword; non-consenting one never is.
        s = requests.get(f"{API}/admin/talent", headers=self.adm, params={"keyword": "Sabre", "name": "TEST Resume"}).json()
        ids = {c["user_id"] for c in s["candidates"]}
        assert uid in ids and other not in ids
        s = requests.get(f"{API}/admin/talent", headers=self.adm, params={"company": "Horizon", "notice_period": "30 days",
                                                                           "min_exp": "1", "has_resume": "yes"}).json()
        assert uid in {c["user_id"] for c in s["candidates"]}
        assert requests.get(f"{API}/admin/talent/{other}", headers=self.adm).status_code == 404

        # Admin view is audit-logged.
        since = datetime.now(timezone.utc).isoformat()
        v = requests.get(f"{API}/admin/talent/{uid}/resume/{rid2}", headers=self.adm)
        assert v.status_code == 200 and v.content[:2] == b"PK"
        assert DB.admin_audit_log.find_one({"action": "view_resume", "entity_id": uid, "at": {"$gte": since}})
        ex_csv = requests.get(f"{API}/admin/talent/export", headers=self.adm, params={"name": "TEST Resume"})
        assert ex_csv.status_code == 200 and uid in ex_csv.text

        # Withdrawing consent removes the candidate from the talent database.
        requests.put(f"{API}/auth/profile", headers=h, json={"talent_db_consent": False})
        assert requests.get(f"{API}/admin/talent/{uid}", headers=self.adm).status_code == 404
        assert DB.consent_records.count_documents({"user_id": uid, "type": "talent_database"}) == 2
        requests.put(f"{API}/auth/profile", headers=h, json={"talent_db_consent": True})

        # Delete: key destroyed, file unreachable, previous version becomes current.
        assert requests.delete(f"{API}/resume/{rid2}", headers=h).status_code == 200
        gone = DB.candidate_resumes.find_one({"resume_id": rid2})
        assert gone["status"] == "deleted" and "enc_key" not in gone
        assert requests.get(f"{API}/resume/{rid2}/file", headers=h).status_code == 404
        assert requests.get(f"{API}/admin/talent/{uid}/resume/{rid2}", headers=self.adm).status_code == 404
        assert requests.get(f"{API}/resume", headers=h).json()["current"]["resume_id"] == rid
        assert requests.delete(f"{API}/resume", headers=h).json()["deleted"] == 1
        assert DB.users.find_one({"user_id": uid})["has_resume"] is False

    def test_stuck_resume_claimed_once(self):
        # A resume left "processing" by a crashed replica is retried by the cron exactly once,
        # even when two cron calls arrive together.
        h, uid = register(False)
        self.users.append(uid)
        self.enable(True)
        rid = upload(h, docx(RESUME)).json()["resume"]["resume_id"]
        wait_parsed(h, rid)
        past = datetime.now(timezone.utc) - timedelta(minutes=10)
        DB.candidate_resumes.update_one({"resume_id": rid}, {"$set": {"status": "processing", "attempts": 1, "lock_until": past}})
        with ThreadPoolExecutor(2) as ex:
            list(ex.map(lambda _: requests.post(f"{API}/cron/resume-retry", headers=CRON, json={"run_id": uuid.uuid4().hex}), range(2)))
        rec = wait_parsed(h, rid)
        assert rec["status"] == "parsed" and DB.candidate_resumes.find_one({"resume_id": rid})["attempts"] == 2
        assert requests.post(f"{API}/cron/resume-retry", json={}).status_code == 401
