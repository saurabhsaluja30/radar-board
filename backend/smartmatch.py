import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Dict, List, Optional

from ops import tracked
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from pymongo import ReturnDocument, UpdateOne
from pymongo.errors import DuplicateKeyError

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
SWEEP_INTERVAL_S = 300  # how often non-admin requests may trigger the expiry sweep
SCORE_HISTORY_MAX = 20  # keep only the most recent score changes per match
MY_MATCHES_TTL_S = 300  # per-candidate cache for /smartmatch/me scoring
JOBS_CACHE_TTL_S = 60  # shared matchable-job list used by /smartmatch/me
SCORE_CACHE_MAX = 5000  # candidates kept in the score cache
QUEUE_BATCH = 200  # candidates scored per batch when a job is matched
QUEUE_LOCK_MINUTES = 10
QUEUE_MAX_ATTEMPTS = 3
# Automatic in-app job alerts (no email, so no sending cost). Admin-adjustable in the Control Room.
AUTO_ALERT_DEFAULTS = {"enabled": True, "min_score": 80, "max_per_day": 5, "max_job_age_days": 14}
# Profile and job fields that change match scores. A save that touches none of them triggers no rematch.
CANDIDATE_MATCH_FIELDS = ("primary_skills", "secondary_skills", "tools", "certifications", "current_designation", "preferred_titles",
                          "preferred_designation", "total_experience", "relevant_experience", "industry", "preferred_industries",
                          "industry_experience", "preferred_locations", "preferred_location", "preferred_country", "current_location",
                          "willing_to_relocate", "expected_ctc", "expected_ctc_currency", "preferred_work_mode", "notice_period",
                          "employment_type_pref", "profile_status", "suspended")
JOB_MATCH_FIELDS = ("title", "designation", "required_skills", "preferred_skills", "experience_min", "experience_max",
                    "industry_category", "function", "location", "city", "country", "work_mode", "salary_min", "salary_max",
                    "currency", "status", "verification_status", "expiry_date", "qualifications", "mandatory_requirements",
                    "notice_period_pref", "employment_type")


def fields_sig(doc: dict, fields) -> str:
    return hashlib.sha1(json.dumps([doc.get(k) for k in fields], default=str).encode()).hexdigest()
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


# Fields the SmartMatch analytics page reads from each candidate (profile completion + alert preference).
ANALYTICS_USER_FIELDS = {"_id": 0, "user_id": 1, "suspended": 1, "profile_status": 1, "job_alert_consent": 1,
                         "preferred_designation": 1, "preferred_location": 1, **{k: 1 for k, _ in PROFILE_FIELDS}}


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


def score_match(c: dict, j: dict, related_industries: list, weights: Optional[dict] = None) -> dict:
    """Score a candidate against a job. Components are computed on the default WEIGHTS scale and then rescaled
    to `weights` (admin-configured, summing to 100) so the scoring rules stay in one place."""
    comps, reasons, missing_data, flags = {}, [], [], []
    # Skills include tools and certifications confirmed from the candidate's resume.
    have = {norm_skill(s) for s in split_list(c.get("primary_skills")) + split_list(c.get("secondary_skills"))
            + split_list(c.get("tools")) + split_list(c.get("certifications"))}
    mand = [norm_skill(s) for s in split_list(j.get("required_skills"))]
    pref = [norm_skill(s) for s in split_list(j.get("preferred_skills"))]
    miss_m = [s for s in mand if not skill_hit(s, have)]
    miss_p = [s for s in pref if not skill_hit(s, have)]
    matched = [x for x in mand + pref if x not in miss_m + miss_p] if have else []
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
        rel_exp = to_num(c.get("relevant_experience"))
        if rel_exp is not None and lo is not None and rel_exp < lo <= exp:
            flags.append(f"Relevant experience {rel_exp:g} yrs is below the {lo:g}-year minimum")
    # Industry
    ji = j.get("industry_category") or j.get("function") or ""
    prefs = [i for i in (c.get("preferred_industries") or []) if i]
    cur = c.get("industry") or ""
    worked_in = [i for i in (c.get("industry_experience") or []) if i]
    if not ji:
        comps["industry"] = {"score": 0, "assessed": False, "detail": "Job industry not set"}
        missing_data.append("Job industry")
    elif not prefs and not cur and not worked_in:
        comps["industry"] = {"score": 0, "assessed": False, "detail": "Candidate industries not provided"}
        missing_data.append("Candidate industry")
    else:
        related = any({ji, x} == set(pair) for pair in related_industries for x in prefs + [cur] + worked_in if len(pair) == 2)
        if ji in prefs:
            s, d = 10, "Preferred industry"
        elif ji == cur:
            s, d = 8, "Current industry"
        elif ji in worked_in:
            s, d = 8, "Industry experience (from resume)"
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
    elif not locs and not c.get("preferred_country") and not c.get("current_location"):
        comps["location"] = {"score": 0, "assessed": False, "detail": "Candidate preferred locations not provided"}
        missing_data.append("Candidate preferred location")
    else:
        hit = next((l for l in locs if l.lower() in jloc or (j.get("city") or "~").lower() in l.lower()), None)
        cur_city = (c.get("current_location") or "").split(",")[0].strip().lower()
        if hit:
            s, d = 10, f"Prefers {hit}"
        elif cur_city and cur_city in jloc:
            s, d = 8, f"Currently based in {c['current_location']}"
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
    w = weights or WEIGHTS
    for k in comps:
        if w is not WEIGHTS:
            comps[k]["score"] = round(comps[k]["score"] / WEIGHTS[k] * w.get(k, 0), 1) if WEIGHTS[k] else 0
        comps[k]["max"] = w.get(k, 0)
    total = round(sum(v["score"] for v in comps.values()))
    return {
        "match_score": total, "category": "Strong Match" if total >= 80 else "Potential Match" if total >= 65 else "Low Match",
        "components": comps, "explanation": reasons, "missing_mandatory_skills": miss_m, "missing_preferred_skills": miss_p,
        "mandatory_gap": bool(miss_m), "flags": flags, "provisional": bool(missing_data), "missing_data": missing_data,
        "matched_skills": list(dict.fromkeys(matched))[:15],
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


class WeightsReq(BaseModel):
    weights: Dict[str, int]


class AutoAlertReq(BaseModel):
    enabled: bool
    min_score: int
    max_per_day: int
    max_job_age_days: int


class RespondReq(BaseModel):
    job_id: str
    response: str


class ActivityReq(BaseModel):
    job_id: str


class JdCheckReq(BaseModel):
    jd_text: Optional[str] = ""
    job_id: Optional[str] = None


class VerifyJobReq(BaseModel):
    verification_status: str
    note: Optional[str] = ""


class _LazyCards:
    """Dict-like view that builds a job card only when it is looked up."""

    def __init__(self, jobs: dict, build):
        self._jobs, self._build = jobs, build

    def __contains__(self, jid):
        return jid in self._jobs

    def __getitem__(self, jid):
        return self._build(jid)

    def get(self, jid, default=None):
        return self._build(jid) if jid in self._jobs else default


def build_router(db, get_current_user, require_admin, compute_membership, send_and_log_email, wrap_email,
                 serialize_job, now_iso, audit, bg=None):
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

    sweep_state = {"at": 0.0}

    async def sweep_expired(force: bool = False):
        """Flip past-expiry jobs to Expired. Public reads also filter by expiry date themselves
        (see live_job_q), so outside admin flows this only needs to run occasionally."""
        now = time.monotonic()
        if not force and now - sweep_state["at"] < SWEEP_INTERVAL_S:
            return
        sweep_state["at"] = now
        res = await db.jobs.update_many({"status": "Published", "expiry_date": {"$nin": [None, ""], "$lt": today()}},
                                        {"$set": {"status": "Expired", "last_updated": now_iso()}})
        if res.modified_count:
            jobs_cache["at"] = 0.0

    async def related_pairs() -> list:
        s = await db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0}) or {}
        return s.get("related_industries") or []

    async def weights() -> dict:
        s = await db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0, "weights": 1}) or {}
        w = s.get("weights")
        return w if isinstance(w, dict) and set(w) == set(WEIGHTS) else dict(WEIGHTS)

    def cand_eligible_q() -> dict:
        return {"role": "candidate", "suspended": {"$ne": True}, "profile_status": {"$ne": "Inactive"}}

    async def upsert_matches(pairs: list, existing_q: dict, min_score: Optional[int] = None) -> None:
        """Save many (candidate, job, score) results with one read and batched writes.
        `existing_q` selects the job_matches rows that may already exist for these pairs.
        With `min_score`, new rows are only created for relevant scores (existing rows are always refreshed),
        so automatic matching doesn't store a row for every low-scoring pair."""
        now = now_iso()
        existing = {(e["candidate_id"], e["job_id"]): e for e in await db.job_matches.find(
            existing_q, {"_id": 0, "candidate_id": 1, "job_id": 1, "match_id": 1, "match_score": 1, "components": 1,
                         "last_scored_at": 1}).to_list(None)}
        ops = []
        for c, j, res in pairs:
            snap = {"job_title": j.get("title"), "company": j.get("company"), "job_location": j.get("location") or j.get("city"),
                    "job_industry": j.get("industry_category") or j.get("function"), "job_source": j.get("job_source"),
                    "candidate_name": c.get("full_name")}
            fields = {**res, **snap, "missing_skills": res["missing_mandatory_skills"] + res["missing_preferred_skills"],
                      "last_scored_at": now, "updated_at": now}
            ex = existing.get((c["user_id"], j["job_id"]))
            if ex:
                upd: dict = {"$set": fields}
                if ex.get("match_score") != res["match_score"]:
                    upd["$push"] = {"score_history": {"$each": [{"match_score": ex.get("match_score"), "components": ex.get("components"),
                                                                 "scored_at": ex.get("last_scored_at")}],
                                                      "$slice": -SCORE_HISTORY_MAX}}
                ops.append(UpdateOne({"match_id": ex["match_id"]}, upd))
            elif min_score is not None and res["match_score"] < min_score:
                continue
            else:
                doc = {"match_id": f"mt_{uuid.uuid4().hex[:12]}", "candidate_id": c["user_id"], "job_id": j["job_id"], **fields,
                       "status": "suggested", "reached": {"suggested": now}, "reviewed_by": None, "reviewed_at": None,
                       "notification_status": "not_sent", "admin_comment": "", "rejection_reason": "", "score_history": [],
                       "created_at": now}
                # $setOnInsert keeps a row created concurrently by another request instead of failing.
                ops.append(UpdateOne({"candidate_id": c["user_id"], "job_id": j["job_id"]}, {"$setOnInsert": doc}, upsert=True))
        for i in range(0, len(ops), 1000):
            await db.job_matches.bulk_write(ops[i:i + 1000], ordered=False)

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
        jobs_cache["at"] = 0.0
        await job_changed(job_id, "verification changed")
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
        await sweep_expired(force=True)
        j = await db.jobs.find_one({"job_id": job_id}, {"_id": 0})
        if not j:
            raise HTTPException(status_code=404, detail="Job not found")
        why = job_ineligible_reason(j)
        if why:
            raise HTTPException(status_code=400, detail=f"{why}. Only verified, open and non-expired jobs can be matched.")
        n = await match_job(j, min_score=None)
        await audit(admin, "find_matching_candidates", "job", job_id, {"candidates_scored": n})
        return {"scored": n}

    async def match_job(j: dict, min_score: Optional[int]) -> int:
        """Score every eligible candidate for one job, in batches so memory stays flat."""
        rel, w = await related_pairs(), await weights()
        n, batch = 0, []

        async def flush():
            ids = [c["user_id"] for c in batch]
            results = await asyncio.to_thread(lambda: [(c, j, score_match(c, j, rel, w)) for c in batch])
            await upsert_matches(results, {"job_id": j["job_id"], "candidate_id": {"$in": ids}}, min_score)

        async for c in db.users.find(cand_eligible_q(), {"_id": 0, "password": 0}):
            batch.append(c)
            if len(batch) >= QUEUE_BATCH:
                await flush()
                n += len(batch)
                batch = []
        if batch:
            await flush()
            n += len(batch)
        await db.jobs.update_one({"job_id": j["job_id"]}, {"$set": {"last_matched_at": now_iso()}})
        return n

    async def match_candidate(c: dict, min_score: Optional[int]) -> int:
        rel, w = await related_pairs(), await weights()
        jobs = await db.jobs.find(eligible_q(), {"_id": 0}).to_list(5000)
        results = await asyncio.to_thread(lambda: [(c, j, score_match(c, j, rel, w)) for j in jobs])
        await upsert_matches(results, {"candidate_id": c["user_id"]}, min_score)
        await db.users.update_one({"user_id": c["user_id"]}, {"$set": {"last_matched_at": now_iso()}})
        return len(jobs)


    @r.post("/admin/smartmatch/candidates/{candidate_id}/find-jobs")
    async def find_jobs(candidate_id: str, admin=Depends(require_admin)):
        await sweep_expired(force=True)
        c = await db.users.find_one({"user_id": candidate_id, "role": "candidate"}, {"_id": 0, "password": 0})
        if not c:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if c.get("suspended") or c.get("profile_status") == "Inactive":
            raise HTTPException(status_code=400, detail="Candidate is suspended or inactive")
        n = await match_candidate(c, min_score=None)
        await audit(admin, "find_matching_jobs", "candidate", candidate_id, {"jobs_scored": n})
        return {"scored": n}

    # ------------------------------------------------------------------ automatic matching queue
    # Matching runs when a job becomes matchable or a candidate's match-relevant details change, never on page visits.
    # Each change becomes one queue item; repeated changes before it runs coalesce into that item. An atomic claim
    # with a lock means only one replica processes an item, and a crashed replica's item is retried after the lock expires.
    queue_gate = asyncio.Semaphore(1)

    async def enqueue(kind: str, ref_id: str, reason: str):
        try:
            await db.match_queue.update_one(
                {"kind": kind, "ref_id": ref_id, "status": "queued"},
                {"$setOnInsert": {"queue_id": f"mq_{uuid.uuid4().hex[:12]}", "kind": kind, "ref_id": ref_id, "status": "queued",
                                  "attempts": 0, "lock_until": None, "created_at": now_iso()},
                 "$addToSet": {"reasons": reason}}, upsert=True)
        except DuplicateKeyError:
            pass  # another request queued the same item at the same moment
        if bg:
            bg(drain_queue(20))

    async def claim_queue_item() -> Optional[dict]:
        now = datetime.now(timezone.utc)
        return await db.match_queue.find_one_and_update(
            {"$or": [{"status": "queued"},
                     {"status": {"$in": ["processing", "failed"]}, "attempts": {"$lt": QUEUE_MAX_ATTEMPTS}, "lock_until": {"$lt": now}}]},
            {"$set": {"status": "processing", "lock_until": now + timedelta(minutes=QUEUE_LOCK_MINUTES), "started_at": now_iso()},
             "$inc": {"attempts": 1}},
            sort=[("created_at", 1)], projection={"_id": 0}, return_document=ReturnDocument.AFTER)

    async def process_item(item: dict) -> dict:
        if item["kind"] == "job":
            j = await db.jobs.find_one({"job_id": item["ref_id"]}, {"_id": 0})
            if not j or job_ineligible_reason(j):
                return {"skipped": "job not matchable"}
            n = await match_job(j, min_score=MIN_RELEVANCE)
            return {"candidates_scored": n, "alerts": await auto_alert({"job_id": j["job_id"]})}
        c = await db.users.find_one({"user_id": item["ref_id"], "role": "candidate"}, {"_id": 0, "password": 0})
        if not c or c.get("suspended") or c.get("profile_status") == "Inactive":
            return {"skipped": "candidate not matchable"}
        n = await match_candidate(c, min_score=MIN_RELEVANCE)
        return {"jobs_scored": n, "alerts": await auto_alert({"candidate_id": c["user_id"]})}

    async def alert_settings() -> dict:
        s = (await db.app_settings.find_one({"key": "smartmatch"}, {"_id": 0, "auto_alerts": 1}) or {}).get("auto_alerts") or {}
        return {k: s.get(k, v) for k, v in AUTO_ALERT_DEFAULTS.items()}

    async def auto_alert(scope: dict) -> dict:
        """Create in-app alerts for relevant matches of recently published jobs.
        Respects opt-outs and muted job categories, never alerts twice for the same job, and caps alerts per
        candidate per day. A blank alert preference is not an opt-out: those candidates get in-app alerts too."""
        st = await alert_settings()
        out = {"sent": 0, "skipped": 0}
        if not st["enabled"]:
            return out
        since = (datetime.now(timezone.utc) - timedelta(days=st["max_job_age_days"])).isoformat()
        rows = await db.job_matches.find({**scope, "match_score": {"$gte": st["min_score"]}, "status": {"$ne": "rejected"},
                                          "mandatory_gap": {"$ne": True}},
                                         {"_id": 0, "match_id": 1, "candidate_id": 1, "job_id": 1, "match_score": 1,
                                          "explanation": 1}).sort("match_score", -1).to_list(5000)
        if not rows:
            return out
        jobs = {j["job_id"]: j for j in await db.jobs.find(
            {"job_id": {"$in": list({m["job_id"] for m in rows})}, **eligible_q(),
             "$and": [{"$or": [{"date_published": {"$gte": since}}, {"date_published": None, "date_added": {"$gte": since}}]}]},
            {"_id": 0, "job_id": 1, "title": 1, "company": 1, "industry_category": 1, "location": 1}).to_list(None)}
        cids = list({m["candidate_id"] for m in rows if m["job_id"] in jobs})
        users = {u["user_id"]: u for u in await db.users.find(
            {"user_id": {"$in": cids}, **cand_eligible_q()},
            {"_id": 0, "user_id": 1, "job_alert_consent": 1, "alert_muted_industries": 1}).to_list(None)}
        already = {(n["candidate_id"], n["job_id"]) for n in await db.job_notifications.find(
            {"candidate_id": {"$in": cids}, "job_id": {"$in": list(jobs)}, "channel": "in_app"},
            {"_id": 0, "candidate_id": 1, "job_id": 1}).to_list(None)}
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        today = {d["_id"]: d["n"] for d in await db.job_notifications.aggregate([
            {"$match": {"candidate_id": {"$in": cids}, "channel": "in_app", "source": "auto", "sent_at": {"$gte": day_ago}}},
            {"$group": {"_id": "$candidate_id", "n": {"$sum": 1}}}]).to_list(None)}
        now = now_iso()
        for m in rows:
            j, u = jobs.get(m["job_id"]), users.get(m["candidate_id"])
            if not j or not u or (m["candidate_id"], m["job_id"]) in already:
                continue
            if alert_pref(u) == "opted_out" or (j.get("industry_category") and j["industry_category"] in (u.get("alert_muted_industries") or [])) \
                    or today.get(u["user_id"], 0) >= st["max_per_day"]:
                out["skipped"] += 1
                continue
            reasons = "\n".join(f"- {x}" for x in (m.get("explanation") or [])[:4]) or "- Matches your profile"
            try:
                await db.job_notifications.insert_one({
                    "notification_id": f"nt_{uuid.uuid4().hex[:12]}", "candidate_id": u["user_id"], "job_id": j["job_id"],
                    "channel": "in_app", "status": "sent", "source": "auto", "match_id": m["match_id"],
                    "subject": f"New job match: {j.get('title')} at {j.get('company')}",
                    "body": f"This opportunity scores {m['match_score']}% against your profile.\n\nWhy it may suit you:\n{reasons}",
                    "sent_at": now, "read_at": None, "created_at": now, "updated_at": now, "attempts": 1})
            except DuplicateKeyError:
                continue  # alerted concurrently
            await db.job_matches.update_one({"match_id": m["match_id"]}, {"$set": {"auto_notified_at": now}})
            already.add((m["candidate_id"], m["job_id"]))
            today[u["user_id"]] = today.get(u["user_id"], 0) + 1
            out["sent"] += 1
        return out

    @r.get("/admin/smartmatch/auto-alerts")
    async def get_auto_alerts(admin=Depends(require_admin)):
        week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return {"settings": await alert_settings(),
                "sent_last_7_days": await db.job_notifications.count_documents({"source": "auto", "sent_at": {"$gte": week}}),
                "candidates_alerted_7_days": len(await db.job_notifications.distinct("candidate_id", {"source": "auto", "sent_at": {"$gte": week}}))}

    @r.put("/admin/smartmatch/auto-alerts")
    async def put_auto_alerts(req: AutoAlertReq, admin=Depends(require_admin)):
        if not 50 <= req.min_score <= 100 or not 1 <= req.max_per_day <= 20 or not 1 <= req.max_job_age_days <= 60:
            raise HTTPException(400, "Minimum score must be 50–100, alerts per day 1–20 and job age 1–60 days")
        val = req.dict()
        await db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"auto_alerts": val}}, upsert=True)
        await audit(admin, "update_auto_alerts", "settings", "smartmatch", val)
        return {"settings": val}

    async def drain_queue(limit: int):
        async with queue_gate:
            for _ in range(limit):
                item = await claim_queue_item()
                if not item:
                    return
                try:
                    result = await process_item(item)
                    await db.match_queue.update_one({"queue_id": item["queue_id"]}, {"$set": {
                        "status": "done", "result": result, "finished_at": now_iso(), "done_at": datetime.now(timezone.utc),
                        "lock_until": None}})
                    jobs_cache["at"] = 0.0
                except Exception as e:  # noqa: BLE001 - kept for retry by the cron
                    await db.match_queue.update_one({"queue_id": item["queue_id"]}, {"$set": {
                        "status": "failed", "error": f"{type(e).__name__}: {str(e)[:180]}", "lock_until": datetime.now(timezone.utc)}})

    async def job_changed(job_id: str, reason: str = "job updated"):
        """Queue matching when a job is (still) matchable and something that affects scores changed."""
        j = await db.jobs.find_one({"job_id": job_id}, {"_id": 0, **{k: 1 for k in JOB_MATCH_FIELDS}, "match_sig": 1, "job_id": 1})
        if not j or job_ineligible_reason(j):
            return False
        sig = fields_sig(j, JOB_MATCH_FIELDS)
        if sig == j.get("match_sig"):
            return False
        await db.jobs.update_one({"job_id": job_id}, {"$set": {"match_sig": sig}})
        await enqueue("job", job_id, reason)
        return True

    async def candidate_changed(user_id: str, reason: str = "profile updated"):
        u = await db.users.find_one({"user_id": user_id, "role": "candidate"},
                                    {"_id": 0, **{k: 1 for k in CANDIDATE_MATCH_FIELDS}, "match_sig": 1})
        if not u or u.get("suspended") or u.get("profile_status") == "Inactive":
            return False
        sig = fields_sig(u, CANDIDATE_MATCH_FIELDS)
        if sig == u.get("match_sig"):
            return False
        await db.users.update_one({"user_id": user_id}, {"$set": {"match_sig": sig}})
        await enqueue("candidate", user_id, reason)
        return True

    @r.post("/cron/smartmatch-queue")
    async def cron_queue(authorization: Optional[str] = Header(None)):
        secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not secret or not hmac.compare_digest(token, secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        if bg:
            bg(tracked("smartmatch-queue", drain_queue(50)))
        return {"accepted": True}

    @r.get("/admin/smartmatch/weights")
    async def get_weights(admin=Depends(require_admin)):
        return {"weights": await weights(), "defaults": WEIGHTS}

    @r.put("/admin/smartmatch/weights")
    async def put_weights(req: WeightsReq, admin=Depends(require_admin)):
        w = req.weights
        if set(w) != set(WEIGHTS) or any(not isinstance(v, int) or v < 0 for v in w.values()):
            raise HTTPException(400, f"Provide a whole-number weight for each of: {', '.join(WEIGHTS)}")
        if sum(w.values()) != 100:
            raise HTTPException(400, f"Weights must add up to 100 (they add up to {sum(w.values())})")
        await db.app_settings.update_one({"key": "smartmatch"}, {"$set": {"weights": w}}, upsert=True)
        jobs_cache["at"] = 0.0
        await audit(admin, "update_match_weights", "settings", "smartmatch", w)
        return {"weights": w}

    @r.post("/admin/smartmatch/rescore-all")
    async def rescore_all(admin=Depends(require_admin)):
        """Queue every open job for rescoring (e.g. after changing weights). Runs in the background in batches."""
        await sweep_expired(force=True)
        ids = await db.jobs.distinct("job_id", eligible_q())
        for jid in ids:
            await enqueue("job", jid, "admin rescore")
        await audit(admin, "rescore_all_matches", "settings", "smartmatch", {"jobs": len(ids)})
        return {"queued_jobs": len(ids)}

    @r.get("/admin/smartmatch/control-room")
    async def control_room(admin=Depends(require_admin)):
        await sweep_expired()
        job_ids = await db.jobs.distinct("job_id", eligible_q())
        cand_ids = set(await db.users.distinct("user_id", cand_eligible_q()))
        live = {"job_id": {"$in": job_ids}}
        by_band = {d["_id"]: d["n"] for d in await db.job_matches.aggregate([
            {"$match": {**live, "match_score": {"$gte": 65}}},
            {"$group": {"_id": {"$cond": [{"$gte": ["$match_score", 80]}, "strong", "potential"]}, "n": {"$sum": 1}}}]).to_list(None)}
        jobs_with = set(await db.job_matches.distinct("job_id", {**live, "match_score": {"$gte": 65}, "candidate_id": {"$in": list(cand_ids)}}))
        cands_with = set(await db.job_matches.distinct("candidate_id", {**live, "match_score": {"$gte": 65}}))
        lonely = [j for j in job_ids if j not in jobs_with]
        lonely_jobs = await db.jobs.find({"job_id": {"$in": lonely[:10]}}, {"_id": 0, "job_id": 1, "title": 1, "company": 1,
                                                                           "last_matched_at": 1}).to_list(10)
        queue = {d["_id"]: d["n"] for d in await db.match_queue.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(None)}
        last = await db.match_queue.find_one({"status": "done"}, {"_id": 0, "finished_at": 1}, sort=[("finished_at", -1)])
        return {
            "total_candidates": await db.users.count_documents({"role": "candidate"}),
            "candidates_with_resumes": await db.users.count_documents({"role": "candidate", "has_resume": True}),
            "active_jobs": len(job_ids),
            "strong_matches": by_band.get("strong", 0), "potential_matches": by_band.get("potential", 0),
            "awaiting_review": await db.job_matches.count_documents({**live, "status": {"$in": ["suggested", "pending_review"]},
                                                                     "match_score": {"$gte": 65}}),
            "approved": await db.job_matches.count_documents({**live, "status": "approved"}),
            "contacted": await db.job_matches.count_documents({**live, "contacted_at": {"$ne": None}}),
            "shortlisted": await db.job_matches.count_documents({**live, "shortlisted_at": {"$ne": None}}),
            "jobs_without_suitable": len(lonely), "jobs_without_suitable_list": lonely_jobs,
            "candidates_without_suitable": len(cand_ids - cands_with),
            "queue": queue, "last_processed_at": (last or {}).get("finished_at"), "weights": await weights(),
        }

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
        actions = {"approve": "approved", "reject": "rejected", "pending_review": "pending_review", "close": "closed", "comment": None,
                   "mark_contacted": None, "unmark_contacted": None, "mark_shortlisted": None, "unmark_shortlisted": None}
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
            if req.action.startswith(("mark_", "unmark_")):
                # Internal recruiter tracking; it doesn't change the match's review status or notify the candidate.
                tag = req.action.split("_", 1)[1]
                on = req.action.startswith("mark_")
                await db.job_matches.update_one({"match_id": mid}, {"$set": {
                    f"{tag}_at": now_iso() if on else None, f"{tag}_by": admin["user_id"] if on else None, "updated_at": now_iso()}})
                await audit(admin, req.action + "_match", "job_match", mid, {})
                done += 1
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
                # An automatic alert doesn't block an admin share: the share upgrades it (same notification, no duplicate).
                upgrading = bool(prev and prev["status"] == "sent" and prev.get("source") == "auto")
                if prev and prev["status"] == "sent" and not upgrading:
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
                    {"$set": {"match_id": mid, "status": status, "error": error, "subject": subject, "body": body, "source": "admin",
                              "sent_by": admin["user_id"], "sent_at": now if status == "sent" else None, "updated_at": now,
                              **({"read_at": None} if upgrading else {})},
                     "$setOnInsert": {"notification_id": f"nt_{uuid.uuid4().hex[:12]}", "created_at": now,
                                      **({} if upgrading else {"read_at": None})},
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
        await sweep_expired(force=True)
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
        # Count notifications on the database: one row per (status, channel) instead of every notification.
        notes = [{"status": d["_id"]["status"], "channel": d["_id"]["channel"], "n": d["n"]}
                 for d in await db.job_notifications.aggregate([
                     {"$match": nq}, {"$group": {"_id": {"status": "$status", "channel": "$channel"}, "n": {"$sum": 1}}}]).to_list(None)]
        pairs = {(m["candidate_id"], m["job_id"]) for m in matches}
        trk = [t for t in await db.job_tracker.find({"job_id": {"$in": job_ids}, "archived": {"$ne": True}},
                                                     {"_id": 0, "candidate_id": 1, "job_id": 1, "reached": 1, "interview_verification": 1,
                                                      "hire_verification": 1}).to_list(100000)
               if (t["candidate_id"], t["job_id"]) in pairs]
        users = await db.users.find({"role": "candidate"}, ANALYTICS_USER_FIELDS).to_list(50000)
        approved, shared = reached("approved"), reached("shared")
        reviewed = [m for m in matches if {"approved", "rejected"} & set((m.get("reached") or {}))]
        responded = [m for m in shared if {"interested", "not_interested", "applied"} & set(m.get("reached") or {})]
        interested = [m for m in shared if {"interested", "applied"} & set(m.get("reached") or {})]
        applied, interviews = reached("applied"), reached("interview_reported")
        n_sent = sum(n["n"] for n in notes if n["status"] == "sent")
        n_attempted = sum(n["n"] for n in notes if n["status"] in ("sent", "failed"))
        n_failed = sum(n["n"] for n in notes if n["status"] == "failed")
        n_email = sum(n["n"] for n in notes if n["status"] == "sent" and n["channel"] == "email")
        n_in_app = sum(n["n"] for n in notes if n["status"] == "sent" and n["channel"] == "in_app")
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
                {"label": "Job Alert Delivery Rate", "value": round(n_sent * 100 / n_attempted, 1) if n_attempted else None, "explain": "Delivered ÷ attempted alerts (in-app + email)"},
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
                "notifications_sent": n_attempted, "notifications_delivered": n_sent,
                "notifications_failed": n_failed, "candidate_responses": len(responded)},
            "alerts": {"sent": n_sent, "failed": n_failed, "email_sent": n_email, "in_app_sent": n_in_app},
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

    # Shared list of matchable jobs (same for every candidate) and per-candidate score cache, so the
    # My Matches page doesn't refetch and rescore every job on every visit.
    jobs_cache: dict = {"at": 0.0, "jobs": {}}
    jobs_lock = asyncio.Lock()
    score_cache: Dict[str, tuple] = {}
    MATCH_KEYS = ("match_score", "category", "explanation", "missing_mandatory_skills", "provisional", "missing_data", "flags",
                  "matched_skills", "mandatory_gap")

    def relevant(res: dict) -> bool:
        """Shown as a recommendation: Strong or Potential Match with no missing mandatory skill."""
        return res["match_score"] >= 65 and not res.get("mandatory_gap")

    async def eligible_jobs() -> tuple:
        async with jobs_lock:
            if time.monotonic() - jobs_cache["at"] > JOBS_CACHE_TTL_S:
                docs = await db.jobs.find(eligible_q(), {"_id": 0, "admin_notes": 0, "verification_score": 0}).to_list(5000)
                jobs_cache["jobs"] = {j["job_id"]: j for j in docs}
                jobs_cache["at"] = time.monotonic()
            return jobs_cache["at"], jobs_cache["jobs"]

    async def my_scores(user: dict, rel: list) -> tuple:
        version, jobs = await eligible_jobs()
        w = await weights()
        sig = hashlib.sha1(json.dumps([user, rel, w], sort_keys=True, default=str).encode()).hexdigest()
        hit = score_cache.get(user["user_id"])
        if hit and hit[0] == sig and hit[1] == version and time.monotonic() - hit[2] < MY_MATCHES_TTL_S:
            return jobs, hit[3]

        def run():
            return {jid: {k: res[k] for k in MATCH_KEYS} for jid, res in
                    ((jid, score_match(user, j, rel, w)) for jid, j in jobs.items())}

        scores = await asyncio.to_thread(run)
        if len(score_cache) >= SCORE_CACHE_MAX:
            score_cache.pop(next(iter(score_cache)))
        score_cache[user["user_id"]] = (sig, version, time.monotonic(), scores)
        return jobs, scores

    @r.get("/smartmatch/me")
    async def my_matches(user=Depends(get_current_user)):
        if user.get("role") != "candidate":
            raise HTTPException(status_code=403, detail="Only candidates have job matches")
        await sweep_expired()
        uid = user["user_id"]
        m = await compute_membership(uid)
        is_member = m["is_active"]
        rel = await related_pairs()
        jobs, scores = await my_scores(user, rel)
        saved_ids = {s["job_id"] for s in await db.saved_jobs.find({"candidate_id": uid}, {"_id": 0, "job_id": 1}).to_list(1000)}
        not_int = set(await db.job_matches.distinct("job_id", {"candidate_id": uid, "status": "not_interested"}))
        not_int |= set(await db.candidate_job_activity.distinct("job_id", {"candidate_id": uid, "type": "not_interested"}))
        tracked = {t["job_id"]: t["status"] for t in await db.job_tracker.find({"candidate_id": uid, "archived": {"$ne": True}},
                                                                               {"_id": 0, "job_id": 1, "status": 1}).to_list(1000)}

        # Jobs may have expired since the shared job list was cached.
        jobs = {jid: j for jid, j in jobs.items() if not job_ineligible_reason(j)}
        built: dict = {}

        def card(jid):
            # Only jobs that actually appear in the response are serialised.
            if jid not in built:
                j, res = jobs[jid], scores[jid]
                built[jid] = {**serialize_job(j, is_member, jid in saved_ids), "match": dict(res),
                              "tracked_status": tracked.get(jid), "not_interested": jid in not_int}
            return built[jid]

        cards = _LazyCards(jobs, card)
        ranked_ids = sorted((jid for jid in jobs if jid not in not_int), key=lambda jid: -scores[jid]["match_score"])
        recent_cut = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        def pub(jid):
            j = jobs[jid]
            return j.get("date_published") or j.get("date_added") or ""

        recent = [card(jid) for jid in sorted((jid for jid in jobs if pub(jid) >= recent_cut), key=pub, reverse=True)[:12]]
        ranked = [card(jid) for jid in [x for x in ranked_ids if relevant(scores[x])][:12]]
        strong = [card(jid) for jid in [x for x in ranked_ids if relevant(scores[x]) and scores[x]["match_score"] >= 80][:12]]
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
            "recommended": ranked,
            "strong": strong,
            "recent": recent, "saved": [cards[i] for i in saved_ids if i in cards],
            "viewed": [cards[i] for i in viewed_ids if i in cards][:12], "shared": shared,
            "unread": sum(1 for n in notes if not n.get("read_at")),
        }

    @r.get("/smartmatch/feed")
    async def matched_feed(q: str = "", industry_category: str = "All", region: str = "All", work_mode: str = "All",
                           employment_type: str = "All", location: str = "", designation: str = "",
                           min_salary: Optional[float] = None, max_experience: Optional[float] = None,
                           user=Depends(get_current_user)):
        """Default job feed for a signed-in candidate: only Strong and Potential matches without missing mandatory
        skills. Filters narrow this list further; they never add unrelated jobs."""
        if user.get("role") != "candidate":
            raise HTTPException(status_code=403, detail="Only candidates have a matched feed")
        uid = user["user_id"]
        is_member = (await compute_membership(uid))["is_active"]
        jobs, scores = await my_scores(user, await related_pairs())
        not_int = set(await db.candidate_job_activity.distinct("job_id", {"candidate_id": uid, "type": "not_interested"}))
        saved_ids = set(await db.saved_jobs.distinct("job_id", {"candidate_id": uid}))
        ql, loc, des = q.strip().lower(), location.strip().lower(), designation.strip().lower()

        def keep(j: dict) -> bool:
            text = " ".join(str(j.get(k) or "") for k in ("title", "company", "required_skills", "designation")).lower()
            place = " ".join(str(j.get(k) or "") for k in ("location", "city", "country")).lower()
            sal = to_num(j.get("salary_max")) or to_num(j.get("salary_min"))
            return ((not ql or ql in text) and (industry_category == "All" or j.get("industry_category") == industry_category)
                    and (region == "All" or j.get("region") == region) and (work_mode == "All" or j.get("work_mode") == work_mode)
                    and (employment_type == "All" or j.get("employment_type") == employment_type)
                    and (not loc or loc in place) and (not des or des in (j.get("title") or "").lower())
                    and (min_salary is None or (sal is not None and sal >= min_salary))
                    and (max_experience is None or (to_num(j.get("experience_min")) or 0) <= max_experience))

        live = {jid: j for jid, j in jobs.items() if not job_ineligible_reason(j) and jid not in not_int}
        rel = [jid for jid in live if relevant(scores[jid])]
        shown = sorted((jid for jid in rel if keep(live[jid])), key=lambda jid: -scores[jid]["match_score"])[:60]
        return {"jobs": [{**serialize_job(live[jid], is_member, jid in saved_ids), "match": dict(scores[jid])} for jid in shown],
                "relevant_total": len(rel), "hidden_unrelated": len(live) - len(rel), "profile": profile_status(user)}

    @r.post("/smartmatch/jd-check")
    async def jd_check(req: JdCheckReq, user=Depends(get_current_user)):
        """Candidate's own check of a job description against their confirmed profile, using the SmartMatch rules."""
        from jd_match import check
        if user.get("role") != "candidate":
            raise HTTPException(status_code=403, detail="Only candidates can run a JD match check")
        job = None
        if req.job_id:
            job = await db.jobs.find_one({"job_id": req.job_id, "status": "Published"}, {"_id": 0})
            if not job:
                raise HTTPException(404, "Job not found")
        text = (req.jd_text or "").strip()[:12000]
        if not job and len(text) < 80:
            raise HTTPException(400, "Please paste the complete job description (at least 80 characters)")
        out = await asyncio.to_thread(check, text, user, await related_pairs(), await weights(), job)
        await db.candidate_job_activity.insert_one({"candidate_id": user["user_id"], "type": "jd_check",
                                                    "job_id": req.job_id, "score": out["score"], "at": now_iso()})
        return {**out, "profile": profile_status(user),
                "disclaimer": "An advisory indicator based on your confirmed profile, not a prediction of selection."}

    def invalidate_jobs():
        jobs_cache["at"] = 0.0

    async def relevant_count(user: dict) -> int:
        """How many live jobs would be recommended to this candidate right now (cached per candidate)."""
        jobs, scores = await my_scores(user, await related_pairs())
        return sum(1 for jid, res in scores.items() if relevant(res) and jid in jobs and not job_ineligible_reason(jobs[jid]))

    async def score_job(user: dict, job: dict) -> int:
        return score_match(user, job, await related_pairs(), await weights())["match_score"]

    return r, {"sweep_expired": sweep_expired, "on_tracker_status": on_tracker_status, "invalidate_jobs": invalidate_jobs,
               "job_changed": job_changed, "candidate_changed": candidate_changed, "relevant_count": relevant_count,
               "score_job": score_job}
