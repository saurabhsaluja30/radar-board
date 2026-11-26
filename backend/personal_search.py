"""Candidate "Find jobs for me": a live LinkedIn search for one candidate, at most once a day.

- Database first: when the candidate already has enough good matches among published jobs, no search runs.
- One search a day per candidate (IST days). The claim is atomic, so repeated clicks, tabs or scripts can't start a
  second one; a search stuck for 10 minutes is released, and a failed or empty search gives the day back.
- Each search is one title in one city at the candidate's seniority, rotating through their preferences day by day.
  Candidates who want the same title, city and seniority on the same day share one Apify run.
- Free candidates get up to `personal_free_jobs` new jobs, members up to `personal_paid_jobs`. Jobs a candidate has
  already been given don't count again. An admin-set daily spending cap pauses live searches for everyone.
- Found jobs are imported like any Apify job (Draft, into the admin review queue) and shown to the candidate who
  searched for them through `personal_results`.
"""
import hashlib
import json
import logging
import re
import uuid
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from apify_jobs import LINKEDIN_ACTOR, PERSONAL_TYPE, linkedin_levels
from smartmatch import candidate_lists

logger = logging.getLogger("jobradar.personal_search")

IST = timezone(timedelta(hours=5, minutes=30))
STALE = timedelta(minutes=10)
ROWS = 10  # one shared search fetches enough for a member; free candidates get the top few


# --------------------------------------------------------------------------- pure helpers
def ist_day(t: datetime) -> str:
    return t.astimezone(IST).date().isoformat()


def day_start_utc(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), dtime.min, tzinfo=IST).astimezone(timezone.utc)


def next_reset_utc(t: datetime) -> datetime:
    return day_start_utc(ist_day(t)) + timedelta(days=1)


def years_of(v) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"\d+(?:\.\d+)?", str(v or ""))
    return float(m.group(0)) if m else None


def _dedupe(xs: List[str]) -> List[str]:
    seen, out = set(), []
    for x in xs:
        k = " ".join(str(x).lower().split())
        if k and k not in seen and k not in ("any", "anywhere", "open"):
            seen.add(k)
            out.append(" ".join(str(x).split())[:80])
    return out


def pick_pair(titles: List[str], cities: List[str], day: str) -> Tuple[str, str]:
    """Rotate through every title × city, one per day."""
    pairs = [(t, c) for t in titles for c in cities]
    return pairs[date.fromisoformat(day).toordinal() % len(pairs)]


def pair_key(title: str, city: str, levels: List[str]) -> str:
    return hashlib.sha1(json.dumps([title.lower(), city.lower(), sorted(levels)]).encode()).hexdigest()[:20]


# --------------------------------------------------------------------------- router
def build_router(db, get_current_user, compute_membership, serialize_job, now_iso, sm_helpers, apify_helpers):
    r = APIRouter()
    settings = apify_helpers["settings"]

    def now() -> datetime:
        return datetime.now(timezone.utc)

    def require_candidate(user):
        if user.get("role") != "candidate":
            raise HTTPException(403, "Only candidates can search for jobs")

    async def limit_for(uid: str, s: dict) -> int:
        m = await compute_membership(uid)
        return s["personal_paid_jobs"] if m.get("is_active") else s["personal_free_jobs"]

    async def spent_today(day: str) -> float:
        agg = await db.apify_runs.aggregate([
            {"$match": {"trigger": "personal", "started_at": {"$gte": day_start_utc(day).isoformat()}}},
            {"$group": {"_id": None, "usd": {"$sum": {"$ifNull": ["$cost_usd", "$cost_cap_usd"]}}}}]).to_list(1)
        return round(agg[0]["usd"], 4) if agg else 0.0

    async def release(uids: List[str], day: str, search_id: Optional[str] = None, reason: str = ""):
        """Give the day back: a failed, stuck or empty search doesn't count."""
        q: dict = {"user_id": {"$in": uids}, "day": day, "status": "running"}
        if search_id:
            q["search_id"] = search_id
        await db.personal_quota.update_many(q, {"$set": {"status": "free", "released_reason": reason[:200],
                                                         "updated_at": now_iso()}})

    async def deliver(search: dict, uids: List[str]):
        """Give each waiting candidate their share of a finished search."""
        s = await settings()
        job_ids = search.get("job_ids") or []
        for uid in uids:
            quota = await db.personal_quota.find_one({"user_id": uid, "day": search["day"]}, {"_id": 0})
            # Only candidates still waiting on this search (not released as stale, not already served).
            if not quota or quota.get("status") != "running" or quota.get("search_id") != search["search_id"]:
                continue
            user = await db.users.find_one({"user_id": uid}, {"_id": 0, "password": 0})
            if not user:
                continue
            seen = set(await db.personal_results.distinct("job_id", {"user_id": uid}))
            jobs = await db.jobs.find({"job_id": {"$in": [j for j in job_ids if j not in seen]}},
                                      {"_id": 0, "admin_notes": 0}).to_list(None)
            ranked = []
            for j in jobs:
                try:
                    score = await sm_helpers["score_job"](user, j)
                except Exception:  # noqa: BLE001 - an unscoreable job still counts, just ranked last
                    score = 0
                ranked.append((score, j))
            ranked.sort(key=lambda x: -x[0])
            picked = ranked[:await limit_for(uid, s)]
            if not picked:
                await release([uid], search["day"], search["search_id"], "no new jobs")
                continue
            at = now_iso()
            try:
                await db.personal_results.insert_many([{"user_id": uid, "job_id": j["job_id"], "search_id": search["search_id"],
                                                        "score": sc, "delivered_at": at} for sc, j in picked], ordered=False)
            except Exception:  # noqa: BLE001 - duplicates from a concurrent delivery are fine
                pass
            n = len(picked)
            await db.job_notifications.insert_one({
                "notification_id": f"nt_{uuid.uuid4().hex[:12]}", "candidate_id": uid, "job_id": picked[0][1]["job_id"],
                "channel": "in_app", "status": "sent", "source": "personal_search", "match_id": None,
                "subject": f"We found {n} new job{'s' if n != 1 else ''} for you",
                "body": f"{search['title']} in {search['city']}: {n} new job{'s' if n != 1 else ''} picked for your profile.",
                "sent_at": at, "read_at": None, "created_at": at, "updated_at": at, "attempts": 1})
            await db.personal_quota.update_one({"user_id": uid, "day": search["day"], "search_id": search["search_id"]},
                                               {"$set": {"status": "done", "delivered": n, "done_at": at}})

    async def on_run_finished(run: dict, summary: dict):
        if run.get("trigger") != "personal":
            return
        search = await db.personal_searches.find_one({"run_id": run["run_id"]}, {"_id": 0})
        if not search or search.get("status") == "done":
            return
        if run.get("status") != "SUCCEEDED":
            await db.personal_searches.update_one({"search_id": search["search_id"]}, {"$set": {"status": "failed"}})
            await release(search.get("waiters") or [], search["day"], search["search_id"], f"run {run.get('status')}")
            return
        logs = await db.job_import_logs.find({"run_id": run["run_id"], "job_id": {"$ne": None},
                                              "action": {"$in": ["created", "updated", "unchanged", "changed_at_source"]}},
                                             {"_id": 0, "job_id": 1}).to_list(None)
        job_ids = list(dict.fromkeys(x["job_id"] for x in logs if x.get("job_id")))
        search = await db.personal_searches.find_one_and_update(
            {"search_id": search["search_id"]}, {"$set": {"status": "done", "job_ids": job_ids, "done_at": now_iso()}},
            projection={"_id": 0}, return_document=ReturnDocument.AFTER)
        await deliver(search, search.get("waiters") or [])

    apify_helpers["after_finalize"].append(on_run_finished)

    async def status_payload(user: dict, s: Optional[dict] = None) -> dict:
        s = s or await settings()
        uid, t = user["user_id"], now()
        day = ist_day(t)
        quota = await db.personal_quota.find_one({"user_id": uid, "day": day}, {"_id": 0}) or {}
        status = quota.get("status") or "free"
        if status == "running" and quota.get("started_at", "") < (t - STALE).isoformat():
            status = "free"  # stuck: the next click may start again
        m = await compute_membership(uid)
        rows = await db.personal_results.find({"user_id": uid}, {"_id": 0}).sort("delivered_at", -1).to_list(30)
        jobs = {j["job_id"]: j for j in await db.jobs.find({"job_id": {"$in": [x["job_id"] for x in rows]}},
                                                          {"_id": 0, "admin_notes": 0, "verification_score": 0}).to_list(None)}
        search = await db.personal_searches.find_one({"search_id": quota.get("search_id")},
                                                     {"_id": 0, "title": 1, "city": 1}) if quota.get("search_id") else None
        return {"enabled": bool(s["personal_search_enabled"]), "status": status, "delivered_today": quota.get("delivered", 0),
                "limit": s["personal_paid_jobs"] if m.get("is_active") else s["personal_free_jobs"],
                "is_member": bool(m.get("is_active")), "next_reset_at": next_reset_utc(t).isoformat(),
                "searching_for": search, "started_at": quota.get("started_at") if status == "running" else None,
                "jobs": [{**serialize_job(jobs[x["job_id"]], bool(m.get("is_active"))), "found_at": x["delivered_at"],
                          "match_score": x.get("score")} for x in rows if x["job_id"] in jobs]}

    @r.get("/me/job-search")
    async def my_search(user=Depends(get_current_user)):
        require_candidate(user)
        return await status_payload(user)

    @r.post("/me/job-search")
    async def find_jobs(user=Depends(get_current_user)):
        require_candidate(user)
        s = await settings()
        if not s["personal_search_enabled"] or not s["paid_runs_approved"] or not apify_helpers["token"]():
            raise HTTPException(503, "Job search isn't available right now. Your matches below are still updated daily.")
        uid, t = user["user_id"], now()
        day = ist_day(t)
        titles, cities = candidate_lists(user)
        titles, cities = _dedupe(titles), _dedupe(cities)
        if not titles or not cities:
            raise HTTPException(400, "Add your CV or your preferred job titles and cities first.")
        n = await sm_helpers["relevant_count"](user)
        if n >= s["personal_db_threshold"]:
            return {"mode": "database", "matches": n, **await status_payload(user, s)}

        # Claim today's search. The unique (user_id, day) index makes this atomic: a running or finished search
        # makes the upsert collide, and the caller just gets the current status.
        try:
            await db.personal_quota.find_one_and_update(
                {"user_id": uid, "day": day, "$or": [{"status": "free"},
                                                     {"status": "running", "started_at": {"$lt": (t - STALE).isoformat()}}]},
                {"$set": {"status": "running", "started_at": t.isoformat(), "search_id": None, "delivered": 0},
                 "$inc": {"attempts": 1}}, upsert=True)
        except DuplicateKeyError:
            return {"mode": "already", **await status_payload(user, s)}

        try:
            if await spent_today(day) >= s["personal_daily_cap_usd"]:
                raise HTTPException(429, "Live job search is paused for today. Try again tomorrow.")
            title, city = pick_pair(titles, cities, day)
            years = years_of(user.get("total_experience"))
            levels = linkedin_levels(int(years)) if years is not None else []
            key = pair_key(title, city, levels)
            search = await db.personal_searches.find_one({"day": day, "pair_key": key}, {"_id": 0})
            fresh = search and (search["status"] == "done" or
                                (search["status"] in ("starting", "running") and search.get("created_at", "") >= (t - STALE).isoformat()))
            if fresh:
                await db.personal_searches.update_one({"search_id": search["search_id"]}, {"$addToSet": {"waiters": uid}})
                await db.personal_quota.update_one({"user_id": uid, "day": day}, {"$set": {"search_id": search["search_id"]}})
                if search["status"] == "done":  # someone searched this today: no new Apify cost
                    await deliver(search, [uid])
                return {"mode": "shared", **await status_payload(user, s)}

            search_id = f"ps_{uuid.uuid4().hex[:12]}"
            doc = {"search_id": search_id, "day": day, "pair_key": key, "title": title, "city": city, "levels": levels,
                   "status": "starting", "waiters": [uid], "job_ids": [], "run_id": None, "created_at": t.isoformat()}
            if search:  # an earlier attempt today failed or got stuck: start over
                await db.personal_searches.update_one({"search_id": search["search_id"]}, {"$set": doc})
                search_id = doc["search_id"]
            else:
                try:
                    await db.personal_searches.insert_one(dict(doc))
                except DuplicateKeyError:  # another candidate started the same search a moment ago
                    other = await db.personal_searches.find_one({"day": day, "pair_key": key}, {"_id": 0})
                    await db.personal_searches.update_one({"search_id": other["search_id"]}, {"$addToSet": {"waiters": uid}})
                    await db.personal_quota.update_one({"user_id": uid, "day": day}, {"$set": {"search_id": other["search_id"]}})
                    return {"mode": "shared", **await status_payload(user, s)}
            await db.personal_quota.update_one({"user_id": uid, "day": day}, {"$set": {"search_id": search_id}})

            src_id = f"src_ps_{key[:12]}"
            src = {"source_id": src_id, "name": f"Personal: {title} · {city}"[:120], "url": "", "source_type": PERSONAL_TYPE,
                   "hidden": True, "permission_status": "Approved", "enabled": False, "frequency": "manual",
                   "keywords": [title], "locations": [city], "filters": {}, "actor_id": LINKEDIN_ACTOR, "actor_input": None,
                   "experience_years": int(years) if years is not None else None, "max_items": ROWS, "category": None}
            await db.job_sources.update_one({"source_id": src_id}, {"$set": src, "$setOnInsert": {
                "date_added": now_iso(), "added_by": "system", "last_checked_at": None, "last_success_at": None,
                "jobs_imported": 0, "failed_attempts": 0, "last_error": None}}, upsert=True)
            remaining = round(s["personal_daily_cap_usd"] - await spent_today(day), 2)
            try:
                started = await apify_helpers["start_runs"]([src], "personal", None, parallel=True,
                                                            cap_usd=max(0.01, min(0.05, remaining)))
            except HTTPException as e:
                await db.personal_searches.update_one({"search_id": search_id}, {"$set": {"status": "failed", "error": e.detail}})
                waiters = (await db.personal_searches.find_one({"search_id": search_id}, {"waiters": 1}) or {}).get("waiters") or [uid]
                await release(waiters, day, search_id, str(e.detail))
                raise
            await db.personal_searches.update_one({"search_id": search_id},
                                                  {"$set": {"status": "running", "run_id": started[0]["run_id"]}})
            return {"mode": "started", **await status_payload(user, s)}
        except HTTPException:
            await release([uid], day, reason="not started")
            raise

    return r
