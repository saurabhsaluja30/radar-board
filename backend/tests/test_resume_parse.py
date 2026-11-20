# Unit tests for the rule-based resume parser (no server needed).
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from career import file_to_text  # noqa: E402
from resume_parse import extract, keywords  # noqa: E402
from smartmatch import norm_skill  # noqa: E402

RESUME = """PRIYA SHARMA
priya.sharma@example.com | +91 98765 43210
Location: Pune, India

Professional Summary
Travel operations specialist with 6 years of experience.

Work Experience
Senior Travel Consultant | Globe Travels Pvt Ltd | Jan 2021 - Present
- Handled ticketing and reservations on Sabre and Amadeus
Travel Executive | SkyWay Holidays | Mar 2018 - Dec 2020
- Fare calculation and visa processing using Galileo

Education
B.Com, University of Pune, 2017

Skills
Sabre, Amadeus, Galileo, Ticketing, MS Excel, Customer Service

Certifications
IATA Foundation Certificate

Current CTC: 6.5 LPA
Expected CTC: 8 LPA
Notice Period: 30 days
"""


def _pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for line in text.splitlines():
        c.drawString(40, y, line)
        y -= 14
    c.save()
    return buf.getvalue()


def _docx(text: str) -> bytes:
    from docx import Document
    d = Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _check(f: dict):
    assert f["full_name"] == "Priya Sharma"
    assert f["email"] == "priya.sharma@example.com"
    assert f["phone"].replace(" ", "") == "+919876543210"
    assert f["current_location"] == "Pune, India"
    assert f["current_designation"] == "Senior Travel Consultant"
    assert f["current_company"] == "Globe Travels Pvt Ltd"
    assert f["previous_companies"] == ["SkyWay Holidays"]
    assert f["total_experience"] >= 5.5
    norm = lambda xs: {norm_skill(x) for x in xs}  # noqa: E731 - skills use the app's synonym mapping
    assert norm(["sabre", "amadeus", "galileo", "ms excel"]) <= set(f["tools"])
    assert norm(["ticketing", "reservations", "customer service"]) <= set(f["skills"])
    assert "Travel & Hospitality" in f["industry_experience"]
    assert f["highest_qualification"] == "Bachelor's"
    assert "University of Pune" in f["institution"]
    assert any("IATA" in c for c in f["certifications"])
    assert f["current_ctc"] == "6.5 LPA" and f["expected_ctc"] == "8 LPA"
    assert f["notice_period"] == "30 days"
    assert "sabre" in keywords(f)


def test_text():
    _check(extract(RESUME))


def test_pdf_and_docx_files():
    _check(extract(file_to_text("cv.pdf", _pdf(RESUME))))
    _check(extract(file_to_text("cv.docx", _docx(RESUME))))


def test_missing_fields_are_not_invented():
    f = extract("John Doe\nI like building things.\nSkills\nPython")
    assert f.get("full_name") == "John Doe"
    for k in ("email", "phone", "current_company", "current_designation", "total_experience", "current_ctc",
              "expected_ctc", "notice_period", "highest_qualification", "institution", "current_location"):
        assert k not in f, k
    assert f["skills"] == ["python"]


def test_detail_lines_under_skills_are_not_skills():
    f = extract("Asha Nair\nSkills\nPayroll, Excel\nNotice Period: 60 days\nExpected CTC: 9 LPA\n")
    assert f["notice_period"] == "60 days" and f["expected_ctc"] == "9 LPA"
    assert not any(any(ch.isdigit() for ch in x) for x in f.get("skills", []) + f.get("tools", []))
