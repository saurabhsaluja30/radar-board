"""Rule-based resume field extraction (no AI, no network).

Every field is optional: a value is returned only when it is clearly present in the text. Nothing is guessed.
"""
import re
from datetime import date
from typing import Dict, List, Optional, Tuple

from smartmatch import NOTICE_DAYS, norm_skill

# Industry buckets match the app's INDUSTRIES list (frontend/src/lib/constants.js, demand.py).
SKILLS: Dict[str, List[str]] = {
    "technical": ["python", "java", "javascript", "typescript", "react", "angular", "vue", "node.js", "django", "flask",
                  "fastapi", "spring", "c#", ".net", "c++", "php", "go", "kotlin", "swift", "sql", "mysql", "postgresql",
                  "mongodb", "oracle", "aws", "azure", "gcp", "docker", "kubernetes", "linux", "git", "html", "css",
                  "rest api", "microservices", "machine learning", "data analysis", "power bi", "tableau", "etl",
                  "selenium", "devops", "ci/cd", "terraform"],
    "functional": ["recruiting", "talent acquisition", "onboarding", "payroll", "employee relations", "hr operations",
                   "performance management", "compensation", "accounting", "accounts payable", "accounts receivable",
                   "financial analysis", "budgeting", "taxation", "gst", "audit", "reconciliation", "bookkeeping",
                   "customer service", "customer experience", "customer support", "voice process", "non-voice process",
                   "chat support", "escalation management", "sales", "business development", "lead generation",
                   "account management", "negotiation", "project management", "stakeholder management",
                   "ticketing", "reservations", "fare calculation", "visa processing", "tour planning",
                   "travel operations", "hotel booking", "team management", "communication"],
    "tools": ["sabre", "amadeus", "galileo", "worldspan", "excel", "microsoft office", "tally", "sap", "quickbooks",
              "zoho", "salesforce", "hubspot", "jira", "confluence", "workday", "successfactors", "naukri recruiter",
              "linkedin recruiter", "zendesk", "freshdesk", "servicenow", "ms dynamics", "oracle financials",
              "google workspace", "slack"],
}
CERT_PAT = re.compile(r"\b(?:certified|certification|certificate)\b|\b(?:PMP|CPA|CFA|ACCA|SHRM|CIPD|ITIL|CCNA|CISSP|"
                      r"AWS Certified|Azure Fundamentals|Six Sigma|IATA|PRINCE2|Scrum Master|CSM)\b", re.I)
INDUSTRY_HINTS = {
    "Travel & Hospitality": ["sabre", "amadeus", "galileo", "worldspan", "ticketing", "reservations", "fare calculation",
                             "visa processing", "tour planning", "travel operations", "hotel booking", "iata"],
    "IT & Technology": ["python", "java", "javascript", "react", "aws", "azure", "docker", "kubernetes", "sql", "devops"],
    "HR & Recruitment": ["recruiting", "talent acquisition", "onboarding", "payroll", "hr operations", "employee relations"],
    "Finance & Accounting": ["accounting", "accounts payable", "accounts receivable", "taxation", "gst", "audit", "tally",
                             "reconciliation", "financial analysis"],
    "BPO / Customer Experience": ["customer service", "customer experience", "customer support", "voice process",
                                  "non-voice process", "chat support", "escalation management"],
}
DEGREES = [("PhD", r"\bph\.?d\b|\bdoctorate\b"), ("MBA", r"\bmba\b|\bpgdm\b"),
           ("Master's", r"\bm\.?\s?tech\b|\bm\.?\s?sc\b|\bm\.?\s?com\b|\bmca\b|\bm\.?a\.?\b(?=\s)|\bmaster(?:'s)?\b"),
           ("Bachelor's", r"\bb\.?\s?tech\b|\bb\.?\s?e\.?\b(?=\s)|\bb\.?\s?sc\b|\bb\.?\s?com\b|\bbca\b|\bbba\b|"
                          r"\bb\.?a\.?\b(?=\s)|\bbachelor(?:'s)?\b"),
           ("Diploma", r"\bdiploma\b"), ("12th / HSC", r"\b(?:12th|hsc|higher secondary|intermediate)\b")]
INSTITUTION_PAT = re.compile(r"[^\n|,]*\b(?:university|college|institute|school|iit|iim|nit)\b[^\n|,]*", re.I)
SECTION_HEADS = re.compile(r"^\s*(?:work\s+experience|professional\s+experience|experience|employment(?:\s+history)?|"
                           r"education|academic|qualifications?|skills|technical\s+skills|key\s+skills|certifications?|"
                           r"projects|summary|profile|objective|achievements|languages|personal\s+details|"
                           r"declaration|hobbies)\s*:?\s*$", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_D = r"(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*,?\s*\d{4}|\d{1,2}[/.-]\d{4}|\d{4})"
RANGE_PAT = re.compile(rf"({_D})\s*(?:-|–|—|to|till|until)\s*({_D}|present|current|now|till date|date)", re.I)
EMAIL_PAT = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_PAT = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}(?!\d)")
LABEL = r"\s*[:\-–]\s*"
DETAIL_LINE = re.compile(r"^\s*(?:notice\s+period|current\s+ctc|expected\s+ctc|current\s+salary|expected\s+salary|ctc|salary|"
                         r"location|address|phone|mobile|email|date\s+of\s+birth|dob|nationality|gender|marital\s+status|"
                         r"languages?\s+known)\s*[:\-–]", re.I)


def _parse_date(s: str, end: bool) -> Optional[Tuple[int, int]]:
    s = s.strip().lower()
    if s in ("present", "current", "now", "till date", "date"):
        t = date.today()
        return t.year, t.month
    m = re.match(r"([a-z]+)\.?\s*,?\s*(\d{4})", s)
    if m and m.group(1)[:3] in MONTHS:
        return int(m.group(2)), MONTHS[m.group(1)[:3]]
    m = re.match(r"(\d{1,2})[/.-](\d{4})", s)
    if m and 1 <= int(m.group(1)) <= 12:
        return int(m.group(2)), int(m.group(1))
    m = re.match(r"(\d{4})$", s)
    if m:
        return int(m.group(1)), 12 if end else 1
    return None


def _months(a: Tuple[int, int]) -> int:
    return a[0] * 12 + a[1]


def _clean_line(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" \t|,-–—•*·")


def _labelled(text: str, labels: str) -> Optional[str]:
    m = re.search(rf"^\s*(?:{labels}){LABEL}(.+)$", text, re.I | re.M)
    return _clean_line(m.group(1))[:120] if m else None


def _sections(lines: List[str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    cur = "header"
    for ln in lines:
        if SECTION_HEADS.match(ln) and len(ln) < 40:
            key = ln.strip().lower().rstrip(":")
            cur = ("experience" if re.search(r"experience|employment", key) else "education"
                   if re.search(r"education|academic|qualification", key) else "skills" if "skill" in key
                   else "certifications" if "certif" in key else key)
            continue
        out.setdefault(cur, []).append(ln)
    return out


def _find_terms(text: str, terms: List[str]) -> List[str]:
    low = text.lower()
    found = []
    for t in terms:
        if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low):
            found.append(norm_skill(t))
    return list(dict.fromkeys(found))


def _employment(lines: List[str]) -> List[dict]:
    jobs = []
    for i, ln in enumerate(lines):
        m = RANGE_PAT.search(ln)
        if not m:
            continue
        start, end = _parse_date(m.group(1), False), _parse_date(m.group(2), True)
        if not start or not end or _months(end) < _months(start):
            continue
        rest = _clean_line(RANGE_PAT.sub("", ln))
        if not rest and i > 0:
            rest = _clean_line(lines[i - 1])
        parts = [p.strip() for p in re.split(r"\s+\|\s+|\s+at\s+|\s*,\s*|\s+-\s+|\s+–\s+", rest) if p.strip()]
        title = parts[0][:80] if parts else None
        company = parts[1][:80] if len(parts) > 1 else None
        if title and SECTION_HEADS.match(title):
            continue
        jobs.append({"title": title, "company": company, "start": f"{start[0]}-{start[1]:02d}",
                     "end": "Present" if re.match(r"present|current|now|till", m.group(2), re.I) else f"{end[0]}-{end[1]:02d}",
                     "_s": _months(start), "_e": _months(end)})
    return jobs


def _total_years(jobs: List[dict], text: str) -> Optional[float]:
    if jobs:
        spans = sorted((j["_s"], j["_e"]) for j in jobs)
        merged = [list(spans[0])]
        for s, e in spans[1:]:
            if s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        months = sum(e - s for s, e in merged)
        if 0 < months < 600:
            return round(months / 12, 1)
    m = re.search(r"(\d{1,2}(?:\.\d)?)\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:total\s+|professional\s+|work\s+)?experience", text, re.I)
    return float(m.group(1)) if m else None


def _name(lines: List[str], email: Optional[str]) -> Optional[str]:
    for ln in lines[:5]:
        s = _clean_line(ln)
        if re.fullmatch(r"(?:name\s*[:\-]\s*)?([A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){1,3})", s, re.I) \
                and not SECTION_HEADS.match(s) and not re.search(r"resume|curriculum|vitae", s, re.I):
            return re.sub(r"^name\s*[:\-]\s*", "", s, flags=re.I).title() if s.isupper() else re.sub(r"^name\s*[:\-]\s*", "", s, flags=re.I)
    return None


def _notice(text: str) -> Optional[str]:
    raw = _labelled(text, r"notice\s+period")
    if not raw:
        return None
    if re.search(r"immediate|serving", raw, re.I):
        return "Immediate"
    m = re.search(r"(\d+)\s*(day|month)", raw, re.I)
    if not m:
        return None
    days = int(m.group(1)) * (30 if m.group(2).lower() == "month" else 1)
    for label, d in sorted(NOTICE_DAYS.items(), key=lambda kv: kv[1]):
        if days <= d:
            return label
    return "More than 90 days"


def _ctc(text: str, labels: str) -> Optional[str]:
    raw = _labelled(text, labels)
    return raw if raw and re.search(r"\d", raw) else None


def extract(text: str) -> dict:
    """Structured fields found in resume text. Keys with nothing found are omitted."""
    text = (text or "")[:60000]
    lines = [ln for ln in (l.strip() for l in text.splitlines()) if ln]
    sec = _sections(lines)
    out: dict = {}

    email = EMAIL_PAT.search(text)
    if email:
        out["email"] = email.group(0).lower()
    for m in PHONE_PAT.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 10 <= len(digits) <= 13 and not RANGE_PAT.search(m.group(0)):
            out["phone"] = m.group(0).strip()
            break
    name = _name(lines, out.get("email"))
    if name:
        out["full_name"] = name
    loc = _labelled(text, r"(?:current\s+)?location|address|city|based\s+in")
    if loc:
        out["current_location"] = loc

    jobs = _employment(sec.get("experience") or lines)
    if jobs:
        jobs.sort(key=lambda j: -j["_e"])
        out["employment_history"] = [{k: v for k, v in j.items() if not k.startswith("_")} for j in jobs[:15]]
        cur = jobs[0]
        if cur.get("title"):
            out["current_designation"] = cur["title"]
        if cur.get("company"):
            out["current_company"] = cur["company"]
        prev = [j["company"] for j in jobs[1:] if j.get("company")]
        if prev:
            out["previous_companies"] = list(dict.fromkeys(prev))[:10]
    years = _total_years(jobs, text)
    if years is not None:
        out["total_experience"] = years

    skills = _find_terms(text, SKILLS["technical"] + SKILLS["functional"])
    tools = _find_terms(text, SKILLS["tools"])
    # Free-text items listed under a Skills heading (comma or bullet separated) are kept too.
    listed = []
    for ln in sec.get("skills", [])[:20]:
        if DETAIL_LINE.match(ln):  # e.g. "Notice Period: 60 days" placed under the Skills heading
            continue
        for item in re.split(r"[,;•|/]", re.sub(r"^[^:]{1,30}:", "", ln)):
            item = _clean_line(item)
            if 1 < len(item) <= 40 and not re.search(r"\d{4}|\d\s*(?:days?|months?|years?|yrs?|lpa|lakhs?|k)\b", item, re.I):
                listed.append(norm_skill(item))
    skills = list(dict.fromkeys(skills + [s for s in listed if s not in tools]))[:40]
    if skills:
        out["skills"] = skills
    if tools:
        out["tools"] = tools
    certs = [_clean_line(ln)[:100] for ln in sec.get("certifications", [])[:10]]
    certs += [_clean_line(ln)[:100] for ln in lines if CERT_PAT.search(ln) and len(ln) < 120]
    certs = [c for c in dict.fromkeys(certs) if c and not SECTION_HEADS.match(c)][:10]
    if certs:
        out["certifications"] = certs
    terms = set(skills) | set(tools) | {c.lower() for c in certs}
    # Two distinct signals per industry (synonyms collapse to one term, so they count once).
    inds = [ind for ind, hints in INDUSTRY_HINTS.items() if len({norm_skill(h) for h in hints} & terms) >= 2]
    if inds:
        out["industry_experience"] = inds

    edu_text = "\n".join(sec.get("education") or lines)
    for label, pat in DEGREES:
        if re.search(pat, edu_text, re.I):
            out["highest_qualification"] = label
            break
    inst = INSTITUTION_PAT.search(edu_text)
    if inst:
        out["institution"] = _clean_line(inst.group(0))[:120]

    cur_ctc = _ctc(text, r"current\s+ctc|current\s+salary|present\s+ctc")
    if cur_ctc:
        out["current_ctc"] = cur_ctc
    exp_ctc = _ctc(text, r"expected\s+ctc|expected\s+salary")
    if exp_ctc:
        out["expected_ctc"] = exp_ctc
    notice = _notice(text)
    if notice:
        out["notice_period"] = notice
    return out


def keywords(fields: dict) -> List[str]:
    """Lower-case search tokens for the talent database index."""
    vals = list(fields.get("skills") or []) + list(fields.get("tools") or []) + list(fields.get("certifications") or [])
    vals += [fields.get(k) for k in ("current_designation", "current_company", "highest_qualification")]
    vals += list(fields.get("previous_companies") or []) + list(fields.get("industry_experience") or [])
    vals += [j.get("title") for j in fields.get("employment_history") or []]
    return sorted({v.strip().lower()[:80] for v in vals if isinstance(v, str) and v.strip()})[:200]
