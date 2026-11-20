"""Phase 6 – platform analytics, background-processing status and Starter resource monitoring.

Everything here is read-only for the admin and cheap to run on Starter hosting:
- analytics are counted on the database with aggregations, never by loading every record;
- each replica keeps its own request timings in a small in-memory ring and writes one resource sample
  every 15 minutes (on the back of normal traffic, so there is no extra scheduler);
- storage totals are snapshotted once per UTC day (shared across replicas through cron_runs);
- cron-triggered jobs record how long they took and whether they failed in `job_log` (kept 30 days).
"""
import asyncio
import calendar
import os
import resource
import socket
import sys
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends

from tracker import _range

REPLICA = os.environ.get("HOSTNAME") or socket.gethostname()
SAMPLE_EVERY_S = 900
SLOW_MS = 2000
KEEP_DAYS = 30
# Emergent Starter tier, from the platform brief.
STARTER = {"cpu_guaranteed": 0.05, "cpu_burst": 0.25, "mem_guaranteed_mb": 200, "mem_burst_mb": 512}
# Rough rupee figure for the Apify spend card. Override with USD_INR_RATE; it is shown as an estimate.
USD_INR = float(os.environ.get("USD_INR_RATE") or 88)

# How often each scheduled job is expected to run, in minutes (None = only when an admin or event triggers it).
SCHEDULES = {
    "tracker-reminders": ("Daily at 9:30 AM IST", 24 * 60),
    "email-retry": ("Every 15 minutes", 15),
    "apify-daily": ("Once a day", 24 * 60),
    "resume-retry": ("Hourly (recommended)", 60),
    "smartmatch-queue": ("Optional – SmartMatch is event-driven", None),
}

_db = None
_lat: deque = deque(maxlen=3000)  # (monotonic time, ms, route, status)
_state: Dict[str, Any] = {"cpu": time.process_time(), "wall": time.monotonic(), "last_sample": 0.0,
                          "started": time.time(), "sampling": False}
_tasks: set = set()


def init(db) -> None:
    global _db
    _db = db


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------- resource readings (stdlib only)
def _read(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def memory_mb() -> Dict[str, Any]:
    """Current resident memory of this process. Linux (production) reads /proc; elsewhere only the peak is available."""
    status = _read("/proc/self/status")
    if status:
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                return {"rss_mb": round(int(line.split()[1]) / 1024, 1), "kind": "current"}
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {"rss_mb": round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1), "kind": "peak"}


def container_limits() -> Dict[str, Optional[float]]:
    mem = _read("/sys/fs/cgroup/memory.max") or _read("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    mem_mb = round(int(mem) / 1048576) if mem and mem.isdigit() and int(mem) < 1 << 50 else None
    cpu = None
    quota = _read("/sys/fs/cgroup/cpu.max")
    if quota and not quota.startswith("max"):
        q, p = quota.split()[:2]
        cpu = round(int(q) / int(p), 3)
    else:
        q, p = _read("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _read("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        if q and p and q.lstrip("-").isdigit() and int(q) > 0:
            cpu = round(int(q) / int(p), 3)
    return {"mem_limit_mb": mem_mb, "cpu_limit": cpu}


def _pct(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    return round(s[min(len(s) - 1, int(len(s) * p))], 1)


def request_stats(since: float) -> Dict[str, Any]:
    rows = [r for r in list(_lat) if r[0] >= since]
    ms = [r[1] for r in rows]
    by_route: Dict[str, List[float]] = {}
    for _, d, route, _s in rows:
        by_route.setdefault(route, []).append(d)
    slow = sorted(({"route": k, "count": len(v), "p95_ms": _pct(v, 0.95), "max_ms": round(max(v), 1)}
                   for k, v in by_route.items()), key=lambda x: -(x["p95_ms"] or 0))[:6]
    return {"requests": len(rows), "p50_ms": _pct(ms, 0.5), "p95_ms": _pct(ms, 0.95),
            "errors_5xx": sum(1 for r in rows if r[3] >= 500), "slow": sum(1 for d in ms if d >= SLOW_MS), "slowest_routes": slow}


def cpu_now() -> Dict[str, float]:
    """Average vCPU used by this process since the last sample (CPU seconds ÷ wall seconds)."""
    cpu, wall = time.process_time(), time.monotonic()
    span = wall - _state["wall"]
    if span < 60:  # too short to mean anything: use the average since the process started
        life = max(time.time() - _state["started"], 1)
        return {"vcpu": round(cpu / life, 4), "span_s": round(life), "cpu": _state["cpu"], "wall": _state["wall"]}
    return {"vcpu": round((cpu - _state["cpu"]) / span, 4), "span_s": round(span), "cpu": cpu, "wall": wall}


# ---------------------------------------------------------------------- middleware + sampling
class MetricsMiddleware:
    """Pure ASGI middleware: times each API request and, every 15 minutes, saves one resource sample."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        start = time.monotonic()
        status = {"code": 500}

        async def _send(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        try:
            await self.app(scope, receive, _send)
        finally:
            end = time.monotonic()
            route = getattr(scope.get("route"), "path", None) or scope.get("path", "")[:60]
            if route.startswith("/api"):
                _lat.append((end, (end - start) * 1000, f"{scope.get('method')} {route}", status["code"]))
            if end - _state["last_sample"] >= SAMPLE_EVERY_S and not _state["sampling"]:
                _state["sampling"] = True
                t = asyncio.create_task(take_sample())
                _tasks.add(t)
                t.add_done_callback(_tasks.discard)


async def take_sample() -> Optional[dict]:
    try:
        if _db is None:
            return None
        since = _state["last_sample"] or 0.0
        c = cpu_now()
        t0 = time.monotonic()
        await _db.command("ping")
        ping = round((time.monotonic() - t0) * 1000, 1)
        stats = request_stats(since)
        doc = {"replica": REPLICA, "at": now().isoformat(), "at_dt": now(), "vcpu": c["vcpu"], "span_s": c["span_s"],
               **memory_mb(), **container_limits(), "db_ping_ms": ping,
               **{k: stats[k] for k in ("requests", "p50_ms", "p95_ms", "errors_5xx", "slow")}}
        _state.update(cpu=c["cpu"], wall=c["wall"], last_sample=time.monotonic())
        await _db.system_metrics.insert_one(dict(doc))
        await storage_snapshot()
        return doc
    except Exception:  # monitoring must never break requests
        traceback.print_exc()
        return None
    finally:
        _state["sampling"] = False


async def storage_totals() -> Dict[str, int]:
    async def agg(coll: str, match: dict) -> dict:
        rows = await getattr(_db, coll).aggregate([{"$match": match}, {"$group": {
            "_id": None, "n": {"$sum": 1}, "bytes": {"$sum": {"$ifNull": ["$size", 0]}}}}]).to_list(1)
        return rows[0] if rows else {}
    res = await agg("candidate_resumes", {"status": {"$ne": "deleted"}})
    ev = await agg("tracker_evidence", {"is_deleted": {"$ne": True}})
    return {"resume_files": res.get("n", 0), "resume_bytes": res.get("bytes", 0), "evidence_files": ev.get("n", 0),
            "evidence_bytes": ev.get("bytes", 0), "total_bytes": res.get("bytes", 0) + ev.get("bytes", 0)}


async def storage_snapshot() -> bool:
    """Once per UTC day across all replicas: record storage totals and database size for the trend chart."""
    day = now().date().isoformat()
    key = f"storage-snapshot-{day}"
    res = await _db.cron_runs.update_one({"run_id": key}, {"$setOnInsert": {"run_id": key, "name": "storage-snapshot",
                                                                            "created_at": now().isoformat()}}, upsert=True)
    if res.upserted_id is None:
        return False
    st = await _db.command("dbStats")
    await _db.storage_snapshots.update_one({"day": day}, {"$set": {
        "day": day, "at_dt": now(), **(await storage_totals()),
        "db_data_bytes": int(st.get("dataSize", 0)), "db_storage_bytes": int(st.get("storageSize", 0)),
        "db_index_bytes": int(st.get("indexSize", 0))}}, upsert=True)
    return True


async def tracked(name: str, work: Awaitable) -> Any:
    """Run a background job and record its duration and outcome in job_log."""
    started, t0 = now(), time.monotonic()
    status, error, result = "ok", None, None
    try:
        result = await work
        return result
    except Exception as e:
        status, error = "failed", f"{type(e).__name__}: {e}"[:300]
        traceback.print_exc()
    finally:
        if _db is not None:
            doc = {"name": name, "replica": REPLICA, "started_at": started.isoformat(), "finished_at": now().isoformat(),
                   "at_dt": started, "duration_ms": round((time.monotonic() - t0) * 1000), "status": status, "error": error}
            if isinstance(result, (int, float, str)) or (isinstance(result, dict) and len(str(result)) < 500):
                doc["result"] = result
            try:
                await _db.job_log.insert_one(doc)
            except Exception:
                traceback.print_exc()


async def ensure_indexes(db) -> None:
    await db.system_metrics.create_index("at_dt", expireAfterSeconds=KEEP_DAYS * 86400)
    await db.job_log.create_index("at_dt", expireAfterSeconds=KEEP_DAYS * 86400)
    await db.job_log.create_index([("name", 1), ("at_dt", -1)])
    await db.storage_snapshots.create_index("day", unique=True)
    await db.candidate_resumes.create_index("uploaded_at")
    await db.jobs.create_index("date_added")
    await db.job_matches.create_index([("created_at", 1)])


# ---------------------------------------------------------------------- router
def build_router(db, require_admin: Callable, live_job_q: Callable):
    init(db)
    r = APIRouter()
    NS = "Not specified"

    def top(field_expr, limit: int = 8) -> list:
        return [{"$group": {"_id": {"$ifNull": [field_expr, NS]}, "n": {"$sum": 1}}},
                {"$project": {"_id": 0, "name": {"$cond": [{"$in": ["$_id", ["", None]]}, NS, "$_id"]}, "count": "$n"}},
                {"$sort": {"count": -1}}, {"$limit": limit}]

    def count() -> list:
        return [{"$count": "n"}]

    def first(rows) -> int:
        return rows[0]["n"] if rows else 0

    def days_between(rng: dict, default_days: int = 30) -> List[str]:
        end = datetime.fromisoformat(rng["$lt"]).date() - timedelta(days=1) if rng.get("$lt") else now().date()
        start = datetime.fromisoformat(rng["$gte"]).date() if rng.get("$gte") else end - timedelta(days=default_days - 1)
        if (end - start).days > 366:
            start = end - timedelta(days=366)
        return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]

    async def daily(coll: str, field: str, days: List[str], match: Optional[dict] = None) -> List[dict]:
        q = {**(match or {}), field: {"$gte": days[0], "$lt": days[-1] + "~"}}
        got = {d["_id"]: d["n"] for d in await getattr(db, coll).aggregate([
            {"$match": q}, {"$group": {"_id": {"$substrBytes": [f"${field}", 0, 10]}, "n": {"$sum": 1}}}]).to_list(None)}
        return [{"day": d, "count": got.get(d, 0)} for d in days]

    # ------------------------------------------------------------------ consolidated analytics (Module K)
    @r.get("/admin/analytics/platform")
    async def platform(admin=Depends(require_admin), start: str = "", end: str = "", industry: str = "", source: str = ""):
        rng = _range(start or None, end or None)
        days = days_between(rng)
        ind = industry if industry and industry != "All" else None

        # Candidates
        cq: dict = {"role": "candidate"}
        if ind:
            cq["industry"] = ind
        exp_bucket = {"$switch": {"branches": [
            {"case": {"$not": [{"$isNumber": "$total_experience"}]}, "then": NS},
            {"case": {"$lt": ["$total_experience", 1]}, "then": "Under 1 year"},
            {"case": {"$lt": ["$total_experience", 3]}, "then": "1–3 years"},
            {"case": {"$lt": ["$total_experience", 5]}, "then": "3–5 years"},
            {"case": {"$lt": ["$total_experience", 10]}, "then": "5–10 years"}], "default": "10+ years"}}
        has_pref = {"$or": [{"preferred_industries.0": {"$exists": True}}, {"preferred_designation": {"$nin": [None, ""]}},
                            {"preferred_titles.0": {"$exists": True}}, {"preferred_location": {"$nin": [None, ""]}}]}
        cf = (await db.users.aggregate([{"$match": cq}, {"$facet": {
            "total": count(),
            "new_in_range": ([{"$match": {"created_at": rng}}] if rng else [{"$match": {"_id": None}}]) + count(),
            "complete": [{"$match": {"profile_completion": {"$gte": 100}}}] + count(),
            "with_preferences": [{"$match": has_pref}] + count(),
            "talent_consent": [{"$match": {"talent_db_consent": True}}] + count(),
            "alerts_on": [{"$match": {"job_alert_consent": True}}] + count(),
            "by_industry": top("$industry"),
            "by_designation": top("$current_designation"),
            "by_experience": [{"$group": {"_id": exp_bucket, "n": {"$sum": 1}}}, {"$project": {"_id": 0, "name": "$_id", "count": "$n"}},
                              {"$sort": {"count": -1}}],
            "by_location": top({"$ifNull": ["$current_location", "$preferred_location"]}),
        }}]).to_list(1))[0]
        cand_ids = None
        if ind:
            cand_ids = await db.users.distinct("user_id", cq)
        rq: dict = {"status": {"$ne": "deleted"}}
        if cand_ids is not None:
            rq["candidate_id"] = {"$in": cand_ids}
        with_resume = len(await db.candidate_resumes.distinct("candidate_id", rq))
        up_match = {"candidate_id": {"$in": cand_ids}} if cand_ids is not None else {}
        candidates = {
            "total": first(cf["total"]), "new_in_range": first(cf["new_in_range"]) if rng else None,
            "with_resume": with_resume, "complete_profiles": first(cf["complete"]),
            "with_preferences": first(cf["with_preferences"]), "talent_consent": first(cf["talent_consent"]),
            "alerts_on": first(cf["alerts_on"]),
            "by_industry": cf["by_industry"], "by_designation": cf["by_designation"],
            "by_experience": cf["by_experience"], "by_location": cf["by_location"],
            "resume_trend": await daily("candidate_resumes", "uploaded_at", days, up_match),
            "registration_trend": await daily("users", "created_at", days, cq),
        }

        # Jobs
        jq: dict = {}
        if ind:
            jq["industry_category"] = ind
        src_expr = {"$ifNull": ["$source_name", {"$ifNull": ["$job_source", NS]}]}
        if source and source != "All":
            jq["$expr"] = {"$eq": [src_expr, source]}
        if rng:
            jq["date_added"] = rng
        live = live_job_q()
        jf = (await db.jobs.aggregate([{"$match": jq}, {"$facet": {
            "total": count(),
            "imported": [{"$match": {"imported_via": "apify"}}] + count(),
            "awaiting": [{"$match": {"review_status": {"$in": ["new_import", "pending_review"]}}}] + count(),
            "pending_verification": [{"$match": {"verification_status": "Pending Verification", "review_status": {"$exists": False}}}] + count(),
            "active": [{"$match": live}] + count(),
            "expired": [{"$match": {"status": "Expired"}}] + count(),
            "rejected": [{"$match": {"$or": [{"verification_status": "Rejected"}, {"review_status": "rejected"}]}}] + count(),
            "duplicates": [{"$match": {"$or": [{"flags": "possible_duplicate"}, {"duplicate_of": {"$nin": [None, ""]}}]}}] + count(),
            "archived": [{"$match": {"status": "Archived"}}] + count(),
            "by_industry": top("$industry_category"),
            "by_source": [{"$group": {"_id": src_expr, "n": {"$sum": 1}}}, {"$project": {"_id": 0, "name": "$_id", "count": "$n"}},
                          {"$sort": {"count": -1}}, {"$limit": 10}],
            "by_location": top("$location"),
            "by_status": [{"$group": {"_id": "$status", "n": {"$sum": 1}}}, {"$project": {"_id": 0, "name": "$_id", "count": "$n"}},
                          {"$sort": {"count": -1}}],
        }}]).to_list(1))[0]
        jobs = {k: first(jf[k]) for k in ("total", "imported", "awaiting", "pending_verification", "active", "expired",
                                          "rejected", "duplicates", "archived")}
        jobs.update({k: jf[k] for k in ("by_industry", "by_source", "by_location", "by_status")})
        jobs["added_trend"] = await daily("jobs", "date_added", days, {k: v for k, v in jq.items() if k != "date_added"})

        # SmartMatch
        mq: dict = {}
        job_filter = {k: v for k, v in jq.items() if k != "date_added"}
        scoped_job_ids = await db.jobs.distinct("job_id", job_filter) if job_filter else None
        if scoped_job_ids is not None:
            mq["job_id"] = {"$in": scoped_job_ids}
        if rng:
            mq["created_at"] = rng
        mf = (await db.job_matches.aggregate([{"$match": mq}, {"$facet": {
            "total": count(),
            "strong": [{"$match": {"match_score": {"$gte": 80}}}] + count(),
            "potential": [{"$match": {"match_score": {"$gte": 65, "$lt": 80}}}] + count(),
            "approved": [{"$match": {"reached.approved": {"$exists": True}}}] + count(),
            "shared": [{"$match": {"reached.shared": {"$exists": True}}}] + count(),
            "candidates_relevant": [{"$match": {"match_score": {"$gte": 65}, "status": {"$ne": "rejected"}}},
                                    {"$group": {"_id": "$candidate_id"}}] + count(),
        }}]).to_list(1))[0]
        live_ids = await db.jobs.distinct("job_id", {**live_job_q(), **job_filter})
        matched_ids = set(await db.job_matches.distinct("job_id", {"job_id": {"$in": live_ids}, "match_score": {"$gte": 65},
                                                                    "status": {"$ne": "rejected"}}))
        nq: dict = {}
        if scoped_job_ids is not None:
            nq["job_id"] = {"$in": scoped_job_ids}
        if rng:
            nq["$or"] = [{"created_at": rng}, {"sent_at": rng}]
        notes = await db.job_notifications.aggregate([{"$match": nq}, {"$group": {
            "_id": {"source": {"$ifNull": ["$source", "admin"]}, "channel": "$channel", "status": "$status"}, "n": {"$sum": 1}}}]).to_list(None)
        sent = [n for n in notes if n["_id"]["status"] == "sent"]
        smartmatch = {k: first(mf[k]) for k in ("total", "strong", "potential", "approved", "shared", "candidates_relevant")}
        smartmatch.update({
            "live_jobs": len(live_ids), "jobs_without_candidates": len(live_ids) - len(matched_ids),
            "notifications": sum(n["n"] for n in sent),
            "notifications_auto": sum(n["n"] for n in sent if n["_id"]["source"] == "auto"),
            "notifications_admin": sum(n["n"] for n in sent if n["_id"]["source"] != "auto"),
            "notifications_in_app": sum(n["n"] for n in sent if n["_id"]["channel"] == "in_app"),
            "notifications_email": sum(n["n"] for n in sent if n["_id"]["channel"] == "email"),
            "notifications_failed": sum(n["n"] for n in notes if n["_id"]["status"] == "failed"),
        })
        no_cand = await db.jobs.find({"job_id": {"$in": [j for j in live_ids if j not in matched_ids][:200]}},
                                     {"_id": 0, "job_id": 1, "title": 1, "company": 1, "industry_category": 1}
                                     ).sort("date_published", -1).to_list(10)
        smartmatch["jobs_without_candidates_sample"] = no_cand

        # Apify
        aq: dict = {"started_at": rng} if rng else {}
        af = (await db.apify_runs.aggregate([{"$match": aq}, {"$group": {
            "_id": None, "runs": {"$sum": 1},
            "succeeded": {"$sum": {"$cond": [{"$eq": ["$status", "SUCCEEDED"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$in": ["$status", ["FAILED", "ABORTED", "TIMED-OUT"]]}, 1, 0]}},
            "running": {"$sum": {"$cond": [{"$in": ["$status", ["STARTING", "READY", "RUNNING"]]}, 1, 0]}},
            "items": {"$sum": {"$ifNull": ["$summary.items", 0]}},
            "imported": {"$sum": {"$ifNull": ["$summary.created", 0]}},
            "updated": {"$sum": {"$ifNull": ["$summary.updated", 0]}},
            "duplicates": {"$sum": {"$ifNull": ["$summary.duplicates", 0]}},
            "cost_usd": {"$sum": {"$ifNull": ["$cost_usd", 0]}}}}]).to_list(1) or [{}])[0]
        af.pop("_id", None)
        month_start = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly = {d["_id"]: d for d in await db.apify_runs.aggregate([
            {"$match": {"started_at": {"$gte": (month_start - timedelta(days=160)).replace(day=1).isoformat()}}},
            {"$group": {"_id": {"$substrBytes": ["$started_at", 0, 7]}, "runs": {"$sum": 1},
                        "usd": {"$sum": {"$ifNull": ["$cost_usd", "$cost_cap_usd"]}},
                        "imported": {"$sum": {"$ifNull": ["$summary.created", 0]}}}}]).to_list(None)}
        months = []
        y, m = month_start.year, month_start.month
        for _ in range(6):
            key = f"{y:04d}-{m:02d}"
            row = monthly.get(key, {})
            months.append({"month": key, "runs": row.get("runs", 0), "usd": round(row.get("usd", 0) or 0, 4),
                           "imported": row.get("imported", 0)})
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        months.reverse()
        settings = await db.app_settings.find_one({"key": "apify"}, {"_id": 0}) or {}
        budget = float(settings.get("monthly_budget_usd") or 15.0)
        spent = months[-1]["usd"]
        dim = calendar.monthrange(month_start.year, month_start.month)[1]
        projected = round(spent / max(now().day, 1) * dim, 4)
        srcs = await db.job_sources.find({}, {"_id": 0, "source_id": 1, "name": 1, "enabled": 1, "permission_status": 1,
                                             "jobs_imported": 1, "last_run_at": 1}).to_list(200)
        sjq: dict = {"imported_via": "apify"}
        if rng:
            sjq["imported_at"] = rng
        per_src = {d["_id"]: d for d in await db.jobs.aggregate([{"$match": sjq}, {"$group": {
            "_id": "$source_id", "imported": {"$sum": 1},
            "awaiting": {"$sum": {"$cond": [{"$in": ["$review_status", ["new_import", "pending_review"]]}, 1, 0]}},
            "approved": {"$sum": {"$cond": [{"$eq": ["$review_status", "approved"]}, 1, 0]}},
            "rejected": {"$sum": {"$cond": [{"$eq": ["$review_status", "rejected"]}, 1, 0]}},
            "duplicates": {"$sum": {"$cond": [{"$in": ["possible_duplicate", {"$ifNull": ["$flags", []]}]}, 1, 0]}},
            "published": {"$sum": {"$cond": [{"$eq": ["$status", "Published"]}, 1, 0]}}}}]).to_list(None)}
        by_source = []
        for s in srcs:
            p = per_src.get(s["source_id"], {})
            by_source.append({**s, **{k: p.get(k, 0) for k in ("imported", "awaiting", "approved", "rejected", "duplicates", "published")}})
        by_source.sort(key=lambda x: -x["imported"])
        apify = {**{k: af.get(k, 0) for k in ("runs", "succeeded", "failed", "running", "items", "imported", "updated", "duplicates")},
                 "cost_usd": round(af.get("cost_usd", 0) or 0, 4),
                 "avg_cost_per_run_usd": round((af.get("cost_usd", 0) or 0) / af["runs"], 4) if af.get("runs") else None,
                 "month_spend_usd": spent, "month_projected_usd": projected, "month_budget_usd": budget,
                 "month_spend_inr": round(spent * USD_INR), "month_projected_inr": round(projected * USD_INR),
                 "month_budget_inr": round(budget * USD_INR), "usd_inr_rate": USD_INR,
                 "paid_runs_approved": bool(settings.get("paid_runs_approved")), "monthly": months, "by_source": by_source}

        # Storage
        snaps = await db.storage_snapshots.find({}, {"_id": 0, "at_dt": 0}).sort("day", -1).to_list(30)
        storage = {**(await storage_totals()), "trend": list(reversed(snaps))}

        industries = sorted(x for x in await db.jobs.distinct("industry_category") if x)
        sources = sorted({x["name"] for x in jobs["by_source"]} | {s["name"] for s in srcs})
        return {"candidates": candidates, "jobs": jobs, "smartmatch": smartmatch, "apify": apify, "storage": storage,
                "range": {"start": days[0], "end": days[-1]}, "options": {"industries": industries, "sources": sources},
                "generated_at": now().isoformat()}

    # ------------------------------------------------------------------ background processing + resources (Module L)
    async def scheduled_jobs() -> List[dict]:
        week = now() - timedelta(days=7)
        stats = {d["_id"]: d for d in await db.job_log.aggregate([
            {"$match": {"at_dt": {"$gte": week}}},
            {"$group": {"_id": "$name", "runs": {"$sum": 1}, "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
                        "avg_ms": {"$avg": "$duration_ms"}, "max_ms": {"$max": "$duration_ms"}}}]).to_list(None)}
        out = []
        for name in list(SCHEDULES) + sorted(set(stats) - set(SCHEDULES)):
            label, every = SCHEDULES.get(name, ("On demand", None))
            last = await db.job_log.find_one({"name": name}, {"_id": 0, "at_dt": 0}, sort=[("at_dt", -1)])
            if not last:
                # Jobs that ran before monitoring was added still left a cron_runs record.
                cr = await db.cron_runs.find_one({"name": name}, {"_id": 0}, sort=[("created_at", -1)])
                last = {"started_at": cr["created_at"], "status": "ok", "duration_ms": None} if cr else None
            st = stats.get(name, {})
            health = "ok"
            if not last:
                health = "never_run" if every else "idle"
            elif last.get("status") == "failed":
                health = "failed"
            elif every and datetime.fromisoformat(last["started_at"]) < now() - timedelta(minutes=every * 2 + 30):
                health = "overdue"
            out.append({"name": name, "schedule": label, "last": last, "health": health, "runs_7d": st.get("runs", 0),
                        "failed_7d": st.get("failed", 0), "avg_ms": round(st["avg_ms"]) if st.get("avg_ms") is not None else None,
                        "max_ms": st.get("max_ms")})
        return out

    async def queues() -> Dict[str, Any]:
        t = now()
        mq = {d["_id"]: d["n"] for d in await db.match_queue.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(None)}
        oldest = await db.match_queue.find_one({"status": "queued"}, {"_id": 0, "created_at": 1}, sort=[("created_at", 1)])
        stuck_m = await db.match_queue.count_documents({"status": "processing", "lock_until": {"$lt": t}})
        rs = {d["_id"]: d["n"] for d in await db.candidate_resumes.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(None)}
        r_oldest = await db.candidate_resumes.find_one({"status": "queued"}, {"_id": 0, "uploaded_at": 1}, sort=[("uploaded_at", 1)])
        stuck_r = await db.candidate_resumes.count_documents({"status": "processing", "lock_until": {"$lt": t}})
        failed_r = await db.candidate_resumes.find({"status": "failed"}, {"_id": 0, "resume_id": 1, "file_name": 1, "error": 1,
                                                                          "attempts": 1, "uploaded_at": 1}).sort("uploaded_at", -1).to_list(5)
        day = (t - timedelta(days=1)).isoformat()
        email_failed = await db.email_logs.count_documents({"delivery_status": "failed", "date_sent": {"$gte": day}})
        email_retry = await db.email_logs.count_documents({"delivery_status": "failed", "retry_html": {"$exists": True},
                                                           "retry_count": {"$not": {"$gte": 2}}})
        apify_running = await db.apify_runs.count_documents({"status": {"$in": ["STARTING", "READY", "RUNNING"]}})
        apify_failed = await db.apify_runs.count_documents({"status": {"$in": ["FAILED", "ABORTED", "TIMED-OUT"]},
                                                           "started_at": {"$gte": (t - timedelta(days=7)).isoformat()}})

        def age_min(iso: Optional[str]) -> Optional[int]:
            if not iso:
                return None
            d = datetime.fromisoformat(iso) if isinstance(iso, str) else iso
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            return max(0, round((t - d).total_seconds() / 60))

        return {
            "smartmatch": {"queued": mq.get("queued", 0), "processing": mq.get("processing", 0), "done_7d": mq.get("done", 0),
                           "failed": mq.get("failed", 0), "stuck": stuck_m, "oldest_queued_min": age_min((oldest or {}).get("created_at"))},
            "resumes": {"queued": rs.get("queued", 0), "processing": rs.get("processing", 0), "parsed": rs.get("parsed", 0),
                        "confirmed": rs.get("confirmed", 0), "failed": rs.get("failed", 0), "stuck": stuck_r,
                        "oldest_queued_min": age_min((r_oldest or {}).get("uploaded_at")), "recent_failures": failed_r},
            "email": {"failed_24h": email_failed, "awaiting_retry": email_retry},
            "apify": {"running": apify_running, "failed_7d": apify_failed},
            "in_process_tasks": len(_tasks),
        }

    async def resources() -> Dict[str, Any]:
        c = cpu_now()
        stats = request_stats(time.monotonic() - SAMPLE_EVERY_S)
        t0 = time.monotonic()
        await db.command("ping")
        ping = round((time.monotonic() - t0) * 1000, 1)
        this = {"replica": REPLICA, "uptime_min": round((time.time() - _state["started"]) / 60), "vcpu": c["vcpu"],
                "vcpu_span_s": c["span_s"], **memory_mb(), **container_limits(), "db_ping_ms": ping,
                "last_15_min": stats}
        week = now() - timedelta(days=7)
        hourly = await db.system_metrics.aggregate([
            {"$match": {"at_dt": {"$gte": week}}},
            {"$group": {"_id": {"$substrBytes": ["$at", 0, 13]}, "vcpu": {"$max": "$vcpu"}, "rss_mb": {"$max": "$rss_mb"},
                        "p95_ms": {"$max": "$p95_ms"}, "requests": {"$sum": "$requests"}, "errors": {"$sum": "$errors_5xx"},
                        "db_ping_ms": {"$max": "$db_ping_ms"}}},
            {"$sort": {"_id": 1}}, {"$project": {"_id": 0, "hour": "$_id", "vcpu": 1, "rss_mb": 1, "p95_ms": 1, "requests": 1,
                                                  "errors": 1, "db_ping_ms": 1}}]).to_list(None)
        samples = await db.system_metrics.find({"at_dt": {"$gte": week}}, {"_id": 0, "vcpu": 1, "rss_mb": 1, "p95_ms": 1,
                                                                            "errors_5xx": 1, "requests": 1, "replica": 1}).to_list(5000)
        n = len(samples)
        cpu_hi = sum(1 for s in samples if (s.get("vcpu") or 0) >= STARTER["cpu_burst"] * 0.8)
        mem_hi = sum(1 for s in samples if (s.get("rss_mb") or 0) >= STARTER["mem_burst_mb"] * 0.8)
        slow = sum(1 for s in samples if (s.get("p95_ms") or 0) >= SLOW_MS)
        reqs = sum(s.get("requests") or 0 for s in samples)
        errs = sum(s.get("errors_5xx") or 0 for s in samples)
        week_summary = {
            "samples": n, "replicas": sorted({s.get("replica") for s in samples if s.get("replica")}),
            "vcpu_avg": round(sum(s.get("vcpu") or 0 for s in samples) / n, 4) if n else None,
            "vcpu_p95": _pct([s.get("vcpu") or 0 for s in samples], 0.95),
            "rss_max_mb": max((s.get("rss_mb") or 0 for s in samples), default=None) if n else None,
            "p95_ms_p95": _pct([s.get("p95_ms") or 0 for s in samples if s.get("p95_ms") is not None], 0.95),
            "cpu_high_pct": round(cpu_hi * 100 / n, 1) if n else None,
            "mem_high_pct": round(mem_hi * 100 / n, 1) if n else None,
            "slow_pct": round(slow * 100 / n, 1) if n else None,
            "requests": reqs, "error_rate_pct": round(errs * 100 / reqs, 2) if reqs else None,
        }
        st = await db.command("dbStats")
        colls = {}
        for name in ("users", "jobs", "job_matches", "job_notifications", "candidate_resumes", "email_logs", "apify_runs",
                     "job_import_logs", "match_queue", "system_metrics", "job_log"):
            colls[name] = await getattr(db, name).estimated_document_count()
        return {"this_replica": this, "starter": STARTER, "hourly": hourly, "week": week_summary,
                "recommendation": recommend(week_summary),
                "database": {"data_bytes": int(st.get("dataSize", 0)), "storage_bytes": int(st.get("storageSize", 0)),
                             "index_bytes": int(st.get("indexSize", 0)), "objects": int(st.get("objects", 0)),
                             "ping_ms": ping, "collections": colls}}

    @r.get("/admin/system/health")
    async def health(admin=Depends(require_admin)):
        return {"jobs": await scheduled_jobs(), "queues": await queues(), "resources": await resources(),
                "generated_at": now().isoformat()}

    @r.post("/admin/system/sample")
    async def sample_now(admin=Depends(require_admin)):
        """Save a resource sample from this replica now (normally taken every 15 minutes)."""
        if _state["sampling"]:
            return {"sample": None}
        _state["sampling"] = True
        return {"sample": {k: v for k, v in ((await take_sample()) or {}).items() if k not in ("_id", "at_dt")}}

    return r, {"tracked": tracked}


def recommend(w: dict) -> Dict[str, Any]:
    """Hosting advice from a week of samples. Only recommends an upgrade when pressure is sustained."""
    if not w.get("samples") or w["samples"] < 96:  # fewer than ~1 day of samples on one replica
        return {"level": "info", "upgrade": False,
                "message": "Not enough data yet. JobRadar records CPU, memory and response times every 15 minutes; "
                           "check back after a few days of normal traffic before deciding anything about hosting."}
    reasons = []
    if (w.get("cpu_high_pct") or 0) >= 25:
        reasons.append(f"CPU was near the Starter burst limit in {w['cpu_high_pct']}% of samples")
    if (w.get("mem_high_pct") or 0) >= 25:
        reasons.append(f"memory was above 80% of 512 MB in {w['mem_high_pct']}% of samples")
    if (w.get("slow_pct") or 0) >= 25:
        reasons.append(f"slowest responses took over {SLOW_MS // 1000} s in {w['slow_pct']}% of samples")
    if reasons:
        return {"level": "warning", "upgrade": True,
                "message": "Starter hosting looks consistently stretched: " + "; ".join(reasons) + ". Check the slowest "
                           "routes below first; if they are already optimised, discuss a higher tier with Emergent."}
    if (w.get("cpu_high_pct") or 0) >= 5 or (w.get("mem_high_pct") or 0) >= 5 or (w.get("slow_pct") or 0) >= 5:
        return {"level": "notice", "upgrade": False,
                "message": "Starter hosting is coping, with occasional busy periods. No upgrade needed; keep watching."}
    return {"level": "ok", "upgrade": False, "message": "Starter hosting has comfortable headroom. No upgrade needed."}
