# CV paste: extraction of the new fields (no server needed) and the paste → confirm → admin flow, run in-process
# against an in-memory MongoDB (mongomock-motor), so it needs no live backend, object storage or RESUME_KEK.
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402
from resume_parse import extract  # noqa: E402
from resumes import CSV_CELL_MAX, _coerce, csv_cell  # noqa: E402

CV = """RAHUL VERMA
rahul.verma@example.com | +91 98111 22334
linkedin.com/in/rahul-verma-123 | https://github.com/rahulv
Portfolio: rahulverma.dev
Location: Pune, India
Desired Role: Senior Travel Consultant, Travel Operations Manager
Preferred Location: Bangalore, Hyderabad
Languages Known: English (Fluent), Hindi, Marathi

Work Experience
Travel Consultant | Globe Travels | Jan 2020 - Present
- Ticketing and reservations on Sabre and Amadeus
Travel Executive | SkyWay Holidays | Mar 2017 - Dec 2019

Education
MBA, Symbiosis Institute of Business Management, 2016
B.Com
University of Pune, 2014

Skills
Sabre, Amadeus, Excel
Notice Period: 30 days
"""

# Same kind of CV with none of the new details: nothing may be invented.
PLAIN = """PRIYA SHARMA
priya.sharma@example.com
Objective: To obtain a challenging position in a reputed organisation where I can grow.

Work Experience
Accounts Executive, ABC Traders, Jan 2019 - Present
- Accounts payable and GST filing in Tally

Skills
Tally, Excel, GST, Reconciliation
"""


# ---------------------------------------------------------------- extraction
def test_languages_are_read_without_proficiency_words():
    assert extract(CV)["languages"] == ["English", "Hindi", "Marathi"]


def test_languages_section_heading():
    f = extract(PLAIN + "\nLanguages\nEnglish - Fluent\nTamil (Native)\n")
    assert f["languages"] == ["English", "Tamil"]


def test_programming_languages_are_not_spoken_languages():
    f = extract(PLAIN + "\nProgramming Languages: Python, Java\n")
    assert "languages" not in f


def test_links_linkedin_github_portfolio():
    assert extract(CV)["links"] == ["https://linkedin.com/in/rahul-verma-123", "https://github.com/rahulv",
                                    "https://rahulverma.dev"]


def test_email_domain_is_not_a_link():
    assert "links" not in extract(PLAIN)


def test_education_entries_including_two_line_layout():
    assert extract(CV)["education"] == [
        {"degree": "MBA", "institution": "Symbiosis Institute of Business Management", "year": "2016"},
        {"degree": "B.Com", "institution": "University of Pune", "year": "2014"},
    ]


def test_preferred_titles_from_labelled_line():
    assert extract(CV)["preferred_titles"] == ["Senior Travel Consultant", "Travel Operations Manager"]


@pytest.mark.parametrize("line", ["Looking for: Travel Manager roles", "Preferred Role: Travel Manager",
                                  "Objective: Travel Manager"])
def test_preferred_titles_other_labels(line):
    assert extract(PLAIN.replace("Objective: To obtain a challenging position in a reputed organisation where I can grow.",
                                 line))["preferred_titles"] == ["Travel Manager"]


def test_prose_objective_is_not_a_title_falls_back_to_current_designation():
    f = extract(PLAIN)
    assert f["current_designation"] == "Accounts Executive"
    assert f["preferred_titles"] == ["Accounts Executive"]


def test_preferred_locations_from_labelled_line():
    assert extract(CV)["preferred_locations"] == ["Bangalore", "Hyderabad"]


def test_willing_to_relocate_line():
    f = extract(PLAIN + "\nWilling to relocate: Yes - Chennai, Mumbai\n")
    assert f["preferred_locations"] == ["Chennai", "Mumbai"]
    assert "preferred_locations" not in extract(PLAIN + "\nWilling to relocate: No\n")


def test_preferred_locations_fall_back_to_current_location():
    f = extract(PLAIN + "\nLocation: Delhi\n")
    assert f["preferred_locations"] == ["Delhi"]


def test_nothing_invented_when_absent():
    f = extract(PLAIN)
    for k in ("languages", "links", "education", "preferred_locations", "current_location"):
        assert k not in f, k
    # A prose objective line isn't read as a skill either.
    assert not any("obtain" in s for s in f.get("skills", []))


def test_new_detail_lines_under_skills_are_not_skills():
    f = extract(CV)
    assert not {"bangalore", "hyderabad", "english", "senior travel consultant"} & set(f.get("skills", []))


# ---------------------------------------------------------------- coercion + export cells
def test_coerce_links_and_education():
    assert _coerce("links", "links", "linkedin.com/in/x, https://a.dev") == ["https://linkedin.com/in/x", "https://a.dev"]
    with pytest.raises(HTTPException):
        _coerce("links", "links", ["javascript:alert(1)"])
    rows = _coerce("education", "education", [{"degree": "MBA", "institution": "IIM A", "year": 2016}, {"degree": ""}])
    assert rows == [{"degree": "MBA", "institution": "IIM A", "year": "2016"}]
    with pytest.raises(HTTPException):
        _coerce("education", "education", [{"degree": "MBA", "year": "last year"}])


def test_csv_cell_blocks_formulas_but_keeps_phone_numbers():
    assert csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert csv_cell("@SUM(A1)") == "'@SUM(A1)"
    assert csv_cell("+91 98111 22334") == "+91 98111 22334"
    assert csv_cell([{"degree": "MBA", "institution": "X", "year": "2016"}]) == "MBA, X, 2016"


# ---------------------------------------------------------------- in-process API flow
mongomock_motor = pytest.importorskip("mongomock_motor")


@pytest.fixture()
def app_ctx(monkeypatch):
    from fastapi import Depends, FastAPI, Header
    from fastapi.testclient import TestClient

    import resumes
    import storage

    # Object storage and the master key must not be needed for pasted text.
    monkeypatch.setattr(storage, "kek", lambda: None)
    monkeypatch.setattr(storage, "_put_object", lambda *a, **k: (_ for _ in ()).throw(AssertionError("storage used")))

    db = mongomock_motor.AsyncMongoMockClient()["test_resume_paste"]
    audits = []

    async def get_current_user(x_user: str = Header(...)):
        u = await db.users.find_one({"user_id": x_user}, {"_id": 0})
        if not u:
            raise HTTPException(401, "no user")
        return u

    async def require_admin(user=Depends(get_current_user)):
        if user.get("role") != "admin":
            raise HTTPException(403, "admin only")
        return user

    async def audit_log(admin, action, entity, entity_id, details=None):
        audits.append(action)

    def bg(coro):
        coro.close()

    from datetime import datetime, timezone
    router, _ = resumes.build_router(db, get_current_user, require_admin, audit_log,
                                     lambda: datetime.now(timezone.utc).isoformat(), bg)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        client.portal.call(db.users.insert_many, [
            {"user_id": "c1", "role": "candidate", "email": "c1@example.com", "full_name": "Rahul Verma",
             "talent_db_consent": True, "created_at": "2026-01-01"},
            {"user_id": "a_full", "role": "admin", "permissions": ["view_resumes", "export_candidates"]},
            {"user_id": "a_none", "role": "admin", "permissions": []},
        ])
        yield client, db, audits


def H(uid):
    return {"X-User": uid}


def test_paste_confirm_admin_and_export(app_ctx):
    client, db, audits = app_ctx
    assert client.post("/resume/paste", json={"text": "too short"}, headers=H("c1")).status_code == 400
    assert client.post("/resume/paste", json={"text": "x" * 50001}, headers=H("c1")).status_code == 400
    assert client.post("/resume/paste", json={"text": CV}, headers=H("a_full")).status_code == 403

    r = client.post("/resume/paste", json={"text": CV}, headers=H("c1"))
    assert r.status_code == 200, r.text
    rec = r.json()["resume"]
    assert r.json()["duplicate"] is False
    assert rec["status"] == "parsed" and rec["source"] == "paste" and rec["is_current"] is True
    assert "raw_text" not in rec
    assert rec["extracted"]["preferred_titles"] == ["Senior Travel Consultant", "Travel Operations Manager"]

    # Same shape as GET /resume, which the confirm screen reads.
    mine = client.get("/resume", headers=H("c1")).json()
    assert mine["current"]["resume_id"] == rec["resume_id"] and "raw_text" not in mine["current"]
    stored = client.portal.call(db.candidate_resumes.find_one, {"resume_id": rec["resume_id"]})
    assert stored["raw_text"] == CV.strip() and len(stored["sha256"]) == 64

    ex = rec["extracted"]
    r = client.post(f"/resume/{rec['resume_id']}/confirm", headers=H("c1"), json={"fields": {
        "preferred_titles": ex["preferred_titles"], "preferred_locations": ["Bangalore", "Hyderabad"],
        "languages": ex["languages"], "links": ex["links"], "education": ex["education"]}})
    assert r.status_code == 200, r.text
    u = client.portal.call(db.users.find_one, {"user_id": "c1"})
    assert u["preferred_titles"] == ["Senior Travel Consultant", "Travel Operations Manager"]
    assert u["preferred_locations"] == ["Bangalore", "Hyderabad"]
    assert u["languages"] == ["English", "Hindi", "Marathi"]
    assert u["education"][1] == {"degree": "B.Com", "institution": "University of Pune", "year": "2014"}

    # Re-pasting the same text makes that record current again instead of adding a new version.
    client.post("/resume/paste", json={"text": PLAIN * 2}, headers=H("c1"))
    r = client.post("/resume/paste", json={"text": CV}, headers=H("c1"))
    assert r.json()["duplicate"] is True and r.json()["resume"]["resume_id"] == rec["resume_id"]
    assert client.get("/resume", headers=H("c1")).json()["current"]["resume_id"] == rec["resume_id"]

    # Admin detail: CV text only with view_resumes.
    d = client.get("/admin/talent/c1", headers=H("a_full")).json()
    assert d["raw_text"] == CV.strip() and d["candidate"]["preferred_titles"]
    assert all("raw_text" not in x for x in d["resumes"])
    assert "view_cv_text" in audits
    d = client.get("/admin/talent/c1", headers=H("a_none")).json()
    assert d["raw_text"] is None and d["can_view_cv_text"] is False

    # Export: needs export_candidates; has the new columns and the CV text.
    assert client.get("/admin/talent/export", headers=H("a_none")).status_code == 403
    r = client.get("/admin/talent/export", headers=H("a_full"))
    assert r.status_code == 200
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert {"cv_text", "preferred_titles", "languages", "links", "education"} <= set(rows[0])
    assert rows[0]["cv_text"].startswith("RAHUL VERMA") and "Senior Travel Consultant" in rows[0]["preferred_titles"]

    # Deleting removes the text.
    assert client.delete(f"/resume/{rec['resume_id']}", headers=H("c1")).status_code == 200
    stored = client.portal.call(db.candidate_resumes.find_one, {"resume_id": rec["resume_id"]})
    assert stored["status"] == "deleted" and "raw_text" not in stored


def test_export_truncates_cv_text_to_excel_cell_limit(app_ctx):
    client, db, _ = app_ctx
    big = CV + ("Handled corporate travel desk. " * 2000)[: 49000 - len(CV)]
    assert client.post("/resume/paste", json={"text": big}, headers=H("c1")).status_code == 200
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(client.get("/admin/talent/export", headers=H("a_full")).text)))
    assert len(rows[0]["cv_text"]) == CSV_CELL_MAX


# ---------------------------------------------------------------- Excel export
def test_build_xlsx_keeps_text_as_text():
    import io as _io
    from openpyxl import load_workbook
    from xlsx_export import build_xlsx
    data = build_xlsx([("a", "A"), ("b", "B"), ("c", "C"), ("d", "D")],
                      [{"a": "=HYPERLINK(\"http://x\")", "b": ["x", "y"], "c": 7, "d": "bad\x07char"},
                       {"a": None, "b": [{"degree": "MBA", "institution": "IIM", "year": "2016"}], "c": True, "d": "z" * 40000}],
                      "Test")
    ws = load_workbook(_io.BytesIO(data)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("A", "B", "C", "D")
    assert rows[1] == ('=HYPERLINK("http://x")', "x; y", 7, "badchar")
    assert ws["A2"].data_type == "s", "a value starting with = is stored as text, not a formula"
    assert rows[2][1] == "MBA, IIM, 2016" and rows[2][2] == "Yes" and len(rows[2][3]) == 32000


def test_candidates_excel_export(app_ctx):
    import io as _io
    from openpyxl import load_workbook
    client, db, audits = app_ctx
    assert client.post("/resume/paste", json={"text": CV}, headers=H("c1")).status_code == 200
    assert client.get("/admin/export/candidates", headers=H("a_none")).status_code == 403
    assert client.get("/admin/export/candidates", headers=H("c1")).status_code == 403
    r = client.get("/admin/export/candidates", headers=H("a_full"))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert r.headers["content-disposition"].startswith('attachment; filename="candidates_')
    ws = load_workbook(_io.BytesIO(r.content)).active
    rows = list(ws.iter_rows(values_only=True))
    head = rows[0]
    assert head[:3] == ("Name", "Email", "Mobile") and head[-1] == "CV text" and "Membership" in head
    rahul = dict(zip(head, next(x for x in rows[1:] if x[0] == "Rahul Verma")))
    assert rahul["Email"] == "c1@example.com" and rahul["Account"] == "Active" and rahul["Membership"] == "no membership"
    assert "Travel" in rahul["CV text"]
    assert "export_candidates" in audits
    assert client.get("/admin/export/candidates", params={"q": "nobody-matches"}, headers=H("a_full")).status_code == 200

    t = client.get("/admin/talent/export", params={"format": "xlsx"}, headers=H("a_full"))
    assert t.status_code == 200 and t.headers["content-disposition"].endswith('talent_database.xlsx"')
    assert load_workbook(_io.BytesIO(t.content)).active["A1"].value
