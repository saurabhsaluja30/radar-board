# Phase 2: Resume Studio — old .doc files, five ATS templates, and tailoring that the candidate reviews before saving.
import os
import sys
import time
import uuid

import pytest
import requests
from fastapi import HTTPException
from pymongo import MongoClient

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from career import TEMPLATES, file_to_text, pair_sections  # noqa: E402
from doctext import doc_to_text  # noqa: E402
from resumes import validate_file  # noqa: E402

DOC = open(os.path.join(HERE, "fixtures", "sample_resume.doc"), "rb").read()
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
API = f"{BASE_URL}/api"


def _env(key):
    if os.environ.get(key):
        return os.environ[key]
    for path in ("/app/backend/.env", os.path.join(os.path.dirname(HERE), ".env")):
        if os.path.exists(path):
            for line in open(path):
                if line.startswith(key + "="):
                    return line.split("=", 1)[1].strip().strip('"')


# --------------------------------------------------------------------------- unit
def test_doc_text_is_read():
    text = doc_to_text(DOC)
    assert text.startswith("Asha Verma")
    assert "Senior Recruiter | Example Staffing Pvt Ltd | Jan 2021 – Present" in text
    assert "MBA (HR)" in text and "\x07" not in text and "\r" not in text


def test_doc_accepted_and_bad_ole_rejected():
    assert validate_file("cv.doc", DOC) == "doc"
    assert "Asha Verma" in file_to_text("x.doc", DOC)
    with pytest.raises(HTTPException):
        validate_file("cv.doc", DOC[:600])  # truncated: OLE header but unreadable
    with pytest.raises(HTTPException):
        file_to_text("x.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 2000)


def test_five_templates():
    assert set(TEMPLATES) == {"classic", "modern", "compact", "executive", "minimal"}


def test_pairing_shows_before_and_after():
    rows = pair_sections(
        [{"id": "s1", "title": "Professional Summary", "content": "Recruiter."},
         {"id": "s2", "title": "SKILLS", "content": "Sourcing"}],
        [{"title": "PROFESSIONAL SUMMARY", "content": "Recruiter for IT roles."},
         {"title": "Skills", "content": "Sourcing"},
         {"title": "Achievements", "content": "- Something"}])
    assert [(r["key"], r["status"]) for r in rows] == [("s1", "changed"), ("s2", "unchanged"), ("new_achievements", "new")]
    assert rows[0]["before"] == "Recruiter." and rows[0]["after"] == "Recruiter for IT roles."


# --------------------------------------------------------------------------- live
@pytest.mark.skipif(not BASE_URL, reason="needs REACT_APP_BACKEND_URL")
class TestResumeStudio:
    @classmethod
    def setup_class(cls):
        cls.db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
        email = f"test_studio_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Studio User", "email": email, "mobile": "9000000000", "password": "secret123",
            "confirm_password": "secret123", "industry": "HR & Recruitment", "current_designation": "Recruiter",
            "current_salary": "6 LPA", "preferred_location": "Pune", "preferred_work_mode": "Hybrid", "consent": True})
        assert r.status_code == 200, r.text
        cls.uid = r.json()["user"]["user_id"]
        cls.h = {"Authorization": f"Bearer {r.json()['token']}"}

    @classmethod
    def teardown_class(cls):
        for coll in ("resumes", "tailor_drafts", "download_tokens"):
            cls.db[coll].delete_many({"user_id": cls.uid})
        cls.db.candidate_resumes.delete_many({"candidate_id": cls.uid})
        cls.db.consent_records.delete_many({"user_id": cls.uid})
        cls.db.subscriptions.delete_many({"candidate_id": cls.uid})
        cls.db.users.delete_one({"user_id": cls.uid})

    def resume(self, template="classic"):
        r = requests.post(f"{API}/career/resumes", headers=self.h, json={
            "title": "TEST Studio", "resume_type": "experienced", "template": template,
            "personal": {"full_name": "Asha Verma", "email": "asha.verma@example.com", "phone": "9000000001"},
            "sections": [{"title": "PROFESSIONAL SUMMARY", "content": "Recruiter with 6 years of experience."},
                         {"title": "SKILLS", "content": "Sourcing, Screening"},
                         {"title": "EDUCATION", "content": "MBA (HR), 2018"}]})
        assert r.status_code == 200, r.text
        return r.json()["resume"]

    def test_profile_upload_accepts_doc(self):
        prev = requests.get(f"{API}/resume/config", headers=self.h).json()
        if not prev.get("uploads_enabled", True):
            pytest.skip("resume uploads are switched off in this database")
        r = requests.post(f"{API}/resume/upload", headers=self.h, files={"file": ("old_cv.doc", DOC)})
        assert r.status_code == 200, r.text
        rid = (r.json().get("resume") or r.json())["resume_id"]
        end = time.time() + 20
        while time.time() < end:
            cur = next((x for x in requests.get(f"{API}/resume", headers=self.h).json()["resumes"] if x["resume_id"] == rid), None)
            if cur and cur["status"] in ("parsed", "failed"):
                break
            time.sleep(0.5)
        assert cur["status"] == "parsed", cur
        f = requests.get(f"{API}/resume/{rid}/file", headers=self.h)
        assert f.status_code == 200 and f.content == DOC and f.headers["content-type"].startswith("application/msword")

    @pytest.mark.parametrize("template", ["executive", "minimal"])
    def test_new_templates_export(self, template):
        res = self.resume(template)
        assert res["template"] == template
        for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK")):
            link = requests.post(f"{API}/career/resumes/{res['resume_id']}/download-link", headers=self.h, json={"format": fmt})
            assert link.status_code == 200
            out = requests.get(f"{BASE_URL}{link.json()['path']}")
            assert out.status_code == 200 and out.content[:len(magic)] == magic

    def draft(self, res):
        sections = pair_sections(res["sections"], [
            {"title": "PROFESSIONAL SUMMARY", "content": "Recruiter with 6 years of experience hiring for IT roles."},
            {"title": "SKILLS", "content": "Sourcing, Screening, Boolean search"},
            {"title": "ACHIEVEMENTS", "content": "- Invented award"}])
        d = {"draft_id": f"tdr_test_{uuid.uuid4().hex[:8]}", "user_id": self.uid, "resume_id": res["resume_id"],
             "resume_title": res["title"], "jd_title": "IT Recruiter at Example Co", "changes": ["Emphasised IT hiring"],
             "matched_keywords": ["Sourcing"], "missing_keywords": ["Boolean search"], "sections": sections,
             "status": "pending", "created_at": "2026-11-22T00:00:00+00:00"}
        self.db.tailor_drafts.insert_one(dict(d))
        return d, {r["title"]: r["key"] for r in sections}

    def test_tailoring_saves_only_what_the_candidate_keeps(self):
        res = self.resume()
        d, keys = self.draft(res)
        before = self.db.resumes.count_documents({"user_id": self.uid})
        got = requests.get(f"{API}/career/tailor-drafts/{d['draft_id']}", headers=self.h).json()["draft"]
        assert [s["status"] for s in got["sections"]] == ["changed", "changed", "unchanged", "new"]
        assert self.db.resumes.count_documents({"user_id": self.uid}) == before, "a proposal is not a resume"
        # keep the summary (edited), reject the skills change and the invented new section
        r = requests.post(f"{API}/career/tailor-drafts/{d['draft_id']}/apply", headers=self.h, json={
            "accepted": [keys["PROFESSIONAL SUMMARY"]],
            "edits": {keys["PROFESSIONAL SUMMARY"]: "Recruiter with 6 years of experience, mostly IT roles."}})
        assert r.status_code == 200, r.text
        new = {s["title"]: s["content"] for s in r.json()["resume"]["sections"]}
        assert new == {"PROFESSIONAL SUMMARY": "Recruiter with 6 years of experience, mostly IT roles.",
                       "SKILLS": "Sourcing, Screening", "EDUCATION": "MBA (HR), 2018"}
        orig = requests.get(f"{API}/career/resumes/{res['resume_id']}", headers=self.h).json()["resume"]
        assert orig["sections"][0]["content"] == "Recruiter with 6 years of experience.", "original is untouched"
        again = requests.post(f"{API}/career/tailor-drafts/{d['draft_id']}/apply", headers=self.h,
                              json={"accepted": [keys["SKILLS"]]})
        assert again.status_code == 400, "a proposal is saved once"

    def test_tailoring_needs_at_least_one_kept_change_and_is_private(self):
        res = self.resume()
        d, _ = self.draft(res)
        assert requests.post(f"{API}/career/tailor-drafts/{d['draft_id']}/apply", headers=self.h,
                             json={"accepted": []}).status_code == 400
        assert requests.get(f"{API}/career/tailor-drafts/{d['draft_id']}").status_code in (401, 403)
        assert self.db.tailor_drafts.find_one({"draft_id": d["draft_id"]})["status"] == "pending"
