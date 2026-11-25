"""Apify job discovery: approved job sources, daily/manual Actor runs, import into the central job database,
duplicate and expiry handling, the admin import review queue, and usage/cost tracking.

Imported jobs are never published automatically: they arrive as Draft / Pending Verification with
review_status "new_import" and need an admin to approve and publish them. SmartMatch and the public site
only ever see Published + Verified jobs, so unreviewed imports can't reach candidates.
"""
import base64
import hashlib
import hmac
import html as html_lib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from ops import tracked
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from pymongo import ReturnDocument, UpdateOne

from resume_parse import SKILLS
from smartmatch import candidate_lists

logger = logging.getLogger("jobradar.apify")

DEFAULT_ACTOR = "yugenox/ats-jobs-search"
# Known Actors and how to build their input. Any other Actor can be used with a per-source input template.
ACTOR_PRESETS = {
    "yugenox/ats-jobs-search": {"label": "Greenhouse, Lever & Ashby employer boards", "price_per_item_usd": 0.002},
    "fantastic-jobs/career-site-job-listing-api": {"label": "Career sites on 58 ATS platforms (incl. Workday)", "price_per_item_usd": 0.012},
    "bebity/linkedin-jobs-scraper": {"label": "LinkedIn job search (titles × locations, or company pages)", "price_per_item_usd": 0.0015},
}
LINKEDIN_ACTOR = "bebity/linkedin-jobs-scraper"
LINKEDIN_URL = re.compile(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/", re.I)
LINKEDIN_JOB = re.compile(r"^https?://([a-z]{2,3}\.)?(www\.)?linkedin\.com/jobs/view/(?:[^/?#]*-)?(\d{6,})", re.I)
DEFAULT_SETTINGS = {
    "actor_id": DEFAULT_ACTOR, "default_keywords": [], "default_locations": ["India"], "max_items_per_run": 200,
    "max_items_per_company": 25, "posted_within_days": 30, "monthly_budget_usd": 15.0, "per_run_cap_usd": 2.0,
    "paid_runs_approved": False, "auto_daily": True,
    "demand_search_enabled": False, "demand_max_pairs": 20, "demand_min_candidates": 2, "demand_jobs_per_pair": 10,
}
# A job search is a source with no URL: the LinkedIn Actor finds jobs matching its titles, locations and filters.
SEARCH_TYPE = "Job search (LinkedIn)"
# The candidate-demand search is a single system-managed source rebuilt daily from candidates' preferences.
DEMAND_TYPE = "Candidate demand search"
DEMAND_ID = "src_demand"
SOURCE_TYPES = [SEARCH_TYPE, "Employer career page", "Company recruitment page", "Authorised job API", "Permitted RSS feed",
                "Licensed job data provider", "Other permitted website"]
# JobRadar filter values → LinkedIn Actor input field and codes.
LI_FILTERS = {
    "experience": ("experienceLevels", {"Internship": "1", "Entry level": "2", "Associate": "3", "Mid-Senior level": "4",
                                        "Director": "5"}),
    "work_mode": ("workTypes", {"Work From Office": "1", "Remote": "2", "Hybrid": "3"}),
    "employment": ("contractTypes", {"Full-time": "F", "Part-time": "P", "Contract": "C", "Internship": "I"}),
}
NO_PREFERENCE = {"any", "anywhere", "all", "open", "na", "n/a", "none", "-", "not sure", "flexible"}
PERMISSION = ["Approved", "Pending review", "Not permitted"]
FREQUENCY = {"daily": 20, "weekly": 6.5 * 24, "manual": None}  # hours between automatic runs
REVIEW = ["new_import", "pending_review", "approved", "rejected", "archived"]
FINAL_STATES = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
SUSPICIOUS = re.compile(r"registration fee|pay(?:ment)? to apply|security deposit|processing fee|whatsapp\s*(?:us|me|on)|"
                        r"telegram|work from home and earn|earn \d+ ?(?:per|/) ?day|no interview|guaranteed job", re.I)
TRACKING_PARAMS = re.compile(r"^(utm_|gh_src|gh_jid$|source$|ref$|lever-source|lever-origin|trk$|refId$|trackingId$)", re.I)


# --------------------------------------------------------------------------- normalisation (pure)
def _first(item: dict, *keys):
    for k in keys:
        v = item.get(k)
        if isinstance(v, list):
            v = next((x for x in v if x not in (None, "")), None)
        if v not in (None, "", []):
            return v
    return None


def norm_url(u: Optional[str]) -> Optional[str]:
    if not u or not isinstance(u, str):
        return None
    m = LINKEDIN_JOB.match(u.strip())
    if m:  # in.linkedin.com/jobs/view/<slug>-<id>?trk=… and www.linkedin.com/jobs/view/<id> are the same job
        return f"https://www.linkedin.com/jobs/view/{m.group(3)}"
    p = urlsplit(u.strip())
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    q = "&".join(x for x in p.query.split("&") if x and not TRACKING_PARAMS.match(x.split("=")[0]))
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", q, ""))


def dedupe_key(company: str, title: str, location: str) -> str:
    n = lambda s: re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()  # noqa: E731
    return hashlib.sha1(f"{n(company)}|{n(title)}|{n(location).split(' ')[0] if n(location) else ''}".encode()).hexdigest()


def strip_html(s: str) -> str:
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s or "")
    s = re.sub(r"(?i)<li[^>]*>", "• ", s)
    return re.sub(r"\n{3,}", "\n\n", html_lib.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def _skills_in(text: str) -> List[str]:
    low = (text or "").lower()
    found = [t for t in SKILLS["technical"] + SKILLS["functional"] + SKILLS["tools"]
             if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)]
    return found[:15]


def _experience(text: str):
    m = re.search(r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs)", text or "", re.I)
    if m and int(m.group(1)) <= int(m.group(2)) <= 40:
        return float(m.group(1)), float(m.group(2))
    m = re.search(r"(\d{1,2})\s*\+\s*(?:years|yrs)|(?:minimum|at least|min\.?)\s*(?:of\s*)?(\d{1,2})\s*(?:years|yrs)", text or "", re.I)
    if m:
        v = float(m.group(1) or m.group(2))
        return (v, None) if v <= 40 else (None, None)
    return None, None


def _work_mode(item: dict) -> Optional[str]:
    v = str(_first(item, "workplaceType", "ai_work_arrangement", "location_type", "workMode", "workType") or "").lower()
    if item.get("isRemote") is True or "remote" in v:
        return "Remote"
    if "hybrid" in v:
        return "Hybrid"
    if "onsite" in v or "on-site" in v or "office" in v:
        return "Work From Office"
    return None


def _employment(item: dict) -> Optional[str]:
    v = str(_first(item, "employmentType", "employment_type", "ai_employment_type", "contractType") or "").lower().replace("_", "-")
    for key, label in (("full", "Full-time"), ("part", "Part-time"), ("contract", "Contract"), ("temp", "Contract"),
                       ("intern", "Internship")):
        if key in v:
            return label
    return None


def _date(v) -> Optional[str]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        m = re.match(r"\d{4}-\d{2}-\d{2}", str(v))
        return m.group(0) if m else None


# ATS actors report countries as ISO 3166 alpha-2 codes ("IN"); others use names ("India").
COUNTRY_CODES = {
    "IN": "India", "US": "United States", "GB": "United Kingdom", "UK": "United Kingdom", "AE": "United Arab Emirates",
    "SG": "Singapore", "CA": "Canada", "AU": "Australia", "DE": "Germany", "FR": "France", "NL": "Netherlands",
    "IE": "Ireland", "SA": "Saudi Arabia", "QA": "Qatar", "JP": "Japan", "MY": "Malaysia", "PH": "Philippines",
    "NZ": "New Zealand", "ES": "Spain", "IT": "Italy", "PL": "Poland", "BR": "Brazil", "MX": "Mexico",
    "HK": "Hong Kong", "ID": "Indonesia", "TH": "Thailand", "VN": "Vietnam", "KR": "South Korea", "CH": "Switzerland",
    "SE": "Sweden", "PT": "Portugal", "IL": "Israel", "ZA": "South Africa", "EG": "Egypt", "KE": "Kenya", "NG": "Nigeria",
}
INDIA_CITIES = re.compile(r"\b(bangalore|bengaluru|mumbai|delhi|new delhi|gurgaon|gurugram|noida|hyderabad|chennai|pune|"
                          r"kolkata|ahmedabad|jaipur|kochi|chandigarh|indore|coimbatore|thiruvananthapuram|trivandrum|"
                          r"navi mumbai|thane|mysore|mysuru|vadodara|lucknow|bhubaneswar|nagpur|surat|visakhapatnam)\b", re.I)


def _country(item: dict, location: str) -> str:
    raw = _first(item, "countries", "countries_derived", "country")
    name = str(raw or "").strip()
    if len(name) == 2 and name.isalpha():
        name = COUNTRY_CODES.get(name.upper(), name.upper())
    if not name and INDIA_CITIES.search(location or ""):
        name = "India"
    return name[:60]


def normalise(item: dict) -> dict:
    """Map one Actor dataset item onto JobRadar job fields. Only values present in the item are used."""
    desc = _first(item, "descriptionText", "description_text", "description")
    if not desc and item.get("descriptionHtml"):
        desc = strip_html(item["descriptionHtml"])
    desc = (desc or "").strip()[:20000]
    title = str(_first(item, "title", "jobTitle", "position") or "").strip()[:160]
    company = str(_first(item, "company", "organization", "companyName", "org_linkedin_name") or "").strip()[:120]
    location = str(_first(item, "location", "locations_derived", "allLocations", "cities_derived") or "").strip()[:160]
    country = _country(item, location)
    url = norm_url(_first(item, "url", "jobUrl", "link"))
    apply_url = _first(item, "applyUrl", "apply_url") or _first(item, "url", "jobUrl")
    smin = _first(item, "salaryMin", "ai_salary_min_value")
    smax = _first(item, "salaryMax", "ai_salary_max_value")
    exp_min, exp_max = _experience(desc)
    skills = _skills_in(desc)
    out = {
        "title": title, "company": company, "description": desc, "location": location,
        "city": location.split(",")[0].strip()[:60] if location else "", "country": country,
        "region": "India" if ("india" in f"{country} {location}".lower()) else ("International" if (country or location) else None),
        "work_mode": _work_mode(item), "employment_type": _employment(item),
        "salary_min": float(smin) if isinstance(smin, (int, float)) else None,
        "salary_max": float(smax) if isinstance(smax, (int, float)) else None,
        "currency": _first(item, "salaryCurrency", "ai_salary_currency"),
        "salary_range": str(_first(item, "salaryText", "salary") or "")[:120] if not isinstance(item.get("salary"), dict) else "",
        "required_skills": ", ".join(skills), "experience_min": exp_min, "experience_max": exp_max,
        "application_link": apply_url if isinstance(apply_url, str) else "", "source_link": url or "",
        "original_url": url, "original_posted_at": _date(_first(item, "postedAt", "date_posted", "datePosted", "publishedAt")),
        "application_deadline": _date(_first(item, "applicationDeadline", "date_valid_through")) or "",
        "external_id": str(_first(item, "jobId", "id", "internalJobId") or "")[:80],
        "closed_at_source": str(item.get("changeType") or "").lower() == "closed",
        "board": " ".join(str(item.get(k) or "") for k in ("companyBoardUrl", "companyToken", "company", "organization",
                                                           "companyName", "companyUrl")).lower(),
    }
    flags = []
    if not (title and company and desc and url):
        flags.append("incomplete")
    if desc and (len(desc) < 200 or SUSPICIOUS.search(desc)):
        flags.append("suspicious")
    if out["original_posted_at"] and out["original_posted_at"] < (datetime.now(timezone.utc) - timedelta(days=60)).date().isoformat():
        flags.append("old_posting")
    out["flags"] = flags
    out["dedupe_key"] = dedupe_key(company, title, location)
    out["content_hash"] = hashlib.sha1(f"{title}|{company}|{location}|{desc}|{smin}|{smax}".encode()).hexdigest()
    return out


def _posted_code(days: int) -> str:
    return "r86400" if days <= 1 else "r604800" if days <= 7 else "r2592000"


def linkedin_search_url(title: str, city: str, days: int = 7) -> str:
    """One exact LinkedIn search (title in one city), so pairs aren't crossed with every other title and city."""
    return "https://www.linkedin.com/jobs/search?" + urlencode({"keywords": title, "location": city, "f_TPR": _posted_code(days)})


def demand_pairs(candidates: List[dict], max_pairs: int = 20, min_candidates: int = 2) -> List[dict]:
    """The most-wanted (job title, city) pairs across active candidates. Only titles, cities and counts come out:
    nothing identifying a candidate is sent to Apify."""
    counts: Dict[tuple, int] = {}
    label: Dict[tuple, tuple] = {}
    for c in candidates:
        if c.get("suspended") or c.get("role", "candidate") != "candidate":
            continue
        titles, cities = candidate_lists(c)
        seen = set()
        for t in titles:
            for city in cities:
                key = (" ".join(t.lower().split()), " ".join(city.lower().split()))
                if key in seen or len(key[0]) < 2 or len(key[1]) < 2 or key[0] in NO_PREFERENCE or key[1] in NO_PREFERENCE:
                    continue
                seen.add(key)
                counts[key] = counts.get(key, 0) + 1
                label.setdefault(key, (" ".join(t.split())[:80], " ".join(city.split())[:60]))
    rows = [{"title": label[k][0], "city": label[k][1], "candidates": n} for k, n in counts.items() if n >= min_candidates]
    rows.sort(key=lambda r: (-r["candidates"], r["title"].lower(), r["city"].lower()))
    return rows[:max_pairs]


def linkedin_filters(filters: Optional[dict]) -> dict:
    out = {}
    for k, (field, codes) in LI_FILTERS.items():
        vals = [codes[v] for v in (filters or {}).get(k) or [] if v in codes]
        if vals:
            out[field] = vals
    return out


# --------------------------------------------------------------------------- API models
class SourceReq(BaseModel):
    name: str
    url: str = ""
    source_type: str = "Employer career page"
    filters: Dict[str, List[str]] = {}
    permission_status: str = "Pending review"
    permission_note: str = ""
    enabled: bool = False
    frequency: str = "daily"
    category: Optional[str] = None
    keywords: List[str] = []
    locations: List[str] = []
    actor_id: Optional[str] = None
    actor_input: Optional[Dict[str, Any]] = None


class SettingsReq(BaseModel):
    actor_id: str
    default_keywords: List[str] = []
    default_locations: List[str] = []
    max_items_per_run: int = 200
    max_items_per_company: int = 25
    posted_within_days: int = 30
    monthly_budget_usd: float = 15.0
    per_run_cap_usd: float = 2.0
    paid_runs_approved: bool = False
    auto_daily: bool = True
    demand_search_enabled: bool = False
    demand_max_pairs: int = 20
    demand_min_candidates: int = 2
    demand_jobs_per_pair: int = 10


class RunReq(BaseModel):
    source_ids: List[str] = []


class ReviewReq(BaseModel):
    job_ids: List[str]
    action: str
    industry_category: Optional[str] = None


def build_router(db, require_admin, audit_log, now_iso, bg, sm_helpers):
    r = APIRouter()
    api_base = (os.environ.get("APIFY_API_BASE") or "https://api.apify.com").rstrip("/")

    def token() -> Optional[str]:
        return os.environ.get("APIFY_TOKEN") or None

    def now() -> datetime:
        return datetime.now(timezone.utc)

    async def settings() -> dict:
        s = await db.app_settings.find_one({"key": "apify"}, {"_id": 0}) or {}
        return {k: s.get(k, v) for k, v in DEFAULT_SETTINGS.items()}

    async def apify(method: str, path: str, **kw) -> Any:
        if not token():
            raise HTTPException(503, "Apify isn't configured: set APIFY_TOKEN in the server's secrets.")
        async with httpx.AsyncClient(timeout=60) as c:
            resp = await c.request(method, f"{api_base}/v2{path}", headers={"Authorization": f"Bearer {token()}"}, **kw)
        if resp.status_code >= 400:
            raise HTTPException(502, f"Apify returned {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data.get("data", data) if isinstance(data, dict) else data

    async def month_spend() -> float:
        start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        agg = await db.apify_runs.aggregate([{"$match": {"started_at": {"$gte": start}}},
                                             {"$group": {"_id": None, "usd": {"$sum": {"$ifNull": ["$cost_usd", "$cost_cap_usd"]}}}}]).to_list(1)
        return round(agg[0]["usd"], 4) if agg else 0.0

    # ------------------------------------------------------------------ starting runs
    def actor_input(actor_id: str, srcs: List[dict], s: dict, keywords: List[str], locations: List[str]) -> dict:
        if srcs[0].get("actor_input"):
            return dict(srcs[0]["actor_input"])
        if actor_id == LINKEDIN_ACTOR:
            # Source URLs: a LinkedIn company page narrows the title × location search to that company; a pasted
            # LinkedIn job-search URL is scraped as-is. "https://www.linkedin.com/jobs" means a broad search.
            companies = [x["url"] for x in srcs if re.search(r"linkedin\.com/company/", x["url"], re.I)]
            searches = [x["url"] for x in srcs if re.search(r"linkedin\.com/jobs/search", x["url"], re.I)]
            days = s["posted_within_days"]
            out = {"titles": keywords, "locations": locations, "companyUrls": companies,
                   "rows": max(1, s["max_items_per_run"] // max(1, len(keywords) * max(1, len(locations)))),
                   "publishedAt": _posted_code(days), "companyProfile": False, "enrichCompany": False,  # enrichment is billed per job
                   **linkedin_filters(srcs[0].get("filters"))}
            if searches:
                out.update(startUrls=searches, maxRowsPerUrl=max(1, s["max_items_per_run"] // len(searches)))
            return out
        if actor_id == "fantastic-jobs/career-site-job-listing-api":
            return {"organizationSearch": [x["name"] for x in srcs], "titleSearch": keywords, "locationSearch": locations,
                    "limit": s["max_items_per_run"], "timeRange": "7d", "descriptionType": "text"}
        return {"companies": [x["url"] for x in srcs], "keywords": keywords, "locations": locations,
                "maxItems": s["max_items_per_run"], "maxItemsPerCompany": s["max_items_per_company"],
                "postedWithinDays": s["posted_within_days"], "includeDescription": True, "onlyNewOrChanged": True,
                "stateKey": "jobradar-" + hashlib.sha1("|".join(sorted(x["source_id"] for x in srcs)).encode()).hexdigest()[:12]}

    def source_actor(x: dict, s: dict) -> str:
        """A source's own Actor; LinkedIn URLs always use the LinkedIn Actor, and other URLs never do."""
        if x.get("source_type") in (SEARCH_TYPE, DEMAND_TYPE):
            return LINKEDIN_ACTOR
        if x.get("actor_id"):
            return x["actor_id"]
        if LINKEDIN_URL.match(x.get("url") or ""):
            return LINKEDIN_ACTOR
        return DEFAULT_ACTOR if s["actor_id"] == LINKEDIN_ACTOR else s["actor_id"]

    def groups(srcs: List[dict], s: dict) -> List[List[dict]]:
        """Sources sharing an Actor and filters run together, so a daily cycle is one run in the common case."""
        out: Dict[tuple, List[dict]] = {}
        for x in srcs:
            actor = source_actor(x, s)
            key = (actor, tuple(sorted(x.get("keywords") or s["default_keywords"])),
                   tuple(sorted(x.get("locations") or s["default_locations"])), x["source_id"] if x.get("actor_input") else "",
                   tuple(sorted((k, tuple(sorted(v))) for k, v in (x.get("filters") or {}).items())))
            out.setdefault(key, []).append(x)
        return list(out.values())

    async def start_runs(srcs: List[dict], trigger: str, admin: Optional[dict] = None) -> List[dict]:
        s = await settings()
        if not s["paid_runs_approved"]:
            raise HTTPException(409, "Apify runs need admin approval first: approve paid runs and set a monthly budget in Apify settings.")
        if not srcs:
            raise HTTPException(400, "No enabled, approved sources to collect from")
        if await db.apify_runs.find_one({"processed": False, "started_at": {"$gte": (now() - timedelta(hours=6)).isoformat()}}):
            raise HTTPException(409, "A collection run is still in progress. Check its status before starting another.")
        started = []
        for grp in groups(srcs, s):
            spent = await month_spend()
            remaining = round(s["monthly_budget_usd"] - spent, 4)
            if remaining <= 0.01:
                raise HTTPException(409, f"This month's Apify budget (${s['monthly_budget_usd']}) is used up (${spent} spent).")
            cap = round(min(s["per_run_cap_usd"], remaining), 2)
            actor = source_actor(grp[0], s)
            kws = grp[0].get("keywords") or s["default_keywords"]
            locs = grp[0].get("locations") or s["default_locations"]
            params: Dict[str, Any] = {"maxTotalChargeUsd": cap}
            secret, base = os.environ.get("APIFY_WEBHOOK_SECRET"), os.environ.get("PUBLIC_BACKEND_URL")
            if secret and base:
                hook = [{"eventTypes": ["ACTOR.RUN.SUCCEEDED", "ACTOR.RUN.FAILED", "ACTOR.RUN.ABORTED", "ACTOR.RUN.TIMED_OUT"],
                         "requestUrl": base.rstrip("/") + "/api/apify/webhook",
                         "headersTemplate": json.dumps({"X-JobRadar-Webhook": secret})}]
                params["webhooks"] = base64.b64encode(json.dumps(hook).encode()).decode()
            doc = {"run_id": f"ar_{uuid.uuid4().hex[:12]}", "actor_id": actor, "source_ids": [x["source_id"] for x in grp],
                   "trigger": trigger, "triggered_by": (admin or {}).get("email"), "status": "STARTING",
                   "started_at": now_iso(), "processed": False, "cost_cap_usd": cap, "finalizing_until": None}
            await db.apify_runs.insert_one(dict(doc))
            try:
                run = await apify("POST", f"/acts/{actor.replace('/', '~')}/runs", params=params,
                                  json=actor_input(actor, grp, s, kws, locs))
            except HTTPException as e:
                await db.apify_runs.update_one({"run_id": doc["run_id"]}, {"$set": {
                    "status": "FAILED", "processed": True, "error": e.detail, "cost_usd": 0.0, "finished_at": now_iso()}})
                await db.job_sources.update_many({"source_id": {"$in": doc["source_ids"]}}, {
                    "$inc": {"failed_attempts": 1}, "$set": {"last_error": e.detail, "last_checked_at": now_iso()}})
                raise
            await db.apify_runs.update_one({"run_id": doc["run_id"]}, {"$set": {
                "apify_run_id": run.get("id"), "dataset_id": run.get("defaultDatasetId"), "status": run.get("status", "RUNNING")}})
            await db.job_sources.update_many({"source_id": {"$in": doc["source_ids"]}}, {"$set": {"last_checked_at": now_iso()}})
            started.append({**doc, "apify_run_id": run.get("id")})
        return started

    # ------------------------------------------------------------------ finishing runs + import
    async def finalize(run_id: str) -> Optional[dict]:
        """Import a finished run's results. The lock lets exactly one replica do it."""
        t = now()
        doc = await db.apify_runs.find_one_and_update(
            {"run_id": run_id, "processed": False, "apify_run_id": {"$ne": None},
             "$or": [{"finalizing_until": None}, {"finalizing_until": {"$lt": t}}]},
            {"$set": {"finalizing_until": t + timedelta(minutes=10)}}, projection={"_id": 0}, return_document=ReturnDocument.AFTER)
        if not doc:
            return None
        try:
            run = await apify("GET", f"/actor-runs/{doc['apify_run_id']}")
            status = run.get("status", "RUNNING")
            cost = run_cost(run)
            if status not in FINAL_STATES:
                await db.apify_runs.update_one({"run_id": run_id}, {"$set": {"status": status, "finalizing_until": None}})
                return {**doc, "status": status}
            summary = {"items": 0, "created": 0, "updated": 0, "changed_at_source": 0, "closed": 0, "duplicates": 0, "flagged": 0, "skipped": 0}
            if status == "SUCCEEDED" or doc.get("dataset_id"):
                s = await settings()
                items = await apify("GET", f"/datasets/{doc['dataset_id']}/items",
                                    params={"clean": "true", "limit": s["max_items_per_run"] + 50, "format": "json"})
                srcs = await db.job_sources.find({"source_id": {"$in": doc["source_ids"]}}, {"_id": 0}).to_list(None)
                summary = await import_items(items if isinstance(items, list) else [], srcs, run_id)
            ok = status == "SUCCEEDED"
            await db.apify_runs.update_one({"run_id": run_id}, {"$set": {
                "status": status, "processed": True, "finalizing_until": None, "finished_at": run.get("finishedAt") or now_iso(),
                "cost_usd": cost, "summary": summary, "error": None if ok else f"Run ended with status {status}"}})
            src_upd = {"$set": {"last_checked_at": now_iso()}}
            if ok:
                src_upd["$set"].update({"last_success_at": now_iso(), "last_error": None, "failed_attempts": 0})
            else:
                src_upd["$set"]["last_error"] = f"Run {status}"
                src_upd["$inc"] = {"failed_attempts": 1}
            await db.job_sources.update_many({"source_id": {"$in": doc["source_ids"]}}, src_upd)
            if summary["created"] or summary["closed"]:
                sm_helpers["invalidate_jobs"]()
            return {**doc, "status": status, "summary": summary, "cost_usd": cost}
        except Exception as e:  # noqa: BLE001 - released for the next attempt (webhook, cron or admin refresh)
            logger.warning(f"apify finalize {run_id} failed: {e}")
            await db.apify_runs.update_one({"run_id": run_id}, {"$set": {"finalizing_until": None, "last_finalize_error": str(e)[:200]}})
            raise

    def run_cost(run: dict) -> float:
        """Pay-per-event Actors bill their events (platform usage is included); others bill platform usage."""
        counts = run.get("chargedEventCounts") or {}
        events = ((run.get("pricingInfo") or {}).get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
        if counts and events:
            return round(sum(float(n or 0) * float((events.get(k) or {}).get("eventPriceUsd") or 0) for k, n in counts.items()), 4)
        return round(float(run.get("usageTotalUsd") or 0), 4)

    def match_source(n: dict, srcs: List[dict]) -> dict:
        for x in srcs:
            token_ = re.sub(r"^https?://", "", x["url"].lower()).rstrip("/")
            slug = token_.rsplit("/", 1)[-1]
            if slug and (slug in n["board"] or x["name"].lower() in n["board"]):
                return x
        return srcs[0]

    async def import_items(items: List[dict], srcs: List[dict], run_id: str) -> dict:
        summary = {"items": len(items), "created": 0, "updated": 0, "changed_at_source": 0, "closed": 0, "duplicates": 0,
                   "flagged": 0, "skipped": 0}
        rows = [(it, normalise(it)) for it in items if isinstance(it, dict)]
        urls = [n["original_url"] for _, n in rows if n["original_url"]]
        keys = [n["dedupe_key"] for _, n in rows]
        by_url = {j["original_url"]: j for j in await db.jobs.find({"original_url": {"$in": urls}}, {
            "_id": 0, "job_id": 1, "original_url": 1, "review_status": 1, "content_hash": 1, "flags": 1}).to_list(None)}
        by_key = {j["dedupe_key"]: j for j in await db.jobs.find({"dedupe_key": {"$in": keys}}, {
            "_id": 0, "job_id": 1, "dedupe_key": 1, "original_url": 1}).to_list(None)}
        ops, logs, per_source = [], [], {}
        today = now().date().isoformat()
        seen_urls = set()
        for _, n in rows:
            src = match_source(n, srcs)
            if not n["title"] or not n["original_url"] or n["original_url"] in seen_urls:
                summary["skipped"] += 1
                logs.append({"action": "skipped", "reason": "repeated in run" if n["original_url"] in seen_urls else "missing title or link",
                             "source_id": src["source_id"], "title": n["title"], "original_url": n["original_url"]})
                continue
            seen_urls.add(n["original_url"])
            fields = {k: v for k, v in n.items() if k not in ("board", "closed_at_source", "flags", "content_hash")}
            ex = by_url.get(n["original_url"])
            if ex:
                upd: dict = {"$set": {"last_seen_at": now_iso(), "last_import_run": run_id}}
                if n["closed_at_source"]:
                    upd["$set"].update({"expiry_date": today, "closed_at_source": True})
                    upd["$addToSet"] = {"flags": "closed_at_source"}
                    summary["closed"] += 1
                    action = "closed"
                elif ex.get("content_hash") == n["content_hash"]:
                    action = "unchanged"
                elif ex.get("review_status") in ("new_import", "pending_review"):
                    # Not yet reviewed: refresh from the source.
                    upd["$set"].update({**{k: v for k, v in fields.items() if k != "original_url"}, "content_hash": n["content_hash"],
                                        "flags": sorted(set((ex.get("flags") or [])) | set(n["flags"]) - {"source_changed"})})
                    summary["updated"] += 1
                    action = "updated"
                else:
                    # Already reviewed: keep the admin's version, flag the change for review.
                    upd["$set"]["source_snapshot"] = {**fields, "seen_at": now_iso()}
                    upd["$addToSet"] = {"flags": "source_changed"}
                    summary["changed_at_source"] += 1
                    action = "changed_at_source"
                ops.append(UpdateOne({"job_id": ex["job_id"]}, upd))
                logs.append({"action": action, "job_id": ex["job_id"], "source_id": src["source_id"], "title": n["title"],
                             "original_url": n["original_url"]})
                continue
            if n["closed_at_source"]:
                summary["skipped"] += 1
                continue
            flags = list(n["flags"])
            dup = by_key.get(n["dedupe_key"])
            if dup:
                flags.append("possible_duplicate")
                summary["duplicates"] += 1
            if flags:
                summary["flagged"] += 1
            jid = f"job_{uuid.uuid4().hex[:10]}"
            doc = {**fields, "job_id": jid, "status": "Draft", "verification_status": "Pending Verification",
                   "review_status": "new_import", "flags": flags, "duplicate_of": dup["job_id"] if dup else None,
                   "content_hash": n["content_hash"], "source_id": src["source_id"], "source_name": src["name"],
                   "job_source": "Approved external job feed / API", "imported_via": "apify", "last_import_run": run_id,
                   "industry_category": src.get("category") or None, "industry": src.get("category") or "",
                   "featured": False, "views": 0, "saves": 0, "apply_clicks": 0, "date_added": now_iso(),
                   "date_received": today, "imported_at": now_iso(), "last_seen_at": now_iso(), "last_updated": now_iso(),
                   "date_published": None, "expiry_date": n["application_deadline"] or "", "verification_score": 0,
                   "admin_notes": "", "recruiter_name": "", "recruiter_email": "", "key_responsibilities": "",
                   "preferred_skills": "", "designation": n["title"]}
            ops.append(UpdateOne({"original_url": n["original_url"]}, {"$setOnInsert": doc}, upsert=True))
            by_key.setdefault(n["dedupe_key"], doc)
            summary["created"] += 1
            per_source[src["source_id"]] = per_source.get(src["source_id"], 0) + 1
            logs.append({"action": "created", "job_id": jid, "source_id": src["source_id"], "title": n["title"],
                         "original_url": n["original_url"], "flags": flags})
        for i in range(0, len(ops), 500):
            await db.jobs.bulk_write(ops[i:i + 500], ordered=False)
        if logs:
            await db.job_import_logs.insert_many([{**x, "run_id": run_id, "at": now_iso(), "at_dt": now()} for x in logs])
        for sid, n in per_source.items():
            await db.job_sources.update_one({"source_id": sid}, {"$inc": {"jobs_imported": n}})
        return summary

    # ------------------------------------------------------------------ candidate demand search
    async def demand_preview_data(s: Optional[dict] = None) -> dict:
        s = s or await settings()
        cands = await db.users.find({"role": "candidate", "suspended": {"$ne": True}}, {
            "_id": 0, "role": 1, "suspended": 1, "preferred_titles": 1, "preferred_designation": 1,
            "preferred_locations": 1, "preferred_location": 1}).to_list(50000)
        pairs = demand_pairs(cands, s["demand_max_pairs"], s["demand_min_candidates"])
        per = max(1, min(s["demand_jobs_per_pair"], s["max_items_per_run"] // max(1, len(pairs))))
        jobs = per * len(pairs)
        price = ACTOR_PRESETS[LINKEDIN_ACTOR]["price_per_item_usd"]
        return {"pairs": pairs, "jobs_per_pair": per, "max_jobs_per_run": jobs,
                "max_cost_per_run_usd": round(jobs * price, 3), "max_cost_per_month_usd": round(jobs * price * 30, 2),
                "candidates_considered": len(cands)}

    async def refresh_demand_source() -> Optional[dict]:
        """Rebuild the system-managed demand search from current candidate preferences (or switch it off)."""
        s = await settings()
        if not s["demand_search_enabled"]:
            await db.job_sources.update_one({"source_id": DEMAND_ID}, {"$set": {"enabled": False}})
            return None
        pv = await demand_preview_data(s)
        pairs = pv["pairs"]
        actor_in = {"startUrls": [linkedin_search_url(p["title"], p["city"], s["posted_within_days"]) for p in pairs],
                    "maxRowsPerUrl": pv["jobs_per_pair"], "companyProfile": False, "enrichCompany": False}
        await db.job_sources.update_one({"source_id": DEMAND_ID}, {"$set": {
            "name": "Candidate demand (automatic)", "url": "", "source_type": DEMAND_TYPE, "managed": True,
            "permission_status": "Approved", "permission_note": "Rebuilt daily from candidates' preferred job titles and cities",
            "enabled": bool(pairs), "frequency": "daily", "actor_id": LINKEDIN_ACTOR, "actor_input": actor_in,
            "demand_pairs": pairs, "keywords": [], "locations": [], "filters": {}, "demand_refreshed_at": now_iso()},
            "$setOnInsert": {"source_id": DEMAND_ID, "date_added": now_iso(), "added_by": "system", "category": None,
                             "last_checked_at": None, "last_success_at": None, "jobs_imported": 0, "failed_attempts": 0,
                             "last_error": None}}, upsert=True)
        return pv

    # ------------------------------------------------------------------ scheduling
    async def due_sources() -> List[dict]:
        out = []
        for x in await db.job_sources.find({"enabled": True, "permission_status": "Approved"}, {"_id": 0}).to_list(None):
            hours = FREQUENCY.get(x.get("frequency") or "daily")
            if hours is None:
                continue
            last = x.get("last_checked_at")
            if not last or datetime.fromisoformat(last) < now() - timedelta(hours=hours):
                out.append(x)
        return out

    async def daily_cycle():
        for doc in await db.apify_runs.find({"processed": False}, {"_id": 0, "run_id": 1}).to_list(50):
            try:
                await finalize(doc["run_id"])
            except Exception:  # noqa: BLE001 - logged in finalize; retried next cycle
                pass
        await sm_helpers["sweep_expired"](force=True)
        s = await settings()
        if not s["auto_daily"] or not s["paid_runs_approved"] or not token():
            return
        await refresh_demand_source()
        srcs = await due_sources()
        if srcs:
            try:
                await start_runs(srcs, "scheduled")
            except HTTPException as e:
                logger.warning(f"scheduled Apify collection skipped: {e.detail}")

    def check_secret(value: Optional[str], env: str):
        secret = os.environ.get(env) or ""
        if not secret or not value or not hmac.compare_digest(value, secret):
            raise HTTPException(401, "Unauthorized")

    @r.post("/cron/apify-daily")
    async def cron_daily(authorization: Optional[str] = Header(None)):
        check_secret(authorization[7:] if authorization and authorization.startswith("Bearer ") else None, "WEBHOOK_CRON_SECRET")
        # One collection cycle per calendar day, however many replicas or retries call this.
        key = f"apify-daily-{now().date().isoformat()}"
        res = await db.cron_runs.update_one({"run_id": key}, {"$setOnInsert": {"run_id": key, "name": "apify-daily",
                                                                               "created_at": now_iso()}}, upsert=True)
        if res.upserted_id is not None:
            bg(tracked("apify-daily", daily_cycle()))
        return {"accepted": True}

    async def poll_pending() -> int:
        """Import any finished runs. Covers deployments without the Apify webhook (no PUBLIC_BACKEND_URL) and
        webhooks that never arrived, so results land within one poll interval instead of the next day."""
        n = 0
        for doc in await db.apify_runs.find({"processed": False, "apify_run_id": {"$ne": None}},
                                            {"_id": 0, "run_id": 1}).to_list(20):
            try:
                res = await finalize(doc["run_id"])
                n += 1 if res and res.get("status") in FINAL_STATES else 0
            except Exception:  # noqa: BLE001 - logged in finalize; retried next poll
                pass
        return n

    @r.post("/cron/apify-poll")
    async def cron_poll(authorization: Optional[str] = Header(None)):
        check_secret(authorization[7:] if authorization and authorization.startswith("Bearer ") else None, "WEBHOOK_CRON_SECRET")
        if token() and await db.apify_runs.find_one({"processed": False, "apify_run_id": {"$ne": None}}, {"_id": 1}):
            bg(tracked("apify-poll", poll_pending()))
        return {"accepted": True}

    @r.post("/apify/webhook")
    async def webhook(request: Request, x_jobradar_webhook: Optional[str] = Header(None)):
        check_secret(x_jobradar_webhook, "APIFY_WEBHOOK_SECRET")
        try:
            body = await request.json()
        except Exception:
            body = {}
        apify_run_id = ((body or {}).get("resource") or {}).get("id") or ((body or {}).get("eventData") or {}).get("actorRunId")
        doc = await db.apify_runs.find_one({"apify_run_id": apify_run_id, "processed": False}, {"_id": 0, "run_id": 1}) if apify_run_id else None
        if doc:
            # The payload is only a hint: finalize re-reads the run from Apify's API.
            bg(finalize(doc["run_id"]))
        return {"accepted": bool(doc)}

    # ------------------------------------------------------------------ admin: settings, sources, runs
    def clean_list(v: List[str]) -> List[str]:
        return list(dict.fromkeys(x.strip()[:80] for x in v if x and x.strip()))[:20]

    def validate_source(req: SourceReq) -> dict:
        d = req.dict()
        search = d["source_type"] == SEARCH_TYPE
        if not d["name"].strip():
            raise HTTPException(400, "Name is required")
        if search:
            # No URL: the LinkedIn Actor searches for these titles in these locations.
            d.update(url="", actor_id=LINKEDIN_ACTOR, actor_input=None)
            if not clean_list(d["keywords"]) or not clean_list(d["locations"]):
                raise HTTPException(400, "A job search needs at least one job title and one location")
            filters = {}
            for k, vals in (d.get("filters") or {}).items():
                if k not in LI_FILTERS or any(v not in LI_FILTERS[k][1] for v in vals):
                    raise HTTPException(400, f"Unknown search filter: {k}")
                if vals:
                    filters[k] = sorted(set(vals))
            d["filters"] = filters
        else:
            d["filters"] = {}
            if not d["url"].strip():
                raise HTTPException(400, "Source URL is required")
            if not re.match(r"^https?://", d["url"].strip()):
                raise HTTPException(400, "Source URL must start with http:// or https://")
        if d["source_type"] not in SOURCE_TYPES:
            raise HTTPException(400, "Invalid source type")
        if d["permission_status"] not in PERMISSION:
            raise HTTPException(400, "Invalid permission status")
        if d["frequency"] not in FREQUENCY:
            raise HTTPException(400, "Frequency must be daily, weekly or manual")
        if d["enabled"] and d["permission_status"] != "Approved":
            raise HTTPException(400, "Only sources with permission status Approved can be enabled")
        if search:
            pass
        elif LINKEDIN_URL.match(d["url"].strip()):
            # LinkedIn URLs are collected with the LinkedIn Actor, whatever the global default Actor is.
            if d["actor_id"] and d["actor_id"] != LINKEDIN_ACTOR and not d["actor_input"]:
                raise HTTPException(400, f"LinkedIn sources are collected with {LINKEDIN_ACTOR}")
            d["actor_id"] = d["actor_id"] or LINKEDIN_ACTOR
        elif d["actor_id"] == LINKEDIN_ACTOR:
            d["actor_id"] = None  # the URL was changed away from LinkedIn: fall back to the default Actor
        if not LINKEDIN_URL.match(d["url"].strip()) and re.search(r"naukri\.com|indeed\.|glassdoor\.|monster\.|shine\.com|foundit\.", d["url"], re.I) \
                and d["source_type"] != "Licensed job data provider":
            raise HTTPException(400, "Job portals like Naukri and Indeed can't be collected without a licence or approved API. "
                                     "Add the employer's own careers page instead.")
        d.update(name=d["name"].strip()[:120], url=d["url"].strip()[:500], keywords=clean_list(d["keywords"]),
                 locations=clean_list(d["locations"]), permission_note=d["permission_note"][:500])
        return d

    @r.get("/admin/apify/overview")
    async def overview(admin=Depends(require_admin)):
        s = await settings()
        runs = await db.apify_runs.find({}, {"_id": 0, "finalizing_until": 0}).sort("started_at", -1).to_list(30)
        apify_usage = None
        if token():
            try:
                lim = await apify("GET", "/users/me/limits")
                apify_usage = {"month_usage_usd": (lim.get("current") or {}).get("monthlyUsageUsd"),
                               "month_limit_usd": (lim.get("limits") or {}).get("maxMonthlyUsageUsd"),
                               "cycle_end": (lim.get("monthlyUsageCycle") or {}).get("endAt")}
            except HTTPException as e:
                apify_usage = {"error": e.detail}
        totals = (await db.apify_runs.aggregate([{"$group": {"_id": None, "runs": {"$sum": 1},
                  "ok": {"$sum": {"$cond": [{"$eq": ["$status", "SUCCEEDED"]}, 1, 0]}},
                  "failed": {"$sum": {"$cond": [{"$in": ["$status", ["FAILED", "ABORTED", "TIMED-OUT"]]}, 1, 0]}},
                  "imported": {"$sum": {"$ifNull": ["$summary.created", 0]}},
                  "duplicates": {"$sum": {"$ifNull": ["$summary.duplicates", 0]}}}}]).to_list(1) or [{}])[0]
        return {"settings": s, "presets": ACTOR_PRESETS, "token_configured": bool(token()),
                "webhook_configured": bool(os.environ.get("APIFY_WEBHOOK_SECRET") and os.environ.get("PUBLIC_BACKEND_URL")),
                "month_spend_usd": await month_spend(), "apify_usage": apify_usage, "runs": runs,
                "totals": {k: v for k, v in totals.items() if k != "_id"},
                "options": {"source_types": SOURCE_TYPES, "permission": PERMISSION, "frequency": list(FREQUENCY),
                            "search_type": SEARCH_TYPE, "demand_type": DEMAND_TYPE,
                            "filters": {k: list(codes) for k, (_, codes) in LI_FILTERS.items()}}}

    @r.put("/admin/apify/settings")
    async def put_settings(req: SettingsReq, admin=Depends(require_admin)):
        d = req.dict()
        if not re.match(r"^[\w.-]+/[\w.-]+$", d["actor_id"]):
            raise HTTPException(400, "Actor must look like username/actor-name")
        if not 1 <= d["max_items_per_run"] <= 1000 or not 1 <= d["max_items_per_company"] <= 200:
            raise HTTPException(400, "Max items per run must be 1–1000 and per company 1–200")
        if not 0 <= d["monthly_budget_usd"] <= 500 or not 0.1 <= d["per_run_cap_usd"] <= 50:
            raise HTTPException(400, "Budget must be $0–500 a month and per-run cap $0.10–50")
        if not 1 <= d["demand_max_pairs"] <= 100 or not 1 <= d["demand_min_candidates"] <= 50 \
                or not 1 <= d["demand_jobs_per_pair"] <= 50:
            raise HTTPException(400, "Demand search: 1–100 searches, 1–50 candidates per search and 1–50 jobs per search")
        d["default_keywords"], d["default_locations"] = clean_list(d["default_keywords"]), clean_list(d["default_locations"])
        await db.app_settings.update_one({"key": "apify"}, {"$set": {"key": "apify", **d}}, upsert=True)
        await audit_log(admin, "update_apify_settings", "settings", "apify", d)
        await refresh_demand_source()
        return d

    @r.get("/admin/apify/demand-preview")
    async def demand_preview(admin=Depends(require_admin)):
        return await demand_preview_data()

    @r.get("/admin/sources")
    async def list_sources(admin=Depends(require_admin)):
        srcs = await db.job_sources.find({}, {"_id": 0}).sort("date_added", -1).to_list(500)
        counts = {d["_id"]: d for d in await db.jobs.aggregate([{"$match": {"source_id": {"$ne": None}}}, {"$group": {
            "_id": "$source_id", "total": {"$sum": 1},
            "awaiting": {"$sum": {"$cond": [{"$in": ["$review_status", ["new_import", "pending_review"]]}, 1, 0]}},
            "published": {"$sum": {"$cond": [{"$eq": ["$status", "Published"]}, 1, 0]}}}}]).to_list(None)}
        for x in srcs:
            c = counts.get(x["source_id"], {})
            x.update(jobs_total=c.get("total", 0), jobs_awaiting=c.get("awaiting", 0), jobs_published=c.get("published", 0))
        return {"sources": srcs}

    @r.post("/admin/sources")
    async def add_source(req: SourceReq, admin=Depends(require_admin)):
        d = validate_source(req)
        same = {"source_type": SEARCH_TYPE, "keywords": d["keywords"], "locations": d["locations"], "filters": d["filters"]} \
            if d["source_type"] == SEARCH_TYPE else {"url": d["url"]}
        if await db.job_sources.find_one(same):
            raise HTTPException(400, "This search has already been added" if d["source_type"] == SEARCH_TYPE
                                else "This source has already been added")
        d.update(source_id=f"src_{uuid.uuid4().hex[:10]}", date_added=now_iso(), added_by=admin.get("email"),
                 last_checked_at=None, last_success_at=None, jobs_imported=0, failed_attempts=0, last_error=None)
        await db.job_sources.insert_one(dict(d))
        await audit_log(admin, "add_job_source", "job_source", d["source_id"], {"name": d["name"], "url": d["url"]})
        d.pop("_id", None)
        return {"source": d}

    @r.put("/admin/sources/{sid}")
    async def edit_source(sid: str, req: SourceReq, admin=Depends(require_admin)):
        if sid == DEMAND_ID:
            raise HTTPException(400, "The candidate demand search is managed from its settings card")
        d = validate_source(req)
        res = await db.job_sources.update_one({"source_id": sid}, {"$set": {**d, "updated_at": now_iso()}})
        if not res.matched_count:
            raise HTTPException(404, "Source not found")
        await audit_log(admin, "edit_job_source", "job_source", sid, {"enabled": d["enabled"], "permission": d["permission_status"]})
        return {"ok": True}

    @r.post("/admin/sources/run")
    async def run_now(req: RunReq, admin=Depends(require_admin)):
        await refresh_demand_source()
        q: dict = {"enabled": True, "permission_status": "Approved"}
        if req.source_ids:
            q["source_id"] = {"$in": req.source_ids}
        srcs = await db.job_sources.find(q, {"_id": 0}).to_list(None)
        recent = (now() - timedelta(hours=1)).isoformat()
        srcs = [x for x in srcs if not x.get("last_checked_at") or x["last_checked_at"] < recent]
        if not srcs:
            raise HTTPException(409, "These sources were checked in the last hour (or none are enabled and approved).")
        started = await start_runs(srcs, "manual", admin)
        await audit_log(admin, "run_apify_collection", "job_source", ",".join(x["source_id"] for x in srcs)[:200],
                        {"runs": [x["run_id"] for x in started]})
        return {"runs": started}

    @r.post("/admin/apify/runs/{run_id}/refresh")
    async def refresh_run(run_id: str, admin=Depends(require_admin)):
        doc = await db.apify_runs.find_one({"run_id": run_id}, {"_id": 0, "finalizing_until": 0})
        if not doc:
            raise HTTPException(404, "Run not found")
        if doc.get("processed"):
            return {"run": doc}
        res = await finalize(run_id)
        return {"run": res or doc}

    # ------------------------------------------------------------------ admin: import review
    @r.get("/admin/imports")
    async def list_imports(review_status: str = "new_import", source_id: str = "", flag: str = "", q: str = "",
                           industry: str = "", location: str = "", page: int = 1, admin=Depends(require_admin)):
        query: dict = {"imported_via": "apify"}
        if review_status and review_status != "All":
            query["review_status"] = {"$in": ["new_import", "pending_review"]} if review_status == "awaiting" else review_status
        if source_id:
            query["source_id"] = source_id
        if flag:
            query["flags"] = flag
        if industry and industry != "All":
            query["industry_category"] = industry
        if location:
            query["location"] = {"$regex": re.escape(location), "$options": "i"}
        if q:
            rx = {"$regex": re.escape(q), "$options": "i"}
            query["$or"] = [{"title": rx}, {"company": rx}]
        total = await db.jobs.count_documents(query)
        rows = await db.jobs.find(query, {"_id": 0, "description": 0, "source_snapshot": 0}).sort("imported_at", -1).skip(
            (max(page, 1) - 1) * 25).limit(25).to_list(25)
        counts = {d["_id"]: d["n"] for d in await db.jobs.aggregate([{"$match": {"imported_via": "apify"}},
                  {"$group": {"_id": "$review_status", "n": {"$sum": 1}}}]).to_list(None)}
        return {"jobs": rows, "total": total, "page": page, "counts": counts}

    @r.get("/admin/imports/{job_id}")
    async def import_detail(job_id: str, admin=Depends(require_admin)):
        job = await db.jobs.find_one({"job_id": job_id, "imported_via": "apify"}, {"_id": 0})
        if not job:
            raise HTTPException(404, "Imported job not found")
        history = await db.job_import_logs.find({"$or": [{"job_id": job_id}, {"original_url": job.get("original_url")}]},
                                                {"_id": 0, "at_dt": 0}).sort("at", -1).to_list(50)
        dup = await db.jobs.find_one({"job_id": job.get("duplicate_of")}, {"_id": 0, "job_id": 1, "title": 1, "company": 1,
                                                                            "status": 1, "original_url": 1}) if job.get("duplicate_of") else None
        return {"job": job, "history": history, "duplicate_of": dup}

    @r.post("/admin/imports/action")
    async def review_action(req: ReviewReq, admin=Depends(require_admin)):
        if req.action not in ("approve", "publish", "reject", "archive", "pending_review", "accept_source_change"):
            raise HTTPException(400, "Unknown action")
        if not 1 <= len(req.job_ids) <= 100:
            raise HTTPException(400, "Select between 1 and 100 jobs")
        jobs = await db.jobs.find({"job_id": {"$in": req.job_ids}, "imported_via": "apify"}, {"_id": 0}).to_list(None)
        today = now().date().isoformat()
        done, skipped = [], []
        for j in jobs:
            s: dict = {"last_updated": now_iso(), "reviewed_by": admin.get("email"), "reviewed_at": now_iso()}
            unset: dict = {}
            if req.action in ("approve", "publish"):
                if j.get("expiry_date") and j["expiry_date"] < today or "closed_at_source" in (j.get("flags") or []):
                    skipped.append({"job_id": j["job_id"], "reason": "expired or closed at source"})
                    continue
                cat = req.industry_category or j.get("industry_category")
                if req.action == "publish" and not cat:
                    skipped.append({"job_id": j["job_id"], "reason": "set an industry before publishing"})
                    continue
                s.update(verification_status="Verified", review_status="approved", verified_by=admin["user_id"], verified_at=now_iso())
                if cat:
                    s.update(industry_category=cat, industry=j.get("industry") or cat)
                if req.action == "publish":
                    s.update(status="Published", date_published=j.get("date_published") or now_iso())
            elif req.action == "reject":
                s.update(verification_status="Rejected", review_status="rejected", status="Draft")
            elif req.action == "archive":
                s.update(review_status="archived", status="Archived")
            elif req.action == "pending_review":
                s.update(review_status="pending_review")
            elif req.action == "accept_source_change":
                snap = j.get("source_snapshot")
                if not snap:
                    skipped.append({"job_id": j["job_id"], "reason": "no source change recorded"})
                    continue
                s.update({k: v for k, v in snap.items() if k not in ("seen_at", "original_url")})
                s["flags"] = [f for f in (j.get("flags") or []) if f != "source_changed"]
                unset["source_snapshot"] = ""
            upd = {"$set": s}
            if unset:
                upd["$unset"] = unset
            await db.jobs.update_one({"job_id": j["job_id"]}, upd)
            done.append(j["job_id"])
        if done:
            sm_helpers["invalidate_jobs"]()
            for jid in done:
                await sm_helpers["job_changed"](jid, f"import {req.action}")
            await audit_log(admin, f"import_{req.action}", "job", ",".join(done)[:200], {"count": len(done)})
        return {"done": done, "skipped": skipped}

    return r, {"daily_cycle": daily_cycle, "poll_pending": poll_pending}
