import csv
import io
import re
from collections import Counter
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from tracker import _range

INDUSTRIES = ["HR & Recruitment", "Travel & Hospitality", "IT & Technology", "Finance & Accounting", "BPO / Customer Experience"]
NS = "Not Specified"
COUNTRY_WORDS = [
    ("India", r"\bindia\b|bengaluru|bangalore|mumbai|delhi|ncr|gurgaon|gurugram|noida|pune|hyderabad|chennai|kolkata|ahmedabad|jaipur|kochi|chandigarh|indore|lucknow"),
    ("UAE", r"\buae\b|dubai|abu dhabi|sharjah|emirates"), ("Saudi Arabia", r"saudi|riyadh|jeddah"), ("Qatar", r"qatar|doha"),
    ("Singapore", r"singapore"), ("United Kingdom", r"\buk\b|united kingdom|england|london|manchester"),
    ("USA", r"\busa\b|\bus\b|united states|america|new york|california|texas"), ("Canada", r"canada|toronto|vancouver"),
    ("Australia", r"australia|sydney|melbourne"), ("Germany", r"germany|berlin|munich"),
    ("Anywhere / Open", r"anywhere|any location|\bany\b|open to relocate|remote"),
]


def country_of(loc: Optional[str]) -> str:
    s = (loc or "").strip().lower()
    if not s:
        return NS
    for name, pat in COUNTRY_WORDS:
        if re.search(pat, s):
            return name
    return "Other"


def bucket(v) -> str:
    v = (v or "").strip()
    return v if v in INDUSTRIES or v == NS else (NS if not v else "Other")


def norm(v) -> str:
    v = (v or "").strip() if isinstance(v, str) else v
    return v or NS


def build_router(db, require_admin, compute_memberships, now_utc):
    r = APIRouter()

    async def enriched():
        users = await db.users.find({"role": "candidate"}, {"_id": 0, "password": 0}).to_list(50000)
        paid_ids = set(await db.payments.distinct("candidate_id", {"status": "successful"}))
        out = []
        ms = await compute_memberships([u["user_id"] for u in users])
        for u in users:
            m = ms[u["user_id"]]
            out.append({
                **u, "industry": bucket(u.get("industry")), "industry_raw": norm(u.get("industry")),
                "preferred_industries": sorted({bucket(i) for i in (u.get("preferred_industries") or []) if i}) or [NS],
                "preferred_designation": norm(u.get("preferred_designation")),
                "current_designation": norm(u.get("current_designation")),
                "experience": norm(u.get("preferred_experience")),
                "location": norm(u.get("preferred_location")),
                "country": country_of(u.get("preferred_location")),
                "work_mode": norm(u.get("preferred_work_mode")),
                "membership_type": "Paid" if u["user_id"] in paid_ids else "Free",
                "sub_status": "Active" if m["is_active"] else ("Expired" if m["status"] == "expired" else "None"),
                "membership_status": m["status"], "plan_name": m.get("plan_name"), "expiry_date": m.get("expiry_date"),
            })
        return out

    def apply_filters(cands, f: dict):
        def ok(c):
            if f.get("industry") and f["industry"] != "All":
                if f.get("dimension") == "preferred":
                    if f["industry"] not in c["preferred_industries"]:
                        return False
                elif c["industry"] != f["industry"]:
                    return False
            for key, field in (("designation", "preferred_designation"), ("location", "location")):
                if f.get(key) and f[key].strip().lower() not in c[field].lower():
                    return False
            for key, field in (("experience", "experience"), ("country", "country"), ("work_mode", "work_mode"),
                               ("membership", "membership_type"), ("sub_status", "sub_status")):
                if f.get(key) and f[key] != "All" and c[field] != f[key]:
                    return False
            return True
        return [c for c in cands if ok(c)]

    def dist(cands, field, top=15):
        total = len(cands) or 1
        return [{"name": k, "count": v, "pct": round(v * 100 / total, 1)} for k, v in Counter(c[field] for c in cands).most_common(top)]

    def in_range(c, rng):
        ca = c.get("created_at") or ""
        return (not rng.get("$gte") or ca >= rng["$gte"]) and (not rng.get("$lt") or ca < rng["$lt"])

    def industry_report(cands, rng, preferred):
        total = len(cands) or 1
        names = INDUSTRIES + ["Other", NS]
        rows = []
        for name in names:
            members = [c for c in cands if (name in c["preferred_industries"] if preferred else c["industry"] == name)]
            if not members and name in ("Other", NS):
                continue
            rows.append({"name": name, "count": len(members), "pct": round(len(members) * 100 / total, 1),
                         "new_in_range": sum(1 for c in members if in_range(c, rng)),
                         "paid": sum(1 for c in members if c["membership_type"] == "Paid"),
                         "free": sum(1 for c in members if c["membership_type"] == "Free")})
        return rows

    def filters_from(**kw):
        return {k: v for k, v in kw.items() if v}

    @r.get("/admin/analytics/registration")
    async def registration(admin=Depends(require_admin), start: Optional[str] = None, end: Optional[str] = None):
        cands = await enriched()
        rng = _range(start, end)
        week = (now_utc() - timedelta(days=7)).isoformat()
        return {
            "total_registered": len(cands),
            "free_registered": sum(1 for c in cands if c["membership_type"] == "Free"),
            "paid": sum(1 for c in cands if c["membership_type"] == "Paid"),
            "active_subscriptions": sum(1 for c in cands if c["sub_status"] == "Active"),
            "expired_subscriptions": sum(1 for c in cands if c["sub_status"] == "Expired"),
            "new_last_7_days": sum(1 for c in cands if (c.get("created_at") or "") >= week),
            "new_in_range": sum(1 for c in cands if in_range(c, rng)) if rng else None,
            "paid_includes_demo": await db.payments.count_documents({"status": "successful", "is_demo": True}) > 0,
        }

    @r.get("/admin/analytics/demand")
    async def demand(admin=Depends(require_admin), start: Optional[str] = None, end: Optional[str] = None,
                     industry: Optional[str] = None, designation: Optional[str] = None, experience: Optional[str] = None,
                     location: Optional[str] = None, country: Optional[str] = None, work_mode: Optional[str] = None,
                     membership: Optional[str] = None, sub_status: Optional[str] = None, dimension: Optional[str] = None):
        everyone = await enriched()
        rng = _range(start, end)
        cands = apply_filters(everyone, filters_from(industry=industry, designation=designation, experience=experience,
                                                     location=location, country=country, work_mode=work_mode,
                                                     membership=membership, sub_status=sub_status, dimension=dimension))
        current = industry_report(cands, rng, False)
        preferred = industry_report(cands, rng, True)
        published = Counter(j.get("industry_category") or NS for j in await db.jobs.find({"status": "Published"}, {"_id": 0, "industry_category": 1}).to_list(10000))
        recs = []
        for row in preferred:
            if row["name"] not in INDUSTRIES:
                continue
            level = "High" if row["pct"] >= 25 else "Moderate" if row["pct"] >= 10 else "Low"
            jobs = published.get(row["name"], 0)
            recs.append({"industry": row["name"], "preferred_candidates": row["count"], "pct": row["pct"], "level": level,
                         "published_jobs": jobs, "candidates_per_job": round(row["count"] / jobs, 1) if jobs else None})
        recs.sort(key=lambda x: -x["preferred_candidates"])
        options = {k: sorted({c[f] for c in everyone}) for k, f in (("experience", "experience"), ("country", "country"), ("work_mode", "work_mode"))}
        return {
            "total_candidates": len(cands), "new_in_range": sum(1 for c in cands if in_range(c, rng)),
            "with_preference": sum(1 for c in cands if c["preferred_industries"] != [NS]),
            "current_industry": current, "preferred_industry": preferred,
            "current_designation": dist(cands, "current_designation"), "preferred_designation": dist(cands, "preferred_designation"),
            "experience": dist(cands, "experience"), "location": dist(cands, "location"), "country": dist(cands, "country"),
            "work_mode": dist(cands, "work_mode"), "recommendations": recs, "options": options,
        }

    def list_rows(cands):
        return [{k: c.get(k) for k in ("user_id", "full_name", "email", "mobile", "industry", "industry_raw", "preferred_industries",
                                       "current_designation", "preferred_designation", "experience", "location", "country",
                                       "work_mode", "membership_type", "sub_status", "plan_name", "expiry_date", "created_at")}
                for c in sorted(cands, key=lambda c: c.get("created_at") or "", reverse=True)]

    async def candidates_for(**kw):
        cands = apply_filters(await enriched(), filters_from(**{k: v for k, v in kw.items() if k not in ("start", "end")}))
        rng = _range(kw.get("start"), kw.get("end"))
        return [c for c in cands if in_range(c, rng)] if rng else cands

    @r.get("/admin/analytics/candidates")
    async def demand_candidates(admin=Depends(require_admin), start: Optional[str] = None, end: Optional[str] = None,
                                industry: Optional[str] = None, designation: Optional[str] = None, experience: Optional[str] = None,
                                location: Optional[str] = None, country: Optional[str] = None, work_mode: Optional[str] = None,
                                membership: Optional[str] = None, sub_status: Optional[str] = None, dimension: Optional[str] = None):
        rows = list_rows(await candidates_for(start=start, end=end, industry=industry, designation=designation, experience=experience,
                                              location=location, country=country, work_mode=work_mode, membership=membership,
                                              sub_status=sub_status, dimension=dimension))
        return {"candidates": rows[:500], "total": len(rows)}

    @r.get("/admin/analytics/candidates/export")
    async def demand_export(admin=Depends(require_admin), start: Optional[str] = None, end: Optional[str] = None,
                            industry: Optional[str] = None, designation: Optional[str] = None, experience: Optional[str] = None,
                            location: Optional[str] = None, country: Optional[str] = None, work_mode: Optional[str] = None,
                            membership: Optional[str] = None, sub_status: Optional[str] = None, dimension: Optional[str] = None):
        rows = list_rows(await candidates_for(start=start, end=end, industry=industry, designation=designation, experience=experience,
                                              location=location, country=country, work_mode=work_mode, membership=membership,
                                              sub_status=sub_status, dimension=dimension))
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Name", "Email", "Mobile", "Current Industry", "Preferred Industries", "Current Designation",
                    "Preferred Designation", "Experience", "Preferred Location", "Preferred Country", "Work Mode",
                    "Membership", "Subscription", "Plan", "Expiry", "Registered On"])
        for c in rows:
            w.writerow([c["full_name"], c["email"], c["mobile"], c["industry_raw"], "; ".join(c["preferred_industries"]),
                        c["current_designation"], c["preferred_designation"], c["experience"], c["location"], c["country"],
                        c["work_mode"], c["membership_type"], c["sub_status"], c["plan_name"] or "", (c["expiry_date"] or "")[:10],
                        (c["created_at"] or "")[:10]])
        return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="jobradar-candidates.csv"', "Cache-Control": "no-store"})

    return r
