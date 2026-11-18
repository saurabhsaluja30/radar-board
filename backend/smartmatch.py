import asyncio
import csv
import io
import re
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

WEIGHTS = {"skills": 30, "designation": 20, "experience": 15, "industry": 10, "location": 10, "salary": 10, "work_mode": 5}
JOB_SOURCES = ["EevolveX recruitment assignment", "Direct employer submission", "Recruiter submission",
               "Approved external job feed / API", "Other authorised source"]
VERIFICATION = ["Pending Verification", "Verified", "Rejected"]
NOTICE_DAYS = {"Immediate": 0, "15 days": 15, "30 days": 30, "45 days": 45, "60 days": 60, "90 days": 90, "More than 90 days": 120}
MATCH_STATUSES = {
    "suggested": "Suggested by System", "pending_review": "Pending Admin Review", "approved": "Approved", "rejected": "Rejected",
    "shared": "Shared with Candidate", "interested": "Candidate Interested", "not_interested": "Candidate Not Interested",
    "applied": "Candidate Applied Independently", "interview_reported": "Interview Reported", "closed": "Closed",
}
DEFAULT_TEMPLATE = {
    "subject": "New job opportunity that may match your profile: [Designation]",
    "body": ("Hi [Candidate Name],\n\nWe found a new job opportunity that may match your profile.\n\n"
             "Job Title: [Designation]\nCompany: [Company Name]\nLocation: [Location]\nExperience: [Experience]\n"
             "Salary: [Salary]\nMatch Score: [Score]%\n\nWhy this opportunity may suit you:\n[Match Explanation]\n\n"
             "Log in to JobRadar to review the complete opportunity and contact the recruiter/company directly.\n\n"
             "JobRadar by EvolveMinds\nDon't Just Apply. Apply Smart."),
}

SKILL_SYNONYMS = {
    "js": "javascript", "reactjs": "react", "react.js": "react", "node": "node.js", "nodejs": "node.js", "py": "python",
    "ms excel": "excel", "microsoft excel": "excel", "advanced excel": "excel", "ms office": "microsoft office",
    "ta": "talent acquisition", "recruitment": "recruiting", "hiring": "recruiting", "end to end recruitment": "recruiting",
    "hrms": "hris", "payroll processing": "payroll", "customer service": "customer support", "client support": "customer support",
    "tally erp": "tally", "tally prime": "tally", "tally erp 9": "tally", "ml": "machine learning", "ai": "artificial intelligence",
    "postgres": "postgresql", "k8s": "kubernetes", "amazon web services": "aws", "gcp": "google cloud", "sfdc": "salesforce",
    "ap": "accounts payable", "ar": "accounts receivable", "communication skills": "communication",
    "english communication": "communication", "verbal communication": "communication", "ticketing": "air ticketing",
    "gds amadeus": "amadeus", "amadeus gds": "amadeus", "sabre gds": "sabre", "galileo gds": "galileo",
}
TITLE_STOP = {"senior", "sr", "junior", "jr", "lead", "head", "chief", "assistant", "asst", "deputy", "trainee", "intern",
              "executive", "exec", "manager", "mgr", "officer", "specialist", "associate", "i", "ii", "iii", "of", "and",
              "the", "&", "-", "/", "team", "staff", "principal", "level", "l1", "l2", "l3"}
TITLE_SYNONYMS = {"hr": "human resources", "ta": "talent acquisition", "recruiter": "recruitment", "recruiting": "recruitment",
                  "dev": "developer", "swe": "software engineer", "accounts": "accountant", "bde": "business development",
                  "bdm": "business development", "csr": "customer service", "cse": "customer service", "tele": "telecaller"}
FAMILIES = {
    "hr": {"human", "resources", "talent", "acquisition", "recruitment", "hrbp", "people", "payroll", "generalist", "sourcing"},
    "finance": {"accountant", "accounting", "finance", "financial", "audit", "auditor", "tax", "taxation", "controller", "fp&a", "treasury", "billing"},
    "it": {"developer", "engineer", "software", "programmer", "devops", "qa", "tester", "data", "architect", "stack", "frontend", "backend", "cloud"},
    "travel": {"travel", "tour", "tours", "ticketing", "reservation", "reservations", "hotel", "hospitality", "front", "guest", "visa", "holiday", "gds"},
    "cx": {"customer", "support", "service", "bpo", "call", "voice", "chat", "telecaller", "process", "helpdesk", "experience"},
    "sales": {"sales", "business", "development", "account", "key", "inside"},
}
PROFILE_FIELDS = [
    ("full_name", "Full name"), ("mobile", "Mobile number"), ("industry", "Current industry"),
    ("current_designation", "Current designation"), ("total_experience", "Total work experience"),
    ("current_company", "Current company"), ("current_salary", "Current CTC"), ("expected_ctc", "Expected CTC"),
    ("primary_skills", "Primary skills"), ("preferred_titles", "Preferred job titles"),
    ("preferred_industries", "Preferred industries"), ("preferred_locations", "Preferred locations"),
    ("preferred_country", "Preferred country"), ("preferred_work_mode", "Preferred work mode"),
    ("notice_period", "Notice period"), ("employment_type_pref", "Employment type preference"),
]


MIN_RELEVANCE = 50
ALERT_PREF_LABEL = {"enabled": "Job alerts on", "none": "No preference selected", "opted_out": "Opted out"}


def alert_pref(c: dict) -> str:
    v = c.get("job_alert_consent")
    return "enabled" if v is True else "opted_out" if v is False else "none"


def split_list(v) -> List[str]:
    if isinstance(v, list):
        items = v
    else:
        items = re.split(r"[,;|\n•]+", v or "")
    return [i.strip() for i in items if i and str(i).strip()]


def norm_skill(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower()).strip(" .")
    return SKILL_SYNONYMS.get(s, s)


def skill_hit(skill: str, have: set) -> bool:
    if skill in have:
        return True
    for h in have:
        short, long_ = (skill, h) if len(skill) <= len(h) else (h, skill)
        if len(short) >= 3 and re.search(rf"(^|\W){re.escape(short)}($|\W)", long_):
            return True
    return False


def title_tokens(t: str) -> set:
    t = re.sub(r"[^a-z0-9&+ ]", " ", (t or "").lower())
    out = set()
    for w in t.split():
        w = TITLE_SYNONYMS.get(w, w)
        out.update(x for x in w.split() if x not in TITLE_STOP)
    return out


def families(tokens: set) -> set:
    return {f for f, words in FAMILIES.items() if tokens & words}


def to_num(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def candidate_lists(c: dict):
    titles = split_list(c.get("preferred_titles")) + split_list(c.get("preferred_designation") or "")
    locs = split_list(c.get("preferred_locations")) + split_list(c.get("preferred_location") or "")
    return titles, locs


def profile_status(c: dict) -> dict:
    titles, locs = candidate_lists(c)
    present = {"preferred_titles": titles, "preferred_locations": locs}
    missing = []
    for k, label in PROFILE_FIELDS:
        v = present.get(k, c.get(k))
        if v in (None, "", []) or (isinstance(v, list) and not [x for x in v if x]):
            missing.append(label)
    pct = round((len(PROFILE_FIELDS) - len(missing)) * 100 / len(PROFILE_FIELDS))
    return {"completion": pct, "missing": missing}


def score_match(c: dict, j: dict, related_industries: list) -> dict:
    comps, reasons, missing_data, flags = {}, [], [], []
    have = {norm_skill(s) for s in split_list(c.get("primary_skills")) + split_list(c.get("secondary_skills"))}
    mand = [norm_skill(s) for s in split_list(j.get("required_skills"))]
    pref = [norm_skill(s) for s in split_list(j.get("preferred_skills"))]
    miss_m = [s for s in mand if not skill_hit(s, have)]
    miss_p = [s for s in pref if not skill_hit(s, have)]
    # Skills
    if not mand and not pref:
        comps["skills"] = {"score": 0, "assessed": False, "detail": "Job lists no skills"}
        missing_data.append("Job skills")
    elif not have:
        comps["skills"] = {"score": 0, "assessed": False, "detail": "Candidate has not added skills"}
        missing_data.append("Candidate skills")
    else:
        rm = (len(mand) - len(miss_m)) / len(mand) if mand else None
        rp = (len(pref) - len(miss_p)) / len(pref) if pref else None
        ratio = rm * 0.7 + rp * 0.3 if rm is not None and rp is not None else (rm if rm is not None else rp)
        s = round(WEIGHTS["skills"] * ratio, 1)
        comps["skills"] = {"score": s, "assessed": True,
                           "detail": f"{len(mand) - len(miss_m)}/{len(mand)} mandatory, {len(pref) - len(miss_p)}/{len(pref)} preferred skills"}
        matched = [x for x in mand + pref if x not in miss_m + miss_p]
        if matched:
            reasons.append(f"Has {', '.join(matched[:5])}")
    if miss_m:
        flags.append(f"Missing mandatory skills: {', '.join(miss_m)}")
    # Designation
    job_title = j.get("title") or j.get("designation") or ""
    jt = title_tokens(job_title)
    titles, locs = candidate_lists(c)
    cand_titles = [t for t in [c.get("current_designation")] + titles if t]
    if not cand_titles:
        comps["designation"] = {"score": 0, "assessed": False, "detail": "Candidate has no current or preferred title"}
        missing_data.append("Candidate designation / preferred titles")
    else:
        best, best_t = 0.0, None
        for t in cand_titles:
            ct = title_tokens(t)
            if t.strip().lower() == job_title.strip().lower():
                r = 1.0
            else:
                r = len(ct & jt) / len(jt) if jt else 0
                if families(ct) & families(jt):
                    r = max(r, 0.6)
            if r > best:
                best, best_t = r, t
        s = round(WEIGHTS["designation"] * min(best, 1), 1)
        comps["designation"] = {"score": s, "assessed": True,
                                "detail": f"Closest title: {best_t}" if best_t else "No related title"}
        if best >= 0.6:
            reasons.append(f"Title “{best_t}” is related to {job_title}")
    # Experience
    exp = to_num(c.get("total_experience"))
    lo, hi = to_num(j.get("experience_min")), to_num(j.get("experience_max"))
    if lo is None and hi is None:
        comps["experience"] = {"score": 0, "assessed": False, "detail": "Job has no min/max experience"}
        missing_data.append("Job experience range")
    elif exp is None:
        comps["experience"] = {"score": 0, "assessed": False, "detail": "Candidate experience not provided"}
        missing_data.append("Candidate total experience")
    else:
        if (lo is None or exp >= lo) and (hi is None or exp <= hi):
            s = WEIGHTS["experience"]
            reasons.append(f"{exp:g} years experience fits the required range")
        elif lo is not None and exp < lo:
            s = max(0, WEIGHTS["experience"] - 5 * (lo - exp))
            flags.append(f"Below required experience ({exp:g} vs min {lo:g} yrs)")
        else:
            s = max(0, WEIGHTS["experience"] - 3 * (exp - hi))
            flags.append(f"Above experience range ({exp:g} vs max {hi:g} yrs)")
        comps["experience"] = {"score": round(s, 1), "assessed": True, "detail": f"{exp:g} yrs vs {lo if lo is not None else '—'}–{hi if hi is not None else '—'} yrs"}
    # Industry
    ji = j.get("industry_category") or j.get("function") or ""
    prefs = [i for i in (c.get("preferred_industries") or []) if i]
    cur = c.get("industry") or ""
    if not ji:
        comps["industry"] = {"score": 0, "assessed": False, "detail": "Job industry not set"}
        missing_data.append("Job industry")
    elif not prefs and not cur:
        comps["industry"] = {"score": 0, "assessed": False, "detail": "Candidate industries not provided"}
        missing_data.append("Candidate industry")
    else:
        related = any({ji, x} == set(pair) for pair in related_industries for x in prefs + [cur] if len(pair) == 2)
        if ji in prefs:
            s, d = 10, "Preferred industry"
        elif ji == cur:
            s, d = 8, "Current industry"
        elif related:
            s, d = 5, "Related industry (admin approved)"
        else:
            s, d = 0, "Different industry"
        comps["industry"] = {"score": s, "assessed": True, "detail": d}
        if s:
            reasons.append(f"{d}: {ji}")
    # Location
    jm = j.get("work_mode") or ""
    jloc = " ".join(x for x in [j.get("location"), j.get("city"), j.get("country")] if x).lower()
    if jm == "Remote":
        comps["location"] = {"score": 10, "assessed": True, "detail": "Remote job — location not a constraint"}
    elif not locs and not c.get("preferred_country"):
        comps["location"] = {"score": 0, "assessed": False, "detail": "Candidate preferred locations not provided"}
        missing_data.append("Candidate preferred location")
    else:
        hit = next((l for l in locs if l.lower() in jloc or (j.get("city") or "~").lower() in l.lower()), None)
        if hit:
            s, d = 10, f"Prefers {hit}"
        elif c.get("preferred_country") and c["preferred_country"].lower() in jloc:
            s, d = 6, f"Same preferred country ({c['preferred_country']})"
        elif c.get("willing_to_relocate"):
            s, d = 5, "Willing to relocate"
        else:
            s, d = 0, "Location not in preferences"
        comps["location"] = {"score": s, "assessed": True, "detail": d}
        if s >= 6:
            reasons.append(d)
    # Salary
    smin, smax = to_num(j.get("salary_min")), to_num(j.get("salary_max"))
    ectc = to_num(c.get("expected_ctc"))
    if smin is None and smax is None:
        comps["salary"] = {"score": 0, "assessed": False, "detail": "Job salary not disclosed"}
        missing_data.append("Job salary range")
    elif ectc is None:
        comps["salary"] = {"score": 0, "assessed": False, "detail": "Candidate expected CTC not provided"}
        missing_data.append("Candidate expected CTC")
    elif (c.get("expected_ctc_currency") or "INR") != (j.get("currency") or "INR"):
        comps["salary"] = {"score": 0, "assessed": False, "detail": "Different currency — compare manually"}
        missing_data.append("Comparable salary currency")
    else:
        top = smax if smax is not None else smin
        if ectc <= top:
            s, d = 10, "Expected CTC within range"
        elif ectc <= top * 1.15:
            s, d = 5, "Expected CTC slightly above range"
        else:
            s, d = 0, "Expected CTC above range"
        comps["salary"] = {"score": s, "assessed": True, "detail": d}
        if s == 10:
            reasons.append(d)
    # Work mode
    cm = c.get("preferred_work_mode") or ""
    if not cm or not jm:
        comps["work_mode"] = {"score": 0, "assessed": False, "detail": "Work mode not provided"}
        missing_data.append("Work mode")
    else:
        s = 5 if cm == "Any" or cm == jm else 2 if "Hybrid" in (cm, jm) else 0
        comps["work_mode"] = {"score": s, "assessed": True, "detail": f"Prefers {cm}, job is {jm}"}
        if s == 5:
            reasons.append(f"Work mode matches ({jm})")
    # Separate checks (not part of score)
    if j.get("qualifications") or j.get("mandatory_requirements"):
        flags.append("Check manually: " + "; ".join(x for x in [j.get("qualifications"), j.get("mandatory_requirements")] if x))
    jn, cn = NOTICE_DAYS.get(j.get("notice_period_pref") or ""), NOTICE_DAYS.get(c.get("notice_period") or "")
    if jn is not None and cn is not None and cn > jn:
        flags.append(f"Notice period {c['notice_period']} is longer than preferred ({j['notice_period_pref']})")
    et, ce = j.get("employment_type"), c.get("employment_type_pref")
    if et and ce and ce != "Any" and ce != et:
        flags.append(f"Prefers {ce}, job is {et}")
    total = round(sum(v["score"] for v in comps.values()))
    for k in comps:
        comps[k]["max"] = WEIGHTS[k]
    return {
        "match_score": total, "category": "Strong Match" if total >= 80 else "Potential Match" if total >= 65 else "Low Match",
        "components": comps, "explanation": reasons, "missing_mandatory_skills": miss_m, "missing_preferred_skills": miss_p,
        "mandatory_gap": bool(miss_m), "flags": flags, "provisional": bool(missing_data), "missing_data": missing_data,
    }


class ReviewReq(BaseModel):
    match_ids: List[str]
    action: str
    comment: Optional[str] = ""
    rejection_reason: Optional[str] = ""


class ShareReq(BaseModel):
    match_ids: List[str]
    channels: List[str]


class TemplateReq(BaseModel):
    subject: str
    body: str


class RelatedReq(BaseModel):
    pairs: List[List[str]]


class RespondReq(BaseModel):
    job_id: str
    response: str


class ActivityReq(BaseModel):
    job_id: str


class VerifyJobReq(BaseModel):
    verification_status: str
    note: Optional[str] = ""


def build_router(db, get_current_user, require_admin, compute_membership, send_and_log_email, wrap_email,
                 serialize_job, now_iso, audit):
    r = APIRouter()

    def today() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def eligible_q() -> dict:
        return {"status": "Published", "verification_status": "Verified",
                "$or": [{"expiry_date": {"$exists": False}}, {"expiry_date": {"$in": [None, ""]}}, {"expiry_date": {"$gte": today()}}]}

    def job_ineligible_reason(j: dict) -> Optional[str]:
        if j.get("verification_status") != "Verified":
            return f"Job is {j.get('verification_status') or 'not verified'}"
        if j.get("status") != "Published":
            return f"Job is {j.get('status')}, not Open"
        if j.get("expiry_date") and j["expiry_date"] < today():
            return "Job has expired"
        return None

    async def sweep_expired():
        await db.jobs.update_many({"status": "Published", "expiry_date": {"$nin": [None, ""], "$lt": today()}},
                                  {"$set": {"status": "Expired", "last_updated": now_iso()}})

    async def related_pairs() -> list:
        s = await db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0}) or {}
        return s.get("related_industries") or []

    def cand_eligible_q() -> dict:
        return {"role": "candidate", "suspended": {"$ne": True}, "profile_status": {"$ne": "Inactive"}}

    async def upsert_match(c: dict, j: dict, res: dict) -> dict:
        now = now_iso()
        existing = await db.job_matches.find_one({"candidate_id": c["user_id"], "job_id": j["job_id"]}, {"_id": 0})
        snap = {"job_title": j.get("title"), "company": j.get("company"), "job_location": j.get("location") or j.get("city"),
                "job_industry": j.get("industry_category") or j.get("function"), "job_source": j.get("job_source"),
                "candidate_name": c.get("full_name")}
        fields = {**res, **snap, "missing_skills": res["missing_mandatory_skills"] + res["missing_preferred_skills"],
                  "last_scored_at": now, "updated_at": now}
        if existing:
            upd: dict = {"$set": fields}
            if existing.get("match_score") != res["match_score"]:
                upd["$push"] = {"score_history": {"match_score": existing.get("match_score"), "components": existing.get("components"),
                                                  "scored_at": existing.get("last_scored_at")}}
            await db.job_matches.update_one({"match_id": existing["match_id"]}, upd)
            return {**existing, **fields}
        doc = {"match_id": f"mt_{uuid.uuid4().hex[:12]}", "candidate_id": c["user_id"], "job_id": j["job_id"], **fields,
               "status": "suggested", "reached": {"suggested": now}, "reviewed_by": None, "reviewed_at": None,
               "notification_status": "not_sent", "admin_comment": "", "rejection_reason": "", "score_history": [],
               "created_at": now}
        try:
            await db.job_matches.insert_one(dict(doc))
        except Exception:
            return await db.job_matches.find_one({"candidate_id": c["user_id"], "job_id": j["job_id"]}, {"_id": 0})
        return doc

    def cand_view(c: dict) -> dict:
        titles, locs = candidate_lists(c)
        return {"user_id": c["user_id"], "full_name": c.get("full_name"), "email": c.get("email"), "mobile": c.get("mobile"),
                "current_designation": c.get("current_designation"), "total_experience": c.get("total_experience"),
                "current_company": c.get("current_company"), "current_salary": c.get("current_salary"),
                "expected_ctc": c.get("expected_ctc"), "expected_ctc_currency": c.get("expected_ctc_currency") or "INR",
                "primary_skills": split_list(c.get("primary_skills")), "preferred_locations": locs, "preferred_titles": titles,
                "preferred_country": c.get("preferred_country"), "notice_period": c.get("notice_period"),
                "industry": c.get("industry"), "preferred_industries": c.get("preferred_industries") or [],
                "preferred_work_mode": c.get("preferred_work_mode"), "profile_status": c.get("profile_status") or "Active",
                "job_alert_consent": c.get("job_alert_consent") is True, "alert_pref": alert_pref(c),
                "suspended": bool(c.get("suspended")),
                **profile_status(c)}

    # ------------------------------------------------------------------ admin: jobs
    @r.get("/admin/smartmatch/meta")
    async def meta(admin=Depends(require_admin)):
        return {"sources": JOB_SOURCES, "verification": VERIFICATION, "statuses": MATCH_STATUSES, "weights": WEIGHTS,
                "notice_periods": list(NOTICE_DAYS), "related_industries": await related_pairs()}

    @r.put("/admin/smartmatch/related-industries")
    async def set_related(req: RelatedReq, admin=Depends(require_admin)):
        pairs = [p[:2] for p in req.pairs if len(p) >= 2 and p[0] != p[1]]
        await db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"related_industries": pairs}}, upsert=True)
        await audit(admin, "update_related_industries", "settings", "smartmatch", {"pairs": pairs})
        return {"related_industries": pairs}

    @r.post("/admin/smartmatch/jobs/{job_id}/verify")
    async def verify_job(job_id: str, req: VerifyJobReq, admin=Depends(require_admin)):
        if req.verification_status not in VERIFICATION:
            raise HTTPException(status_code=400, detail="Invalid verification status")
        res = await db.jobs.update_one({"job_id": job_id}, {"$set": {
            "verification_status": req.verification_status, "verified_by": admin["user_id"], "verified_at": now_iso(),
            "last_updated": now_iso()}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Job not found")
        await audit(admin, "verify_job", "job", job_id, {"verification_status": req.verification_status, "note": req.note})
        return {"ok": True}

    @r.get("/admin/smartmatch/duplicates")
    async def duplicates(admin=Depends(require_admin), company: str = "", title: str = "", location: str = "",
                         source_link: str = "", exclude: str = ""):
        ors = []
        if company and title:
            q = {"company": {"$regex": f"^{re.escape(company.strip())}$", "$options": "i"},
                 "title": {"$regex": f"^{re.escape(title.strip())}$", "$options": "i"}}
            if location:
                q["location"] = {"$regex": f"^{re.escape(location.strip())}$", "$options": "i"}
            ors.append(q)
        if source_link.strip():
            ors.append({"source_link": source_link.strip()})
        if not ors:
            return {"duplicates": []}
        q = {"$or": ors}
        if exclude:
            q["job_id"] = {"$ne": exclude}
        found = await db.jobs.find(q, {"_id": 0, "job_id": 1, "title": 1, "company": 1, "location": 1, "status": 1}).to_list(20)
        return {"duplicates": found}

    # ------------------------------------------------------------------ admin: matching
    @r.post("/admin/smartmatch/jobs/{job_id}/find-candidates")
    async def find_candidates(job_id: str, admin=Depends(require_admin)):
        await sweep_expired()
        j = await db.jobs.find_one({"job_id": job_id}, {"_id": 0})
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")
        why = job_ineligible_reason(j)
        if why:
            raise HTTPException(status_code=400, detail=f"{why}. Only verified, open and non-expired jobs can be matched.")
        rel = await related_pairs()
        cands = await db.users.find(cand_eligible_q(), {"_id": 0, "password": 0}).to_list(50000)
        for c in cands:
            await upsert_match(c, j, score_match(c, j, rel))
        await audit(admin, "find_matching_candidates", "job", job_id, {"candidates_scored": len(cands)})
        return {"scored": len(cands)}

    @r.post("/admin/smartmatch/candidates/{candidate_id}/find-jobs")
    async def find_jobs(candidate_id: str, admin=Depends(require_admin)):
        await sweep_expired()
        c = await db.users.find_one({"user_id": candidate_id, "role": "candidate"}, {"_id": 0, "password": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if c.get("suspended") or c.get("profile_status") == "Inactive":
            raise HTTPException(status_code=400, detail="Candidate is suspended or inactive")
        rel = await related_pairs()
        jobs = await db.jobs.find(eligible_q(), {"_id": 0}).to_list(5000)
        for j in jobs:
            await upsert_match(c, j, score_match(c, j, rel))
        await audit(admin, "find_matching_jobs", "candidate", candidate_id, {"jobs_scored": len(jobs)})
        return {"scored": len(jobs)}

    async def match_query(f: dict) -> dict:
        q: dict = {}
        for k in ("job_id", "candidate_id"):
            if f.get(k):
                q[k] = f[k]
        if f.get("status") and f["status"] != "All":
            q["status"] = {"$in": ["suggested", "pending_review"]} if f["status"] == "awaiting" else f["status"]
        rng = {}
        if f.get("min_score") not in (None, ""):
            rng["$gte"] = float(f["min_score"])
        if f.get("max_score") not in (None, ""):
            rng["$lte"] = float(f["max_score"])
        if rng:
            q["match_score"] = rng
        if f.get("industry") and f["industry"] != "All":
            q["job_industry"] = f["industry"]
        if f.get("source") and f["source"] != "All":
            q["job_source"] = f["source"]
        for k, field in (("location", "job_location"), ("company", "company"), ("job_title", "job_title")):
            if f.get(k):
                q[field] = {"$regex": re.escape(f[k]), "$options": "i"}
        jf: dict = {}
        if f.get("job_status") and f["job_status"] != "All":
            jf["status"] = f["job_status"]
        if f.get("work_mode") and f["work_mode"] != "All":
            jf["work_mode"] = f["work_mode"]
        if f.get("country"):
            jf["country"] = {"$regex": re.escape(f["country"]), "$options": "i"}
        if jf:
            ids = set(await db.jobs.distinct("job_id", jf))
            q["job_id"] = {"$in": list(ids & {f["job_id"]} if f.get("job_id") else ids)}
        cf: dict = {}
        for k, field in (("designation", "current_designation"), ("skills", "primary_skills")):
            if f.get(k):
                cf[field] = {"$regex": re.escape(f[k]), "$options": "i"}
        if f.get("notice_period") and f["notice_period"] != "All":
            cf["notice_period"] = f["notice_period"]
        if f.get("candidate_status") and f["candidate_status"] != "All":
            cf["profile_status"] = {"$ne": "Inactive"} if f["candidate_status"] == "Active" else "Inactive"
        er = {}
        if f.get("min_exp") not in (None, ""):
            er["$gte"] = float(f["min_exp"])
        if f.get("max_exp") not in (None, ""):
            er["$lte"] = float(f["max_exp"])
        if er:
            cf["total_experience"] = er
        if f.get("max_ctc") not in (None, ""):
            cf["expected_ctc"] = {"$lte": float(f["max_ctc"])}
        ids = None
        if cf:
            cf["role"] = "candidate"
            ids = set(await db.users.distinct("user_id", cf))
        ap, prof = f.get("alert_pref"), f.get("profile")
        if (ap and ap != "All") or (prof and prof != "All"):
            people = await db.users.find({"role": "candidate"}, {"_id": 0, "password": 0}).to_list(50000)
            keep = set()
            for u in people:
                p = alert_pref(u)
                if ap == "eligible" and (p == "opted_out" or u.get("suspended") or u.get("profile_status") == "Inactive"):
                    continue
                if ap in ALERT_PREF_LABEL and p != ap:
                    continue
                if prof in ("complete", "incomplete") and (profile_status(u)["completion"] == 100) != (prof == "complete"):
                    continue
                keep.add(u["user_id"])
            ids = keep if ids is None else ids & keep
        if f.get("received") in ("yes", "no") and f.get("job_id"):
            got = set(await db.job_notifications.distinct("candidate_id", {"job_id": f["job_id"], "status": "sent"}))
            if f["received"] == "yes":
                ids = got if ids is None else ids & got
            else:
                q.setdefault("$and", []).append({"candidate_id": {"$nin": list(got)}})
        if ids is not None:
            q["candidate_id"] = {"$in": list(ids & {f["candidate_id"]} if f.get("candidate_id") else ids)}
        return q

    async def enrich(matches: list) -> list:
        cids = list({m["candidate_id"] for m in matches})
        jids = list({m["job_id"] for m in matches})
        users = {u["user_id"]: u for u in await db.users.find({"user_id": {"$in": cids}}, {"_id": 0, "password": 0}).to_list(len(cids) + 1)}
        jobs = {j["job_id"]: j for j in await db.jobs.find({"job_id": {"$in": jids}}, {"_id": 0, "job_id": 1, "status": 1,
                                                                                       "verification_status": 1, "expiry_date": 1}).to_list(len(jids) + 1)}
        out = []
        for m in matches:
            u = users.get(m["candidate_id"])
            j = jobs.get(m["job_id"], {})
            out.append({**m, "status_label": MATCH_STATUSES.get(m["status"], m["status"]),
                        "candidate": cand_view(u) if u else None, "job_status": j.get("status"),
                        "job_eligible": not job_ineligible_reason(j) if j else False})
        return out

    FILTER_KEYS = ["alert_pref", "profile", "received", "job_id", "candidate_id", "status", "min_score", "max_score", "industry", "source", "location", "company",
                   "job_title", "job_status", "work_mode", "country", "designation", "skills", "notice_period",
                   "candidate_status", "min_exp", "max_exp", "max_ctc"]

    @r.get("/admin/smartmatch/matches")
    async def list_matches(admin=Depends(require_admin), page: int = 1, page_size: int = 25, alert_pref: str = "", profile: str = "",
                           received: str = "", job_id: str = "", candidate_id: str = "",
                           status: str = "", min_score: str = "", max_score: str = "", industry: str = "", source: str = "",
                           location: str = "", company: str = "", job_title: str = "", job_status: str = "", work_mode: str = "",
                           country: str = "", designation: str = "", skills: str = "", notice_period: str = "",
                           candidate_status: str = "", min_exp: str = "", max_exp: str = "", max_ctc: str = ""):
        loc = locals()
        try:
            q = await match_query({k: loc[k] for k in FILTER_KEYS})
        except ValueError:
            raise HTTPException(status_code=400, detail="Numeric filters must be numbers")
        page_size = max(1, min(page_size, 100))
        total = await db.job_matches.count_documents(q)
        items = await db.job_matches.find(q, {"_id": 0, "score_history": 0}).sort([("match_score", -1), ("updated_at", -1)]).skip(
            (max(page, 1) - 1) * page_size).limit(page_size).to_list(page_size)
        return {"matches": await enrich(items), "total": total, "page": page, "page_size": page_size}

    @r.get("/admin/smartmatch/matches/export")
    async def export_matches(admin=Depends(require_admin), alert_pref: str = "", profile: str = "", received: str = "",
                             job_id: str = "", candidate_id: str = "", status: str = "",
                             min_score: str = "", max_score: str = "", industry: str = "", source: str = "", location: str = "",
                             company: str = "", job_title: str = "", job_status: str = "", work_mode: str = "", country: str = "",
                             designation: str = "", skills: str = "", notice_period: str = "", candidate_status: str = "",
                             min_exp: str = "", max_exp: str = "", max_ctc: str = ""):
        loc = locals()
        q = await match_query({k: loc[k] for k in FILTER_KEYS})
        items = await enrich(await db.job_matches.find(q, {"_id": 0, "score_history": 0}).sort("match_score", -1).to_list(20000))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Match ID", "Candidate", "Candidate ID", "Email", "Current Designation", "Experience (yrs)", "Current CTC",
                    "Expected CTC", "Primary Skills", "Preferred Locations", "Notice Period", "Job ID", "Job Title", "Company",
                    "Score", "Category", "Provisional", "Missing Mandatory Skills", "Why", "Status", "Admin Comment"] + list(WEIGHTS))
        for m in items:
            c = m["candidate"] or {}
            w.writerow([m["match_id"], c.get("full_name"), m["candidate_id"], c.get("email"), c.get("current_designation"),
                        c.get("total_experience"), c.get("current_salary"), c.get("expected_ctc"), "; ".join(c.get("primary_skills") or []),
                        "; ".join(c.get("preferred_locations") or []), c.get("notice_period"), m["job_id"], m.get("job_title"),
                        m.get("company"), m["match_score"], m["category"], "Yes" if m["provisional"] else "No",
                        "; ".join(m["missing_mandatory_skills"]), "; ".join(m["explanation"]), m["status_label"],
                        m.get("admin_comment")] + [m["components"].get(k, {}).get("score") for k in WEIGHTS])
        await audit(admin, "export_matches", "job_matches", "-", {"rows": len(items)})
        return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="smartmatch-matches.csv"', "Cache-Control": "no-store"})

    @r.get("/admin/smartmatch/matches/{match_id}/history")
    async def match_history(match_id: str, admin=Depends(require_admin)):
        m = await db.job_matches.find_one({"match_id": match_id}, {"_id": 0})
        if not m:
            raise HTTPException(status_code=404, detail="Match not found")
        reviews = await db.match_reviews.find({"match_id": match_id}, {"_id": 0}).sort("at", -1).to_list(200)
        notes = await db.job_notifications.find({"candidate_id": m["candidate_id"], "job_id": m["job_id"]}, {"_id": 0, "body": 0}).to_list(20)
        return {"reviews": reviews, "score_history": m.get("score_history") or [], "notifications": notes}

    async def set_match_status(m: dict, status: str, by: Optional[dict], extra: Optional[dict] = None, note: str = ""):
        now = now_iso()
        upd = {"status": status, "updated_at": now, **(extra or {})}
        if status not in (m.get("reached") or {}):
            upd[f"reached.{status}"] = now
        await db.job_matches.update_one({"match_id": m["match_id"]}, {"$set": upd})
        await db.match_reviews.insert_one({"review_id": f"rv_{uuid.uuid4().hex[:12]}", "match_id": m["match_id"],
                                           "candidate_id": m["candidate_id"], "job_id": m["job_id"], "from_status": m.get("status"),
                                           "to_status": status, "by": by["user_id"] if by else "candidate",
                                           "by_role": by.get("role") if by else "candidate", "note": note, "at": now})

    @r.post("/admin/smartmatch/matches/review")
    async def review(req: ReviewReq, admin=Depends(require_admin)):
        actions = {"approve": "approved", "reject": "rejected", "pending_review": "pending_review", "close": "closed", "comment": None}
        if req.action not in actions:
            raise HTTPException(status_code=400, detail="Invalid action")
        if req.action == "reject" and not (req.rejection_reason or "").strip():
            raise HTTPException(status_code=400, detail="Please record a reason for rejection")
        if not req.match_ids or len(req.match_ids) > 200:
            raise HTTPException(status_code=400, detail="Select between 1 and 200 matches")
        done, skipped = 0, []
        for mid in req.match_ids:
            m = await db.job_matches.find_one({"match_id": mid}, {"_id": 0})
            if not m:
                skipped.append({"match_id": mid, "reason": "not found"})
                continue
            if req.action == "comment":
                await db.job_matches.update_one({"match_id": mid}, {"$set": {"admin_comment": req.comment or "", "updated_at": now_iso()}})
                await audit(admin, "comment_match", "job_match", mid, {"comment": req.comment})
                done += 1
                continue
            if req.action == "approve":
                j = await db.jobs.find_one({"job_id": m["job_id"]}, {"_id": 0})
                why = job_ineligible_reason(j or {})
                if why:
                    skipped.append({"match_id": mid, "reason": why})
                    continue
                if m["status"] in ("shared", "interested", "not_interested", "applied", "interview_reported"):
                    skipped.append({"match_id": mid, "reason": "already shared"})
                    continue
            extra = {"reviewed_by": admin["user_id"], "reviewed_at": now_iso()}
            if req.comment:
                extra["admin_comment"] = req.comment
            if req.action == "reject":
                extra["rejection_reason"] = req.rejection_reason.strip()
            await set_match_status(m, actions[req.action], admin, extra, req.rejection_reason or req.comment or "")
            await audit(admin, f"{req.action}_match", "job_match", mid, {"comment": req.comment, "rejection_reason": req.rejection_reason})
            done += 1
        return {"updated": done, "skipped": skipped}

    # ------------------------------------------------------------------ alerts
    async def get_template() -> dict:
        s = await db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0}) or {}
        return s.get("template") or DEFAULT_TEMPLATE

    def render(text: str, c: dict, j: dict, m: dict) -> str:
        exp = (f"{j['experience_min']:g}–{j['experience_max']:g} years" if to_num(j.get("experience_min")) is not None and to_num(j.get("experience_max")) is not None
               else j.get("experience_required") or "Not specified")
        vals = {"[Candidate Name]": c.get("full_name") or "there", "[Designation]": j.get("title") or "",
                "[Company Name]": j.get("company") or "", "[Location]": j.get("location") or j.get("city") or "",
                "[Experience]": exp, "[Salary]": j.get("salary_range") or "Not disclosed", "[Score]": str(m["match_score"]),
                "[Match Explanation]": "\n".join(f"- {x}" for x in m.get("explanation") or []) or "- Your profile preferences"}
        for k, v in vals.items():
            text = text.replace(k, v)
        return text

    @r.get("/admin/smartmatch/template")
    async def template(admin=Depends(require_admin)):
        return {"template": await get_template(), "placeholders": ["[Candidate Name]", "[Designation]", "[Company Name]", "[Location]",
                                                                   "[Experience]", "[Salary]", "[Score]", "[Match Explanation]"]}

    @r.put("/admin/smartmatch/template")
    async def save_template(req: TemplateReq, admin=Depends(require_admin)):
        t = {"subject": req.subject.strip()[:200], "body": req.body.strip()[:4000]}
        if not t["subject"] or not t["body"]:
            raise HTTPException(status_code=400, detail="Subject and message are required")
        await db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"template": t}}, upsert=True)
        await audit(admin, "update_alert_template", "settings", "smartmatch", {})
        return {"template": t}

    FREQ_DAYS = {"Daily": 1, "Weekly": 7}

    @r.post("/admin/smartmatch/matches/share")
    async def share(req: ShareReq, admin=Depends(require_admin)):
        channels = [ch for ch in req.channels if ch in ("in_app", "email")]
        if not channels:
            raise HTTPException(status_code=400, detail="Choose at least one channel (in-app or email)")
        if not req.match_ids or len(req.match_ids) > 200:
            raise HTTPException(status_code=400, detail="Select between 1 and 200 matches")
        tpl = await get_template()
        results = []
        for mid in req.match_ids:
            m = await db.job_matches.find_one({"match_id": mid}, {"_id": 0})
            if not m:
                results.append({"match_id": mid, "result": "skipped", "reason": "not found"})
                continue
            if m["status"] not in ("approved", "shared"):
                results.append({"match_id": mid, "result": "skipped", "reason": "match is not approved"})
                continue
            j = await db.jobs.find_one({"job_id": m["job_id"]}, {"_id": 0})
            why = job_ineligible_reason(j or {})
            if why:
                results.append({"match_id": mid, "result": "skipped", "reason": why})
                continue
            c = await db.users.find_one({"user_id": m["candidate_id"]}, {"_id": 0, "password": 0})
            if not c or c.get("suspended") or c.get("profile_status") == "Inactive":
                results.append({"match_id": mid, "result": "skipped", "reason": "candidate inactive"})
                continue
            pref = alert_pref(c)
            if pref == "opted_out":
                results.append({"match_id": mid, "result": "skipped", "reason": "candidate opted out of job alerts"})
                continue
            if m["match_score"] < MIN_RELEVANCE:
                results.append({"match_id": mid, "result": "skipped", "reason": f"low relevance (score {m['match_score']} < {MIN_RELEVANCE})"})
                continue
            any_sent = False
            for ch in channels:
                if ch == "email" and pref != "enabled":
                    results.append({"match_id": mid, "channel": ch, "result": "skipped",
                                    "reason": "email needs the candidate's opt-in — no preference selected, in-app only"})
                    continue
                prev = await db.job_notifications.find_one({"candidate_id": c["user_id"], "job_id": j["job_id"], "channel": ch}, {"_id": 0})
                if prev and prev["status"] == "sent":
                    results.append({"match_id": mid, "channel": ch, "result": "skipped", "reason": "already sent"})
                    continue
                if ch == "email" and FREQ_DAYS.get(c.get("job_alert_frequency")):
                    since = (datetime.now(timezone.utc) - timedelta(days=FREQ_DAYS[c["job_alert_frequency"]])).isoformat()
                    if await db.job_notifications.find_one({"candidate_id": c["user_id"], "channel": "email", "status": "sent", "sent_at": {"$gte": since}}):
                        results.append({"match_id": mid, "channel": ch, "result": "skipped",
                                        "reason": f"candidate prefers {c['job_alert_frequency'].lower()} emails — already emailed in this period"})
                        continue
                subject, body = render(tpl["subject"], c, j, m), render(tpl["body"], c, j, m)
                status, error = "sent", None
                if ch == "email":
                    inner = (f'<div style="color:#374151;font-size:15px;line-height:1.6">{escape(body).replace(chr(10), "<br>")}</div>'
                             '<p style="color:#9CA3AF;font-size:12px;margin-top:20px">You receive this because you opted in to JobRadar job alerts. '
                             'To stop or change them, update Job Alerts in your JobRadar profile.</p>')
                    log = await send_and_log_email(candidate_id=c["user_id"], to=c["email"], email_type="smartmatch_alert",
                                                   subject=subject, html=wrap_email("New job match", inner))
                    if (log or {}).get("delivery_status") == "failed":
                        raw = (log or {}).get("error_message") or ""
                        status = "failed"
                        error = ("Email service is busy (rate limited) — please retry in a minute" if raw.startswith("429")
                                 else "Email could not be delivered — please retry later")
                now = now_iso()
                await db.job_notifications.update_one(
                    {"candidate_id": c["user_id"], "job_id": j["job_id"], "channel": ch},
                    {"$set": {"match_id": mid, "status": status, "error": error, "subject": subject, "body": body,
                              "sent_by": admin["user_id"], "sent_at": now if status == "sent" else None, "updated_at": now},
                     "$setOnInsert": {"notification_id": f"nt_{uuid.uuid4().hex[:12]}", "read_at": None, "created_at": now},
                     "$inc": {"attempts": 1}}, upsert=True)
                results.append({"match_id": mid, "channel": ch, "result": status, "reason": error})
                any_sent = any_sent or status == "sent"
            if any_sent:
                if m["status"] == "approved":
                    await set_match_status(m, "shared", admin, {"notification_status": "sent"})
                else:
                    await db.job_matches.update_one({"match_id": mid}, {"$set": {"notification_status": "sent"}})
                await audit(admin, "share_match", "job_match", mid, {"channels": channels})
        return {"results": results}

    # ------------------------------------------------------------------ admin: candidates + audit + analytics
    @r.get("/admin/smartmatch/candidates")
    async def sm_candidates(admin=Depends(require_admin), q: str = "", industry: str = "", designation: str = "", skills: str = "",
                            location: str = "", country: str = "", work_mode: str = "", notice_period: str = "",
                            candidate_status: str = "", min_exp: str = "", max_exp: str = "", page: int = 1, page_size: int = 25):
        query: dict = {"role": "candidate"}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            query["$or"] = [{"full_name": rx}, {"email": rx}, {"user_id": q}]
        if industry and industry != "All":
            query["industry"] = industry
        for val, field in ((designation, "current_designation"), (skills, "primary_skills"), (country, "preferred_country")):
            if val:
                query[field] = {"$regex": re.escape(val), "$options": "i"}
        if location:
            rx = {"$regex": re.escape(location), "$options": "i"}
            query.setdefault("$and", []).append({"$or": [{"preferred_locations": rx}, {"preferred_location": rx}]})
        if work_mode and work_mode != "All":
            query["preferred_work_mode"] = work_mode
        if notice_period and notice_period != "All":
            query["notice_period"] = notice_period
        if candidate_status == "Active":
            query["profile_status"] = {"$ne": "Inactive"}
        elif candidate_status == "Inactive":
            query["profile_status"] = "Inactive"
        er = {}
        try:
            if min_exp:
                er["$gte"] = float(min_exp)
            if max_exp:
                er["$lte"] = float(max_exp)
        except ValueError:
            raise HTTPException(status_code=400, detail="Experience must be a number")
        if er:
            query["total_experience"] = er
        page_size = max(1, min(page_size, 100))
        total = await db.users.count_documents(query)
        users = await db.users.find(query, {"_id": 0, "password": 0}).sort("created_at", -1).skip((max(page, 1) - 1) * page_size).limit(page_size).to_list(page_size)
        return {"candidates": [cand_view(u) for u in users], "total": total, "page": page, "page_size": page_size}

    @r.get("/admin/smartmatch/candidates/{candidate_id}")
    async def sm_candidate(candidate_id: str, admin=Depends(require_admin)):
        u = await db.users.find_one({"user_id": candidate_id, "role": "candidate"}, {"_id": 0, "password": 0})
        if not u:
            raise HTTPException(status_code=404, detail="Candidate not found")
        v = cand_view(u)
        v.update({"secondary_skills": split_list(u.get("secondary_skills")), "willing_to_relocate": u.get("willing_to_relocate"),
                  "employment_type_pref": u.get("employment_type_pref"), "job_alert_frequency": u.get("job_alert_frequency"),
                  "updated_at": u.get("updated_at"), "created_at": u.get("created_at")})
        return {"candidate": v}

    @r.get("/admin/smartmatch/audit")
    async def audit_log(admin=Depends(require_admin), entity_id: str = "", limit: int = 100):
        q = {"entity_id": entity_id} if entity_id else {}
        return {"entries": await db.admin_audit_log.find(q, {"_id": 0}).sort("at", -1).limit(min(limit, 500)).to_list(500)}

    @r.get("/admin/smartmatch/analytics")
    async def analytics(admin=Depends(require_admin), start: str = "", end: str = "", industry: str = "", source: str = "",
                        location: str = "", designation: str = ""):
        await sweep_expired()
        from tracker import _range
        rng = _range(start or None, end or None)
        jq: dict = {}
        if industry and industry != "All":
            jq["industry_category"] = industry
        if source and source != "All":
            jq["job_source"] = source
        if location:
            jq["location"] = {"$regex": re.escape(location), "$options": "i"}
        if designation:
            jq["title"] = {"$regex": re.escape(designation), "$options": "i"}
        jobs = await db.jobs.find(jq, {"_id": 0, "job_id": 1, "status": 1, "verification_status": 1, "expiry_date": 1,
                                       "date_received": 1, "date_added": 1}).to_list(20000)
        if rng:
            jobs_in = [j for j in jobs if rng.get("$gte", "") <= (j.get("date_received") or j.get("date_added") or "") < rng.get("$lt", "~")]
        else:
            jobs_in = jobs
        job_ids = [j["job_id"] for j in jobs]
        mq: dict = {"job_id": {"$in": job_ids}}
        if rng:
            mq["created_at"] = rng
        matches = await db.job_matches.find(mq, {"_id": 0, "candidate_id": 1, "job_id": 1, "status": 1, "reached": 1}).to_list(100000)
        reached = lambda s: [m for m in matches if s in (m.get("reached") or {})]  # noqa: E731
        nq: dict = {"job_id": {"$in": job_ids}}
        if rng:
            nq["created_at"] = rng
        notes = await db.job_notifications.find(nq, {"_id": 0, "status": 1, "channel": 1}).to_list(100000)
        pairs = {(m["candidate_id"], m["job_id"]) for m in matches}
        trk = [t for t in await db.job_tracker.find({"job_id": {"$in": job_ids}, "archived": {"$ne": True}},
                                                     {"_id": 0, "candidate_id": 1, "job_id": 1, "reached": 1, "interview_verification": 1,
                                                      "hire_verification": 1}).to_list(100000)
               if (t["candidate_id"], t["job_id"]) in pairs]
        users = await db.users.find({"role": "candidate"}, {"_id": 0, "password": 0}).to_list(50000)
        approved, shared = reached("approved"), reached("shared")
        reviewed = [m for m in matches if {"approved", "rejected"} & set((m.get("reached") or {}))]
        responded = [m for m in shared if {"interested", "not_interested", "applied"} & set(m.get("reached") or {})]
        interested = [m for m in shared if {"interested", "applied"} & set(m.get("reached") or {})]
        applied, interviews = reached("applied"), reached("interview_reported")
        sent = [n for n in notes if n["status"] == "sent"]
        attempted = [n for n in notes if n["status"] in ("sent", "failed")]
        pct = lambda a, b: round(len(a) * 100 / len(b), 1) if b else None  # noqa: E731
        return {
            "candidates": {"total": len(users), "active": sum(1 for u in users if not u.get("suspended") and u.get("profile_status") != "Inactive"),
                           "complete_profiles": sum(1 for u in users if profile_status(u)["completion"] == 100)},
            "jobs": {"received": len(jobs_in), "verified": sum(1 for j in jobs_in if j.get("verification_status") == "Verified"),
                     "active": sum(1 for j in jobs_in if not job_ineligible_reason(j)), "expired": sum(1 for j in jobs_in if j.get("status") == "Expired")},
            "matches": {"candidates_matched": len({m["candidate_id"] for m in matches}), "total": len(matches),
                        "awaiting_review": sum(1 for m in matches if m["status"] in ("suggested", "pending_review")),
                        "approved": len(approved), "shared": len(shared), "responses": len(responded), "applied": len(applied),
                        "interviews": len(interviews)},
            "outcomes": {"offers_reported": sum(1 for t in trk if "offer_received" in (t.get("reached") or {})),
                         "hires_reported": sum(1 for t in trk if t.get("hire_verification")),
                         "hires_verified": sum(1 for t in trk if t.get("hire_verification") == "verified"),
                         "interviews_reported": sum(1 for t in trk if t.get("interview_verification")),
                         "interviews_verified": sum(1 for t in trk if t.get("interview_verification") == "verified")},
            "kpis": [
                {"label": "Candidate Job Delivery Rate", "value": pct(shared, approved), "explain": "Shared ÷ approved matches"},
                {"label": "Match Approval Rate", "value": pct(approved, reviewed), "explain": "Approved ÷ reviewed (approved + rejected) matches"},
                {"label": "Candidate Interest Rate", "value": pct(interested, shared), "explain": "Interested or applied ÷ shared matches"},
                {"label": "Job Alert Delivery Rate", "value": pct(sent, attempted), "explain": "Delivered ÷ attempted alerts (in-app + email)"},
                {"label": "Independently Reported Application Rate", "value": pct([m for m in applied if "shared" in (m.get("reached") or {})], shared),
                 "explain": "Shared matches where the candidate reported applying ÷ shared matches"},
                {"label": "Interview Reporting Rate", "value": pct([m for m in interviews if "applied" in (m.get("reached") or {})], applied),
                 "explain": "Applied matches that reported an interview ÷ applied matches"},
                {"label": "Employer Revenue", "value": None, "explain": "Not tracked yet — JobRadar has no employer billing"},
            ],
            "alert_prefs": {
                "active_candidates": sum(1 for u in users if not u.get("suspended") and u.get("profile_status") != "Inactive"),
                "enabled": sum(1 for u in users if alert_pref(u) == "enabled"), "none": sum(1 for u in users if alert_pref(u) == "none"),
                "opted_out": sum(1 for u in users if alert_pref(u) == "opted_out"),
                "eligible_in_app": sum(1 for u in users if alert_pref(u) != "opted_out" and not u.get("suspended") and u.get("profile_status") != "Inactive"),
                "notifications_sent": len(attempted), "notifications_delivered": len(sent),
                "notifications_failed": sum(1 for n in notes if n["status"] == "failed"), "candidate_responses": len(responded)},
            "alerts": {"sent": len(sent), "failed": sum(1 for n in notes if n["status"] == "failed"),
                       "email_sent": sum(1 for n in sent if n["channel"] == "email"), "in_app_sent": sum(1 for n in sent if n["channel"] == "in_app")},
        }

    # ------------------------------------------------------------------ candidate
    async def log_activity(uid: str, job_id: str, kind: str):
        await db.candidate_job_activity.insert_one({"activity_id": f"ac_{uuid.uuid4().hex[:12]}", "candidate_id": uid,
                                                     "job_id": job_id, "type": kind, "at": now_iso()})

    async def on_tracker_status(candidate_id: str, job_id: str, status: str):
        mapping = {"interested": "interested", "applied": "applied", "interview_scheduled": "interview_reported",
                   "interview_completed": "interview_reported"}
        await log_activity(candidate_id, job_id, f"tracker:{status}")
        target = mapping.get(status)
        m = await db.job_matches.find_one({"candidate_id": candidate_id, "job_id": job_id}, {"_id": 0})
        if not target or not m or m["status"] not in ("shared", "interested", "not_interested", "applied", "interview_reported"):
            return
        order = ["shared", "not_interested", "interested", "applied", "interview_reported"]
        if order.index(target) > order.index(m["status"]):
            await set_match_status(m, target, None)

    @r.get("/smartmatch/profile-status")
    async def my_profile_status(user=Depends(get_current_user)):
        return profile_status(user)

    @r.post("/smartmatch/activity")
    async def activity(req: ActivityReq, user=Depends(get_current_user)):
        if user.get("role") == "candidate" and await db.jobs.find_one({"job_id": req.job_id}, {"_id": 1}):
            await log_activity(user["user_id"], req.job_id, "view")
        return {"ok": True}

    @r.post("/smartmatch/respond")
    async def respond(req: RespondReq, user=Depends(get_current_user)):
        if req.response not in ("interested", "not_interested"):
            raise HTTPException(status_code=400, detail="Invalid response")
        if not await db.jobs.find_one({"job_id": req.job_id}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Job not found")
        await log_activity(user["user_id"], req.job_id, req.response)
        m = await db.job_matches.find_one({"candidate_id": user["user_id"], "job_id": req.job_id}, {"_id": 0})
        if m and m["status"] in ("shared", "interested", "not_interested"):
            await set_match_status(m, req.response, None)
        return {"ok": True}

    @r.get("/smartmatch/notifications")
    async def my_notifications(user=Depends(get_current_user)):
        if alert_pref(user) == "opted_out":
            return {"notifications": [], "unread": 0, "pref": "opted_out"}
        notes = await db.job_notifications.find({"candidate_id": user["user_id"], "channel": "in_app", "status": "sent"},
                                                {"_id": 0, "notification_id": 1, "job_id": 1, "subject": 1, "sent_at": 1, "read_at": 1}).sort("sent_at", -1).to_list(30)
        jobs = {j["job_id"]: j for j in await db.jobs.find({"job_id": {"$in": [n["job_id"] for n in notes]}},
                                                           {"_id": 0, "job_id": 1, "title": 1, "company": 1, "status": 1}).to_list(50)}
        out = [{**n, "title": jobs.get(n["job_id"], {}).get("title"), "company": jobs.get(n["job_id"], {}).get("company")} for n in notes if n["job_id"] in jobs]
        return {"notifications": out, "unread": sum(1 for n in out if not n.get("read_at")), "pref": alert_pref(user)}

    @r.get("/admin/alert-manager/jobs")
    async def am_jobs(admin=Depends(require_admin)):
        await sweep_expired()
        jobs = await db.jobs.find(eligible_q(), {"_id": 0, "job_id": 1, "title": 1, "company": 1, "location": 1, "city": 1,
                                                 "date_published": 1, "date_added": 1}).sort("date_added", -1).to_list(2000)
        ids = [j["job_id"] for j in jobs]
        mc = {d["_id"]: d for d in await db.job_matches.aggregate([{"$match": {"job_id": {"$in": ids}}}, {"$group": {
            "_id": "$job_id", "matches": {"$sum": 1},
            "approved": {"$sum": {"$cond": [{"$in": ["$status", ["approved", "shared", "interested", "applied", "interview_reported"]]}, 1, 0]}}}}]).to_list(5000)}
        nc = {d["_id"]: d["n"] for d in await db.job_notifications.aggregate([{"$match": {"job_id": {"$in": ids}, "status": "sent", "channel": "in_app"}},
                                                                              {"$group": {"_id": "$job_id", "n": {"$sum": 1}}}]).to_list(5000)}
        return {"jobs": [{**j, "matches": mc.get(j["job_id"], {}).get("matches", 0), "approved": mc.get(j["job_id"], {}).get("approved", 0),
                          "notified": nc.get(j["job_id"], 0)} for j in jobs]}

    @r.get("/admin/alert-manager/jobs/{job_id}/recipients")
    async def am_recipients(job_id: str, admin=Depends(require_admin)):
        notes = await db.job_notifications.find({"job_id": job_id}, {"_id": 0, "body": 0}).sort("updated_at", -1).to_list(5000)
        users = {u["user_id"]: u for u in await db.users.find({"user_id": {"$in": [n["candidate_id"] for n in notes]}},
                                                             {"_id": 0, "user_id": 1, "full_name": 1, "email": 1}).to_list(5000)}
        return {"recipients": [{**n, "candidate_name": users.get(n["candidate_id"], {}).get("full_name"),
                                "candidate_email": users.get(n["candidate_id"], {}).get("email")} for n in notes]}

    @r.post("/smartmatch/notifications/{notification_id}/read")
    async def read_note(notification_id: str, user=Depends(get_current_user)):
        await db.job_notifications.update_one({"notification_id": notification_id, "candidate_id": user["user_id"], "read_at": None},
                                              {"$set": {"read_at": now_iso()}})
        return {"ok": True}

    @r.delete("/smartmatch/my-data")
    async def delete_my_data(user=Depends(get_current_user)):
        uid = user["user_id"]
        await asyncio.gather(db.job_matches.delete_many({"candidate_id": uid}), db.match_reviews.delete_many({"candidate_id": uid}),
                             db.job_notifications.delete_many({"candidate_id": uid}), db.candidate_job_activity.delete_many({"candidate_id": uid}))
        await db.users.update_one({"user_id": uid}, {"$set": {"job_alert_consent": False}})
        await db.consent_records.insert_one({"consent_id": f"cs_{uuid.uuid4().hex[:12]}", "user_id": uid, "type": "job_alerts",
                                             "granted": False, "source": "delete_smartmatch_data", "at": now_iso()})
        return {"ok": True}

    @r.get("/smartmatch/me")
    async def my_matches(user=Depends(get_current_user)):
        if user.get("role") != "candidate":
            raise HTTPException(status_code=403, detail="Only candidates have job matches")
        await sweep_expired()
        uid = user["user_id"]
        m = await compute_membership(uid)
        is_member = m["is_active"]
        rel = await related_pairs()
        jobs = await db.jobs.find(eligible_q(), {"_id": 0, "admin_notes": 0, "verification_score": 0}).to_list(5000)
        saved_ids = {s["job_id"] for s in await db.saved_jobs.find({"candidate_id": uid}, {"_id": 0, "job_id": 1}).to_list(1000)}
        not_int = set(await db.job_matches.distinct("job_id", {"candidate_id": uid, "status": "not_interested"}))
        not_int |= set(await db.candidate_job_activity.distinct("job_id", {"candidate_id": uid, "type": "not_interested"}))
        tracked = {t["job_id"]: t["status"] for t in await db.job_tracker.find({"candidate_id": uid, "archived": {"$ne": True}},
                                                                               {"_id": 0, "job_id": 1, "status": 1}).to_list(1000)}

        def card(j):
            res = score_match(user, j, rel)
            return {**serialize_job(j, is_member, j["job_id"] in saved_ids), "match": {
                k: res[k] for k in ("match_score", "category", "explanation", "missing_mandatory_skills", "provisional", "missing_data", "flags")},
                "tracked_status": tracked.get(j["job_id"]), "not_interested": j["job_id"] in not_int}

        cards = {j["job_id"]: card(j) for j in jobs}
        ranked = sorted((c for c in cards.values() if not c["not_interested"]), key=lambda c: -c["match"]["match_score"])
        recent_cut = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent = sorted([c for c in cards.values() if (c.get("date_published") or c.get("date_added") or "") >= recent_cut],
                        key=lambda c: c.get("date_published") or c.get("date_added") or "", reverse=True)
        viewed_ids, seen = [], set()
        for a in await db.candidate_job_activity.find({"candidate_id": uid, "type": "view"}, {"_id": 0, "job_id": 1}).sort("at", -1).to_list(200):
            if a["job_id"] not in seen:
                seen.add(a["job_id"])
                viewed_ids.append(a["job_id"])
        notes = [] if alert_pref(user) == "opted_out" else await db.job_notifications.find(
            {"candidate_id": uid, "channel": "in_app", "status": "sent"}, {"_id": 0}).sort("sent_at", -1).to_list(100)
        shared = []
        for n in notes:
            c = cards.get(n["job_id"])
            if c:
                shared.append({**c, "notification": {k: n.get(k) for k in ("notification_id", "subject", "body", "sent_at", "read_at")}})
        return {
            "profile": profile_status(user), "alerts": {"consent": user.get("job_alert_consent") is True, "pref": alert_pref(user), "frequency": user.get("job_alert_frequency") or "Instant"},
            "recommended": [c for c in ranked if c["match"]["match_score"] >= 65][:12],
            "strong": [c for c in ranked if c["match"]["match_score"] >= 80][:12],
            "recent": recent[:12], "saved": [cards[i] for i in saved_ids if i in cards],
            "viewed": [cards[i] for i in viewed_ids if i in cards][:12], "shared": shared,
            "unread": sum(1 for n in notes if not n.get("read_at")),
        }

    return r, {"sweep_expired": sweep_expired, "on_tracker_status": on_tracker_status}
