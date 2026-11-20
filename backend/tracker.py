import asyncio
import csv
import hmac
import io
import os
import uuid
import re
from datetime import date, timedelta
from html import escape
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

STATUSES = {
    "interested": "Interested", "contacted": "Contacted Recruiter", "applied": "Applied",
    "responded": "Recruiter Responded", "interview_scheduled": "Interview Scheduled",
    "interview_completed": "Interview Completed", "offer_received": "Offer Received", "hired": "Hired",
    "not_selected": "Not Selected", "no_response": "No Response",
}
TERMINAL = {"hired", "not_selected"}
REMINDERS = [(30, "Any update on this opportunity?"), (14, "Have you received an interview call?"),
             (7, "Did you submit your application?"), (3, "Have you contacted the recruiter?")]
EVIDENCE_KINDS = {"interview_invite": "Interview invitation", "interview_confirmation": "Interview confirmation",
                  "offer_letter": "Offer letter", "joining_confirmation": "Joining confirmation"}
EVIDENCE_TYPES = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
CONVERSIONS = [
    ("saved", "contacted", "Job Saved → Recruiter Contacted", "Tracked jobs where the candidate reported contacting the recruiter ÷ all tracked jobs."),
    ("contacted", "applied", "Recruiter Contacted → Applied", "Of tracked jobs that reached 'Contacted Recruiter', the share that also reached 'Applied'."),
    ("applied", "interview_scheduled", "Applied → Interview Scheduled", "Of tracked jobs that reached 'Applied', the share that also reached 'Interview Scheduled'."),
    ("interview_scheduled", "offer_received", "Interview Scheduled → Offer Received", "Of tracked jobs that reached 'Interview Scheduled', the share that also reached 'Offer Received'."),
    ("applied", "hired", "Applied → Hired", "Of tracked jobs that reached 'Applied', the share that also reached 'Hired'."),
]
FUNNEL = ["contacted", "applied", "responded", "interview_scheduled", "interview_completed", "offer_received", "hired"]

from storage import APP_NAME, _get_object, _put_object, warm_storage  # noqa: F401 - warm_storage is re-exported for server.py


class TrackReq(BaseModel):
    job_id: str


class StatusReq(BaseModel):
    status: str
    interview_company: Optional[str] = None
    interview_date: Optional[str] = None
    interview_mode: Optional[str] = None
    interview_comments: Optional[str] = None
    hire_company: Optional[str] = None
    hire_designation: Optional[str] = None
    joining_date: Optional[str] = None
    hire_feedback: Optional[str] = None


class SettingsReq(BaseModel):
    email_reminders: bool


class VerifyReq(BaseModel):
    kind: str
    verified: bool


def _range(start: Optional[str], end: Optional[str]) -> dict:
    q = {}
    try:
        for d in (start, end):
            if d:
                date.fromisoformat(d)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")
    if start:
        q["$gte"] = f"{start}T00:00:00"
    if end:
        q["$lt"] = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
    return q


def build_router(db, get_current_user, require_admin, compute_membership, send_and_log_email, wrap_email,
                 now_utc, now_iso, parse_dt, hooks=None):
    r = APIRouter()

    def reminder_for(t: dict) -> Optional[dict]:
        if t.get("status") in TERMINAL:
            return None
        last = parse_dt(t.get("updated_at")) or now_utc()
        age = (now_utc() - last).days
        for days, text in REMINDERS:
            if age >= days:
                key = f"{days}:{t.get('updated_at')}"
                if key in (t.get("reminders_dismissed") or []):
                    return None
                return {"key": key, "days": days, "text": text}
        return None

    async def public_item(t: dict, is_member: bool) -> dict:
        out = {k: v for k, v in t.items() if k not in ("reminders_dismissed", "reminders_emailed")}
        if not is_member:
            out["recruiter_name"] = out["recruiter_email"] = None
        out["status_label"] = STATUSES.get(t["status"], t["status"])
        out["reminder"] = reminder_for(t)
        out["evidence"] = await db.tracker_evidence.find(
            {"tracker_id": t["tracker_id"], "is_deleted": False},
            {"_id": 0, "evidence_id": 1, "kind": 1, "original_filename": 1, "created_at": 1}).to_list(50)
        return out

    async def own(tracker_id: str, user: dict) -> dict:
        t = await db.job_tracker.find_one({"tracker_id": tracker_id, "candidate_id": user["user_id"], "archived": {"$ne": True}}, {"_id": 0})
        if not t:
            raise HTTPException(status_code=404, detail="Tracked job not found")
        return t

    # ------------------------------------------------------------------ candidate
    @r.post("/tracker")
    async def track(req: TrackReq, user=Depends(get_current_user)):
        if user.get("role") != "candidate":
            raise HTTPException(status_code=403, detail="Only candidates can track jobs")
        job = await db.jobs.find_one({"job_id": req.job_id}, {"_id": 0})
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        now = now_iso()
        doc = {
            "tracker_id": f"trk_{uuid.uuid4().hex[:12]}", "candidate_id": user["user_id"], "job_id": job["job_id"],
            "company": job.get("company"), "designation": job.get("title"),
            "location": job.get("location") or job.get("city") or job.get("country"),
            "industry": job.get("industry_category") or job.get("function") or "Not Specified",
            "recruiter_name": job.get("recruiter_name"), "recruiter_email": job.get("recruiter_email"),
            "status": "interested", "status_history": [{"status": "interested", "at": now}],
            "reached": {"saved": now}, "interview": None, "hire": None,
            "interview_verification": None, "hire_verification": None,
            "reminders_dismissed": [], "reminders_emailed": [], "archived": False,
            "created_at": now, "updated_at": now,
        }
        await db.job_tracker.update_one({"candidate_id": user["user_id"], "job_id": job["job_id"]},
                                        {"$setOnInsert": doc}, upsert=True)
        t = await db.job_tracker.find_one({"candidate_id": user["user_id"], "job_id": job["job_id"]}, {"_id": 0})
        if t.get("archived"):
            await db.job_tracker.update_one({"tracker_id": t["tracker_id"]}, {"$set": {"archived": False, "updated_at": now}})
            t["archived"] = False
        for h in hooks or []:
            await h(user["user_id"], job["job_id"], "interested")
        m = await compute_membership(user["user_id"])
        return {"item": await public_item(t, m["is_active"])}

    @r.get("/tracker")
    async def my_tracker(user=Depends(get_current_user)):
        items = await db.job_tracker.find({"candidate_id": user["user_id"], "archived": {"$ne": True}}, {"_id": 0}).sort("updated_at", -1).to_list(500)
        m = await compute_membership(user["user_id"])
        return {"items": [await public_item(t, m["is_active"]) for t in items], "statuses": STATUSES,
                "email_reminders": user.get("tracker_email_reminders", True)}

    @r.get("/tracker/job/{job_id}")
    async def tracker_for_job(job_id: str, user=Depends(get_current_user)):
        t = await db.job_tracker.find_one({"candidate_id": user["user_id"], "job_id": job_id, "archived": {"$ne": True}}, {"_id": 0})
        return {"item": {"tracker_id": t["tracker_id"], "status": t["status"], "status_label": STATUSES[t["status"]]} if t else None}

    @r.put("/tracker/{tracker_id}/status")
    async def update_status(tracker_id: str, req: StatusReq, user=Depends(get_current_user)):
        t = await own(tracker_id, user)
        if req.status not in STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status")
        now = now_iso()
        upd = {"status": req.status, "updated_at": now}
        if req.status == "interview_scheduled":
            if not req.interview_date or req.interview_mode not in ("Phone", "Video", "Face-to-Face"):
                raise HTTPException(status_code=400, detail="Interview date and mode are required")
            upd["interview"] = {"company": (req.interview_company or t.get("company") or "").strip()[:200],
                                "date": req.interview_date[:20], "mode": req.interview_mode,
                                "comments": (req.interview_comments or "").strip()[:1000], "reported_at": now}
            if not t.get("interview_verification"):
                upd["interview_verification"] = "candidate_reported"
        if req.status == "hired":
            if not req.joining_date or not (req.hire_company or "").strip() or not (req.hire_designation or "").strip():
                raise HTTPException(status_code=400, detail="Company, designation and joining date are required")
            upd["hire"] = {"company": req.hire_company.strip()[:200], "designation": req.hire_designation.strip()[:200],
                           "joining_date": req.joining_date[:20], "feedback": (req.hire_feedback or "").strip()[:1000],
                           "reported_at": now}
            if not t.get("hire_verification"):
                upd["hire_verification"] = "candidate_reported"
        if req.status not in (t.get("reached") or {}):
            upd[f"reached.{req.status}"] = now
        await db.job_tracker.update_one({"tracker_id": tracker_id}, {"$set": upd,
                                        "$push": {"status_history": {"status": req.status, "at": now}}})
        t = await db.job_tracker.find_one({"tracker_id": tracker_id}, {"_id": 0})
        for h in hooks or []:
            await h(user["user_id"], t["job_id"], req.status)
        m = await compute_membership(user["user_id"])
        return {"item": await public_item(t, m["is_active"])}

    @r.post("/tracker/{tracker_id}/dismiss-reminder")
    async def dismiss(tracker_id: str, user=Depends(get_current_user)):
        t = await own(tracker_id, user)
        rem = reminder_for(t)
        if rem:
            await db.job_tracker.update_one({"tracker_id": tracker_id}, {"$addToSet": {"reminders_dismissed": rem["key"]}})
        return {"ok": True}

    @r.delete("/tracker/{tracker_id}")
    async def untrack(tracker_id: str, user=Depends(get_current_user)):
        await own(tracker_id, user)
        await db.job_tracker.update_one({"tracker_id": tracker_id}, {"$set": {"archived": True, "archived_at": now_iso()}})
        return {"ok": True}

    @r.put("/tracker/settings")
    async def tracker_settings(req: SettingsReq, user=Depends(get_current_user)):
        await db.users.update_one({"user_id": user["user_id"]}, {"$set": {"tracker_email_reminders": req.email_reminders}})
        return {"email_reminders": req.email_reminders}

    @r.post("/tracker/{tracker_id}/evidence")
    async def upload_evidence(tracker_id: str, kind: str = Form(...), redacted: str = Form(...),
                              file: UploadFile = File(...), user=Depends(get_current_user)):
        await own(tracker_id, user)
        if kind not in EVIDENCE_KINDS:
            raise HTTPException(status_code=400, detail="Unknown evidence type")
        if redacted != "true":
            raise HTTPException(status_code=400, detail="Please confirm you have hidden salary and private details")
        ctype = (file.content_type or "").lower()
        if ctype not in EVIDENCE_TYPES:
            raise HTTPException(status_code=400, detail="Please upload a PDF, PNG, JPG or WEBP file")
        data = await file.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="File must be under 5 MB")
        magic = {"pdf": data[:5] == b"%PDF-", "png": data[:8] == b"\x89PNG\r\n\x1a\n", "jpg": data[:3] == b"\xff\xd8\xff",
                 "webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}
        if not magic[EVIDENCE_TYPES[ctype]]:
            raise HTTPException(status_code=400, detail="The file content does not match its type")
        path = f"{APP_NAME}/evidence/{user['user_id']}/{uuid.uuid4().hex}.{EVIDENCE_TYPES[ctype]}"
        try:
            res = await asyncio.to_thread(_put_object, path, data, ctype)
        except Exception:
            raise HTTPException(status_code=502, detail="Upload failed. Please try again.")
        ev = {"evidence_id": f"ev_{uuid.uuid4().hex[:12]}", "tracker_id": tracker_id, "candidate_id": user["user_id"],
              "kind": kind, "storage_path": res.get("path", path), "original_filename": (file.filename or "file")[:120],
              "content_type": ctype, "size": len(data), "is_deleted": False, "created_at": now_iso()}
        await db.tracker_evidence.insert_one(dict(ev))
        return {"evidence_id": ev["evidence_id"], "kind": kind, "original_filename": ev["original_filename"]}

    # ------------------------------------------------------------------ reminders cron
    async def send_reminder_emails():
        users = {u["user_id"]: u for u in await db.users.find(
            {"role": "candidate", "tracker_email_reminders": {"$ne": False}, "suspended": {"$ne": True}},
            {"_id": 0, "user_id": 1, "email": 1, "full_name": 1}).to_list(20000)}
        items = await db.job_tracker.find({"archived": {"$ne": True}, "status": {"$nin": list(TERMINAL)},
                                           "candidate_id": {"$in": list(users)}}, {"_id": 0}).to_list(50000)
        per_user: dict = {}
        for t in items:
            rem = reminder_for(t)
            if rem and rem["key"] not in (t.get("reminders_emailed") or []):
                per_user.setdefault(t["candidate_id"], []).append((t, rem))
        for uid, pairs in per_user.items():
            u = users[uid]
            rows = "".join(f'<li style="margin-bottom:8px"><strong>{escape(t.get("designation") or "")}</strong> at '
                           f'{escape(t.get("company") or "")} &mdash; {escape(rem["text"])}</li>' for t, rem in pairs)
            inner = (f'<p style="color:#374151;font-size:15px">Hi {escape(u.get("full_name") or "there")},</p>'
                     f'<p style="color:#374151;font-size:15px">A quick check-in on jobs in your My Job Search Tracker:</p>'
                     f'<ul style="color:#374151;font-size:14px">{rows}</ul>'
                     '<p style="color:#6B7280;font-size:13px">Open JobRadar and update your progress, or dismiss the reminder. '
                     'You can turn these emails off on your tracker page.</p>')
            await send_and_log_email(candidate_id=uid, to=u["email"], email_type="tracker_reminder",
                                     subject="Any progress on your saved jobs?", html=wrap_email("Job search check-in", inner))
            for t, rem in pairs:
                await db.job_tracker.update_one({"tracker_id": t["tracker_id"]}, {"$addToSet": {"reminders_emailed": rem["key"]}})

    @r.post("/cron/tracker-reminders")
    async def cron_reminders(request: Request, background: BackgroundTasks, authorization: Optional[str] = Header(None),
                             x_webhook_id: Optional[str] = Header(None)):
        # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
        secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not secret or not hmac.compare_digest(token, secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid body")
        run_id = x_webhook_id or (body or {}).get("run_id") or uuid.uuid4().hex
        res = await db.cron_runs.update_one({"run_id": run_id}, {"$setOnInsert": {"run_id": run_id, "name": "tracker-reminders",
                                            "created_at": now_iso()}}, upsert=True)
        if res.upserted_id is not None:
            from ops import tracked
            background.add_task(tracked, "tracker-reminders", send_reminder_emails())
        return {"accepted": True}

    # ------------------------------------------------------------------ admin
    async def filtered_records(start, end, industry, company, designation, job_id, location):
        q: dict = {"archived": {"$ne": True}}
        rng = _range(start, end)
        if rng:
            q["created_at"] = rng
        if industry and industry != "All":
            q["industry"] = industry
        if job_id:
            q["job_id"] = job_id.strip()
        for field, val in (("company", company), ("designation", designation), ("location", location)):
            if val:
                q[field] = {"$regex": re.escape(val.strip()), "$options": "i"}
        return await db.job_tracker.find(q, {"_id": 0, "reminders_dismissed": 0, "reminders_emailed": 0}).sort("updated_at", -1).to_list(50000)

    def summarise(records: list) -> dict:
        stages = ["saved"] + FUNNEL
        recs = {s: [t for t in records if s in (t.get("reached") or {})] for s in stages}
        totals = {s: {"records": len(recs[s]), "candidates": len({t["candidate_id"] for t in recs[s]})} for s in stages}
        conversions = []
        for a, b, label, explain in CONVERSIONS:
            den = recs[a]
            num = [t for t in den if b in (t.get("reached") or {})]
            conversions.append({"label": label, "explain": explain, "numerator": len(num), "denominator": len(den),
                                "rate": round(len(num) * 100 / len(den), 1) if den else None})
        iv = [t for t in records if t.get("interview_verification")]
        hi = [t for t in records if t.get("hire_verification")]
        verification = {
            "interview_reported": len(iv), "interview_verified": sum(1 for t in iv if t["interview_verification"] == "verified"),
            "hire_reported": len(hi), "hire_verified": sum(1 for t in hi if t["hire_verification"] == "verified"),
        }
        return {"totals": totals, "conversions": conversions, "verification": verification}

    @r.get("/admin/success")
    async def admin_success(admin=Depends(require_admin), start: Optional[str] = None, end: Optional[str] = None,
                            industry: Optional[str] = None, company: Optional[str] = None, designation: Optional[str] = None,
                            job_id: Optional[str] = None, location: Optional[str] = None):
        records = await filtered_records(start, end, industry, company, designation, job_id, location)
        ids = list({t["candidate_id"] for t in records})
        users = {u["user_id"]: u for u in await db.users.find({"user_id": {"$in": ids}}, {"_id": 0, "user_id": 1, "full_name": 1, "email": 1}).to_list(len(ids) + 1)}
        evs: dict = {}
        for e in await db.tracker_evidence.find({"tracker_id": {"$in": [t["tracker_id"] for t in records]}, "is_deleted": False},
                                                {"_id": 0, "storage_path": 0}).to_list(20000):
            evs.setdefault(e["tracker_id"], []).append(e)
        rows = []
        for t in records[:300]:
            u = users.get(t["candidate_id"], {})
            rows.append({**t, "candidate_name": u.get("full_name"), "candidate_email": u.get("email"),
                         "status_label": STATUSES.get(t["status"]), "evidence": evs.get(t["tracker_id"], [])})
        return {**summarise(records), "records": rows, "total_records": len(records), "statuses": STATUSES,
                "evidence_kinds": EVIDENCE_KINDS}

    @r.get("/admin/success/export")
    async def admin_success_export(admin=Depends(require_admin), start: Optional[str] = None, end: Optional[str] = None,
                                   industry: Optional[str] = None, company: Optional[str] = None,
                                   designation: Optional[str] = None, job_id: Optional[str] = None, location: Optional[str] = None):
        records = await filtered_records(start, end, industry, company, designation, job_id, location)
        ids = list({t["candidate_id"] for t in records})
        users = {u["user_id"]: u for u in await db.users.find({"user_id": {"$in": ids}}, {"_id": 0, "user_id": 1, "full_name": 1, "email": 1}).to_list(len(ids) + 1)}
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Tracker ID", "Candidate", "Email", "Job ID", "Designation", "Company", "Location", "Industry",
                    "Current Status", "Saved On", "Last Update", "Interview Date", "Interview Mode", "Interview Result",
                    "Hire Company", "Joining Date", "Hire Result"])
        for t in records:
            u = users.get(t["candidate_id"], {})
            iv, hi = t.get("interview") or {}, t.get("hire") or {}
            w.writerow([t["tracker_id"], u.get("full_name"), u.get("email"), t["job_id"], t.get("designation"), t.get("company"),
                        t.get("location"), t.get("industry"), STATUSES.get(t["status"]), t["created_at"][:10], t["updated_at"][:10],
                        iv.get("date"), iv.get("mode"), (t.get("interview_verification") or "").replace("_", " "),
                        hi.get("company"), hi.get("joining_date"), (t.get("hire_verification") or "").replace("_", " ")])
        return Response(content="\ufeff" + buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="jobradar-success-report.csv"'})

    @r.post("/admin/success/{tracker_id}/verify")
    async def admin_verify(tracker_id: str, req: VerifyReq, admin=Depends(require_admin)):
        if req.kind not in ("interview", "hire"):
            raise HTTPException(status_code=400, detail="Unknown outcome type")
        t = await db.job_tracker.find_one({"tracker_id": tracker_id}, {"_id": 0})
        if not t or not t.get(f"{req.kind}_verification"):
            raise HTTPException(status_code=400, detail="The candidate has not reported this outcome")
        await db.job_tracker.update_one({"tracker_id": tracker_id}, {"$set": {
            f"{req.kind}_verification": "verified" if req.verified else "candidate_reported",
            f"{req.kind}_verified_by": admin["user_id"] if req.verified else None,
            f"{req.kind}_verified_at": now_iso() if req.verified else None}})
        return {"ok": True}

    @r.get("/admin/success/evidence/{evidence_id}")
    async def admin_evidence(evidence_id: str, admin=Depends(require_admin)):
        e = await db.tracker_evidence.find_one({"evidence_id": evidence_id, "is_deleted": False}, {"_id": 0})
        if not e:
            raise HTTPException(status_code=404, detail="File not found")
        try:
            data = await asyncio.to_thread(_get_object, e["storage_path"])
        except Exception:
            raise HTTPException(status_code=502, detail="Could not load file")
        return Response(content=data, media_type=e["content_type"],
                        headers={"Content-Disposition": f'inline; filename="{e["evidence_id"]}"', "Cache-Control": "no-store"})

    return r
