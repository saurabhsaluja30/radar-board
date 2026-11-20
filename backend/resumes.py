"""Candidate resume upload, background parsing, confirmation, deletion, and the Admin Candidate Talent Database.

Resume files are encrypted with a per-file key before they reach object storage (see storage.py). Deleting a
resume destroys its key, so the stored bytes can never be read again even though the storage API has no delete.
"""
import asyncio
import base64
import csv
import hashlib
import hmac
import io
import logging
import os
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ops import tracked
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from pymongo import ReturnDocument

import storage
from career import file_to_text
from resume_parse import extract, keywords
from smartmatch import NOTICE_DAYS, norm_skill, profile_status

logger = logging.getLogger("jobradar.resumes")

DEFAULT_SETTINGS = {"uploads_enabled": False, "max_mb": 2.0, "outdated_months": 12}
TYPES = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_ATTEMPTS = 3
LOCK_MINUTES = 5
RETRY_BATCH = 10
PERMISSIONS = ["view_resumes", "export_candidates"]

# Fields a candidate may confirm from their resume, with how each is stored on the user profile.
CONFIRMABLE = {
    "mobile": "str", "current_location": "str", "current_company": "str", "current_designation": "str",
    "total_experience": "years", "relevant_experience": "years", "current_salary": "str", "expected_ctc": "money",
    "notice_period": "notice", "highest_qualification": "str", "institution": "str",
    "primary_skills": "list", "tools": "list", "certifications": "list", "previous_companies": "list",
    "industry_experience": "list", "employment_history": "history",
}
# Parser output key → profile field.
EXTRACT_TO_PROFILE = {"phone": "mobile", "skills": "primary_skills", "current_ctc": "current_salary"}


class ConfirmReq(BaseModel):
    fields: Dict[str, Any]


class SettingsReq(BaseModel):
    uploads_enabled: bool
    max_mb: float
    outdated_months: int


def _clean_list(v) -> List[str]:
    if isinstance(v, str):
        v = re.split(r"[,;\n]", v)
    return list(dict.fromkeys(str(x).strip()[:100] for x in (v or []) if str(x).strip()))[:40]


def _coerce(field: str, kind: str, v):
    if v in (None, "", []):
        return None
    if kind == "str":
        return str(v).strip()[:160]
    if kind in ("years", "money"):
        mult = 1
        if kind == "money" and isinstance(v, str):
            low = v.lower()
            mult = 10000000 if re.search(r"\bcr|crore", low) else 100000 if re.search(r"lpa|lakh|lac", low) \
                else 1000 if re.search(r"\d\s*k\b", low) else 1
        try:
            n = float(re.sub(r"[^\d.]", "", str(v)) if isinstance(v, str) else v) * mult
        except ValueError:
            raise HTTPException(400, f"{field.replace('_', ' ').capitalize()} must be a number")
        if kind == "years" and not 0 <= n <= 60:
            raise HTTPException(400, f"{field.replace('_', ' ').capitalize()} must be between 0 and 60 years")
        if n < 0:
            raise HTTPException(400, f"{field.replace('_', ' ').capitalize()} cannot be negative")
        return n
    if kind == "notice":
        if v not in NOTICE_DAYS:
            raise HTTPException(400, "Invalid notice period")
        return v
    if kind == "list":
        items = _clean_list(v)
        return [norm_skill(x) for x in items] if field == "primary_skills" else items
    if kind == "history":
        out = []
        for e in (v or [])[:15]:
            if isinstance(e, dict):
                out.append({k: str(e.get(k) or "").strip()[:80] for k in ("title", "company", "start", "end")})
        return out
    return None


def validate_file(name: str, data: bytes) -> str:
    """Return "pdf" or "docx", or raise 400. Checks real file content, not just the name."""
    if data[:5] == b"%PDF-":
        head = data[:400000]
        if re.search(rb"/Encrypt\b", head):
            raise HTTPException(400, "This PDF is password-protected. Please upload an unlocked copy.")
        if re.search(rb"/(?:JavaScript|JS|Launch|EmbeddedFile|RichMedia)\b", data):
            raise HTTPException(400, "This PDF contains scripts or attachments and can't be accepted. "
                                     "Please export a plain PDF.")
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if sum(i.file_size for i in z.infolist()) > 30 * 1024 * 1024:
                    raise HTTPException(400, "This Word file is not valid.")
        except zipfile.BadZipFile:
            raise HTTPException(400, "This Word file is damaged. Please upload a valid .docx file.")
        if "word/document.xml" not in names:
            raise HTTPException(400, "Please upload a PDF or Word (.docx) file.")
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            raise HTTPException(400, "Word files with macros can't be accepted. Please save as a normal .docx.")
        return "docx"
    raise HTTPException(400, "Please upload a PDF or Word (.docx) file. Older .doc files: save as .docx first.")


def build_router(db, get_current_user, require_admin, audit_log, now_iso, bg, on_profile_change=None):
    r = APIRouter()
    work_gate = asyncio.Semaphore(1)  # one parse at a time per replica (Starter: 0.25 vCPU burst)

    def now_dt() -> datetime:
        return datetime.now(timezone.utc)

    async def settings() -> dict:
        s = await db.app_settings.find_one({"key": "resumes"}, {"_id": 0}) or {}
        return {k: s.get(k, v) for k, v in DEFAULT_SETTINGS.items()}

    def public(rec: dict) -> dict:
        return {k: v for k, v in rec.items() if k not in ("enc_key", "storage_path", "lock_until", "_id")}

    async def require_candidate(user=Depends(get_current_user)):
        if user.get("role") != "candidate":
            raise HTTPException(403, "Only candidates can manage resumes")
        return user

    def require_perm(perm: str):
        async def dep(admin=Depends(require_admin)):
            # Admins created before permissions existed (no field) keep full access.
            if "permissions" in admin and perm not in (admin.get("permissions") or []):
                raise HTTPException(403, "You don't have permission for this action")
            return admin
        return dep

    async def refresh_user_resume_fields(uid: str):
        cur = await db.candidate_resumes.find_one({"candidate_id": uid, "is_current": True, "status": {"$ne": "deleted"}},
                                                  {"_id": 0, "uploaded_at": 1, "extracted": 1})
        await db.users.update_one({"user_id": uid}, {"$set": {
            "has_resume": bool(cur), "resume_uploaded_at": (cur or {}).get("uploaded_at"),
            "resume_keywords": keywords((cur or {}).get("extracted") or {})}})

    async def set_completion(uid: str):
        u = await db.users.find_one({"user_id": uid}, {"_id": 0, "password": 0})
        if u:
            await db.users.update_one({"user_id": uid}, {"$set": {"profile_completion": profile_status(u)["completion"]}})

    # ------------------------------------------------------------------ background parsing
    async def claim(statuses: List[str]) -> Optional[dict]:
        """Atomically take one resume to parse. The lock means only one replica works on a file."""
        now = now_dt()
        return await db.candidate_resumes.find_one_and_update(
            {"status": {"$in": statuses}, "attempts": {"$lt": MAX_ATTEMPTS},
             "$or": [{"lock_until": None}, {"lock_until": {"$lt": now}}]},
            {"$set": {"status": "processing", "lock_until": now + timedelta(minutes=LOCK_MINUTES)}, "$inc": {"attempts": 1}},
            sort=[("uploaded_at", 1)], projection={"_id": 0}, return_document=ReturnDocument.AFTER)

    async def parse_one(rec: dict):
        try:
            blob = await asyncio.to_thread(storage._get_object, rec["storage_path"])
            data = storage.decrypt(base64.b64decode(rec["enc_key"]), blob)
            text = await asyncio.to_thread(file_to_text, f"x.{rec['file_type']}", data)
            fields = await asyncio.to_thread(extract, text)
            res = await db.candidate_resumes.update_one(
                {"resume_id": rec["resume_id"], "status": "processing"},
                {"$set": {"status": "parsed", "extracted": fields, "parsed_at": now_iso(), "error": None, "lock_until": None,
                          "text_chars": len(text)}})
            if res.modified_count and rec.get("is_current"):
                await refresh_user_resume_fields(rec["candidate_id"])
        except Exception as e:  # noqa: BLE001 - recorded on the record and retried by the cron
            msg = getattr(e, "detail", None) or f"{type(e).__name__}: {str(e)[:160]}"
            logger.warning(f"resume parse failed {rec['resume_id']}: {msg}")
            await db.candidate_resumes.update_one({"resume_id": rec["resume_id"], "status": "processing"},
                                                  {"$set": {"status": "failed", "error": str(msg)[:200], "lock_until": None}})

    async def drain(statuses: List[str], limit: int):
        async with work_gate:
            for _ in range(limit):
                rec = await claim(statuses)
                if not rec:
                    return
                await parse_one(rec)

    # ------------------------------------------------------------------ candidate
    @r.get("/resume/config")
    async def resume_config():
        s = await settings()
        return {"uploads_enabled": s["uploads_enabled"], "max_mb": s["max_mb"], "types": list(TYPES)}

    @r.get("/resume")
    async def my_resumes(user=Depends(require_candidate)):
        recs = await db.candidate_resumes.find({"candidate_id": user["user_id"], "status": {"$ne": "deleted"}},
                                               {"_id": 0, "enc_key": 0, "storage_path": 0, "lock_until": 0}
                                               ).sort("version", -1).to_list(20)
        s = await settings()
        return {"resumes": recs, "current": next((x for x in recs if x.get("is_current")), None),
                "confirmed_fields": user.get("confirmed_fields") or [],
                "talent_db_consent": user.get("talent_db_consent") is True,
                "uploads_enabled": s["uploads_enabled"], "max_mb": s["max_mb"]}

    @r.post("/resume/upload")
    async def upload(file: UploadFile = File(...), user=Depends(require_candidate)):
        s = await settings()
        if not s["uploads_enabled"]:
            raise HTTPException(503, "Resume uploads are not available yet. Please try again later.")
        limit = int(s["max_mb"] * 1024 * 1024)
        data = await file.read(limit + 1)
        if not data:
            raise HTTPException(400, "The uploaded file is empty.")
        if len(data) > limit:
            raise HTTPException(400, f"File is too large. Please upload a file under {s['max_mb']:g} MB.")
        ftype = validate_file(file.filename or "", data)
        uid = user["user_id"]
        digest = hashlib.sha256(data).hexdigest()
        same = await db.candidate_resumes.find_one({"candidate_id": uid, "sha256": digest, "status": {"$ne": "deleted"}},
                                                   {"_id": 0, "enc_key": 0, "storage_path": 0, "lock_until": 0})
        if same:
            if not same.get("is_current"):
                await db.candidate_resumes.update_many({"candidate_id": uid, "is_current": True}, {"$set": {"is_current": False}})
                await db.candidate_resumes.update_one({"resume_id": same["resume_id"]}, {"$set": {"is_current": True}})
                await refresh_user_resume_fields(uid)
                same["is_current"] = True
            return {"resume": same, "duplicate": True}
        key = storage.new_key()
        rid = f"rs_{uuid.uuid4().hex[:12]}"
        path = f"{storage.APP_NAME}/resumes/{uid}/{uuid.uuid4().hex}.bin"
        try:
            await asyncio.to_thread(storage._put_object, path, storage.encrypt(key, data), "application/octet-stream")
        except Exception as e:
            logger.warning(f"resume upload to storage failed: {e}")
            raise HTTPException(502, "Upload failed. Please try again.")
        last = await db.candidate_resumes.find_one({"candidate_id": uid}, {"_id": 0, "version": 1}, sort=[("version", -1)])
        rec = {"resume_id": rid, "candidate_id": uid, "version": ((last or {}).get("version") or 0) + 1, "is_current": True,
               "original_filename": re.sub(r"[^\w .()-]", "_", file.filename or f"resume.{ftype}")[:120],
               "file_type": ftype, "content_type": TYPES[ftype], "size": len(data), "sha256": digest,
               "storage_path": path, "enc_key": base64.b64encode(key).decode(), "status": "queued", "attempts": 0,
               "lock_until": None, "error": None, "extracted": {}, "uploaded_at": now_iso(), "parsed_at": None,
               "confirmed_at": None, "deleted_at": None}
        await db.candidate_resumes.update_many({"candidate_id": uid, "is_current": True}, {"$set": {"is_current": False}})
        await db.candidate_resumes.insert_one(dict(rec))
        await refresh_user_resume_fields(uid)
        bg(drain(["queued"], 3))
        return {"resume": public(rec), "duplicate": False}

    async def own(rid: str, uid: str) -> dict:
        rec = await db.candidate_resumes.find_one({"resume_id": rid, "candidate_id": uid, "status": {"$ne": "deleted"}}, {"_id": 0})
        if not rec:
            raise HTTPException(404, "Resume not found")
        return rec

    async def file_response(rec: dict, download: bool) -> Response:
        if not rec.get("enc_key"):
            raise HTTPException(404, "Resume not found")
        try:
            blob = await asyncio.to_thread(storage._get_object, rec["storage_path"])
            data = storage.decrypt(base64.b64decode(rec["enc_key"]), blob)
        except Exception:
            raise HTTPException(502, "Could not load the resume file")
        disp = "attachment" if download else "inline"
        return Response(content=data, media_type=rec["content_type"], headers={
            "Content-Disposition": f'{disp}; filename="{rec["original_filename"]}"',
            "Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"})

    @r.get("/resume/{rid}/file")
    async def my_file(rid: str, download: bool = False, user=Depends(require_candidate)):
        return await file_response(await own(rid, user["user_id"]), download)

    @r.post("/resume/{rid}/confirm")
    async def confirm(rid: str, req: ConfirmReq, user=Depends(require_candidate)):
        rec = await own(rid, user["user_id"])
        if rec["status"] not in ("parsed", "confirmed"):
            raise HTTPException(409, "This resume hasn't finished processing yet")
        updates: dict = {}
        for k, v in (req.fields or {}).items():
            k = EXTRACT_TO_PROFILE.get(k, k)
            if k in CONFIRMABLE:
                val = _coerce(k, CONFIRMABLE[k], v)
                if val is not None:
                    updates[k] = val
        if not updates:
            raise HTTPException(400, "Nothing to save")
        confirmed = sorted(set(user.get("confirmed_fields") or []) | set(updates))
        await db.users.update_one({"user_id": user["user_id"]},
                                  {"$set": {**updates, "confirmed_fields": confirmed, "updated_at": now_iso()}})
        await db.candidate_resumes.update_one({"resume_id": rid}, {"$set": {"status": "confirmed", "confirmed_at": now_iso()}})
        await set_completion(user["user_id"])
        if on_profile_change:
            await on_profile_change(user["user_id"], "resume details confirmed")
        return {"ok": True, "saved": sorted(updates), "confirmed_fields": confirmed}

    async def shred(rec: dict) -> str:
        how = "already_removed"
        try:
            how = await asyncio.to_thread(storage.delete_object, rec["storage_path"])
        except Exception as e:  # noqa: BLE001 - the key is destroyed regardless, so the file stays unreadable
            logger.warning(f"resume object removal failed {rec['resume_id']}: {e}")
            how = "key_destroyed_only"
        await db.candidate_resumes.update_one({"resume_id": rec["resume_id"]}, {
            "$set": {"status": "deleted", "is_current": False, "deleted_at": now_iso(), "extracted": {}, "storage_removal": how},
            "$unset": {"enc_key": "", "sha256": ""}})
        return how

    async def promote_latest(uid: str):
        nxt = await db.candidate_resumes.find_one({"candidate_id": uid, "status": {"$ne": "deleted"}}, {"_id": 0, "resume_id": 1},
                                                  sort=[("version", -1)])
        if nxt:
            await db.candidate_resumes.update_one({"resume_id": nxt["resume_id"]}, {"$set": {"is_current": True}})
        await refresh_user_resume_fields(uid)

    @r.delete("/resume/{rid}")
    async def delete_one(rid: str, user=Depends(require_candidate)):
        rec = await own(rid, user["user_id"])
        await shred(rec)
        if rec.get("is_current"):
            await promote_latest(user["user_id"])
        return {"ok": True}

    @r.delete("/resume")
    async def delete_all(user=Depends(require_candidate)):
        recs = await db.candidate_resumes.find({"candidate_id": user["user_id"], "status": {"$ne": "deleted"}}, {"_id": 0}).to_list(100)
        for rec in recs:
            await shred(rec)
        await refresh_user_resume_fields(user["user_id"])
        return {"ok": True, "deleted": len(recs)}

    # ------------------------------------------------------------------ cron: retry failed / stuck parses
    @r.post("/cron/resume-retry")
    async def cron_retry(request: Request, authorization: Optional[str] = Header(None), x_webhook_id: Optional[str] = Header(None)):
        secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
        token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not secret or not hmac.compare_digest(token, secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            body = await request.json()
        except Exception:
            body = {}
        run_id = x_webhook_id or (body or {}).get("run_id") or uuid.uuid4().hex
        res = await db.cron_runs.update_one({"run_id": run_id}, {"$setOnInsert": {
            "run_id": run_id, "name": "resume-retry", "created_at": now_iso()}}, upsert=True)
        if res.upserted_id is not None:
            # "processing" with an expired lock = a replica stopped mid-parse.
            bg(tracked("resume-retry", drain(["queued", "failed", "processing"], RETRY_BATCH)))
        return {"accepted": True}

    # ------------------------------------------------------------------ admin: settings + storage
    @r.get("/admin/resumes/settings")
    async def get_settings(admin=Depends(require_admin)):
        return await settings()

    @r.put("/admin/resumes/settings")
    async def put_settings(req: SettingsReq, admin=Depends(require_admin)):
        if not 0.1 <= req.max_mb <= 10:
            raise HTTPException(400, "Upload limit must be between 0.1 and 10 MB")
        if not 1 <= req.outdated_months <= 60:
            raise HTTPException(400, "Outdated after must be between 1 and 60 months")
        val = req.dict()
        await db.app_settings.update_one({"key": "resumes"}, {"$set": {"key": "resumes", **val}}, upsert=True)
        await audit_log(admin, "update_resume_settings", "settings", "resumes", val)
        return val

    @r.get("/admin/storage/status")
    async def storage_status(admin=Depends(require_admin)):
        check = await asyncio.to_thread(storage.check_storage)
        agg = lambda coll, match: getattr(db, coll).aggregate([  # noqa: E731
            {"$match": match}, {"$group": {"_id": None, "n": {"$sum": 1}, "bytes": {"$sum": "$size"}}}]).to_list(1)
        res = (await agg("candidate_resumes", {"status": {"$ne": "deleted"}}) or [{}])[0]
        ev = (await agg("tracker_evidence", {"is_deleted": {"$ne": True}}) or [{}])[0]
        by_status = {d["_id"]: d["n"] for d in await db.candidate_resumes.aggregate(
            [{"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(None)}
        return {**check, "resume_files": res.get("n", 0), "resume_bytes": res.get("bytes", 0),
                "evidence_files": ev.get("n", 0), "evidence_bytes": ev.get("bytes", 0),
                "total_bytes": res.get("bytes", 0) + ev.get("bytes", 0), "by_status": by_status,
                "note": "Totals are counted from JobRadar's own records. The storage provider's quota isn't available "
                        "through its API — confirm it with Emergent.", **(await settings())}

    # ------------------------------------------------------------------ admin: talent database
    def rx(v: str) -> dict:
        return {"$regex": re.escape(v.strip()), "$options": "i"}

    def talent_query(f: dict) -> dict:
        q: dict = {"role": "candidate", "talent_db_consent": True, "suspended": {"$ne": True}}
        conds: List[dict] = []
        if f.get("name"):
            q["full_name"] = rx(f["name"])
        for key, field in (("designation", "current_designation"), ("company", "current_company"),
                           ("current_location", "current_location"), ("institution", "institution"),
                           ("current_ctc", "current_salary")):
            if f.get(key):
                q[field] = rx(f[key])
        if f.get("industry") and f["industry"] != "All":
            conds.append({"$or": [{"industry": f["industry"]}, {"industry_experience": f["industry"]}]})
        if f.get("preferred_designation"):
            conds.append({"$or": [{"preferred_designation": rx(f["preferred_designation"])},
                                  {"preferred_titles": rx(f["preferred_designation"])}]})
        if f.get("preferred_location"):
            conds.append({"$or": [{"preferred_location": rx(f["preferred_location"])},
                                  {"preferred_locations": rx(f["preferred_location"])}]})
        if f.get("preferred_country"):
            conds.append({"$or": [{"preferred_country": rx(f["preferred_country"])},
                                  {"preferred_countries": rx(f["preferred_country"])}]})
        if f.get("work_mode") and f["work_mode"] != "All":
            q["preferred_work_mode"] = f["work_mode"]
        if f.get("notice_period") and f["notice_period"] != "All":
            q["notice_period"] = f["notice_period"]
        if f.get("education") and f["education"] != "All":
            q["highest_qualification"] = f["education"]
        if f.get("certification"):
            q["certifications"] = rx(f["certification"])
        for key in ("skills", "tools", "keyword"):
            for term in [t for t in re.split(r"[,;]", f.get(key) or "") if t.strip()]:
                t = term.strip()
                conds.append({"$or": [{"resume_keywords": t.lower()}, {"resume_keywords": norm_skill(t)},
                                      {"primary_skills": rx(t)}, {"secondary_skills": rx(t)}, {"tools": rx(t)}]
                              + ([{"current_designation": rx(t)}, {"current_company": rx(t)},
                                  {"certifications": rx(t)}] if key == "keyword" else [])})
        for key, field in (("exp", "total_experience"), ("rel_exp", "relevant_experience"), ("ectc", "expected_ctc")):
            rng = {}
            if f.get(f"min_{key}") not in (None, ""):
                rng["$gte"] = float(f[f"min_{key}"])
            if f.get(f"max_{key}") not in (None, ""):
                rng["$lte"] = float(f[f"max_{key}"])
            if rng:
                q[field] = rng
        if f.get("has_resume") in ("yes", "no"):
            q["has_resume"] = True if f["has_resume"] == "yes" else {"$ne": True}
        if f.get("outdated") == "yes":
            months = int(f.get("_outdated_months") or 12)
            q["has_resume"] = True
            q["resume_uploaded_at"] = {"$lt": (now_dt() - timedelta(days=30 * months)).isoformat()}
        if f.get("profile") in ("complete", "incomplete"):
            q["profile_completion"] = 100 if f["profile"] == "complete" else {"$lt": 100}
        reg = {}
        if f.get("registered_from"):
            reg["$gte"] = f["registered_from"]
        if f.get("registered_to"):
            reg["$lte"] = f["registered_to"] + "T23:59:59"
        if reg:
            q["created_at"] = reg
        if conds:
            q["$and"] = conds
        return q

    LIST_FIELDS = {"_id": 0, "user_id": 1, "full_name": 1, "email": 1, "mobile": 1, "industry": 1, "current_designation": 1,
                   "current_company": 1, "total_experience": 1, "relevant_experience": 1, "current_location": 1,
                   "preferred_location": 1, "preferred_locations": 1, "preferred_work_mode": 1, "notice_period": 1,
                   "current_salary": 1, "expected_ctc": 1, "expected_ctc_currency": 1, "primary_skills": 1, "tools": 1,
                   "highest_qualification": 1, "has_resume": 1, "resume_uploaded_at": 1, "profile_completion": 1,
                   "created_at": 1}

    async def filters_with_settings(params: dict) -> dict:
        f = {k: v for k, v in params.items() if v not in (None, "")}
        f["_outdated_months"] = (await settings())["outdated_months"]
        return f

    @r.get("/admin/talent")
    async def talent_search(request: Request, page: int = 1, page_size: int = Query(25, le=100),
                            admin=Depends(require_admin)):
        f = await filters_with_settings(dict(request.query_params))
        try:
            q = talent_query(f)
        except ValueError:
            raise HTTPException(400, "Experience and CTC filters must be numbers")
        total = await db.users.count_documents(q)
        rows = await db.users.find(q, LIST_FIELDS).sort("created_at", -1).skip((max(page, 1) - 1) * page_size).limit(page_size).to_list(page_size)
        months = f["_outdated_months"]
        cutoff = (now_dt() - timedelta(days=30 * months)).isoformat()
        for u in rows:
            u["resume_outdated"] = bool(u.get("has_resume") and (u.get("resume_uploaded_at") or "") < cutoff)
        return {"candidates": rows, "total": total, "page": page, "page_size": page_size,
                "consented_total": await db.users.count_documents({"role": "candidate", "talent_db_consent": True})}

    @r.get("/admin/talent/export")
    async def talent_export(request: Request, admin=Depends(require_perm("export_candidates"))):
        f = await filters_with_settings(dict(request.query_params))
        rows = await db.users.find(talent_query(f), LIST_FIELDS).sort("created_at", -1).to_list(5000)
        cols = [c for c in LIST_FIELDS if c not in ("_id",)]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for u in rows:
            w.writerow(["; ".join(map(str, u.get(c))) if isinstance(u.get(c), list) else u.get(c, "") for c in cols])
        await audit_log(admin, "export_talent_database", "candidate", "-", {"rows": len(rows),
                        "filters": {k: v for k, v in f.items() if not k.startswith("_")}})
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": 'attachment; filename="talent_database.csv"', "Cache-Control": "no-store"})

    async def consented(cid: str) -> dict:
        u = await db.users.find_one({"user_id": cid, "role": "candidate", "talent_db_consent": True}, {"_id": 0, "password": 0})
        if not u:
            raise HTTPException(404, "Candidate not found or hasn't consented to the talent database")
        return u

    @r.get("/admin/talent/{cid}")
    async def talent_detail(cid: str, admin=Depends(require_admin)):
        u = await consented(cid)
        recs = await db.candidate_resumes.find({"candidate_id": cid, "status": {"$ne": "deleted"}},
                                               {"_id": 0, "enc_key": 0, "storage_path": 0, "lock_until": 0, "sha256": 0}
                                               ).sort("version", -1).to_list(20)
        return {"candidate": {**u, **profile_status(u)}, "resumes": recs}

    @r.get("/admin/talent/{cid}/resume/{rid}")
    async def talent_resume(cid: str, rid: str, download: bool = False, admin=Depends(require_perm("view_resumes"))):
        await consented(cid)
        rec = await db.candidate_resumes.find_one({"resume_id": rid, "candidate_id": cid, "status": {"$ne": "deleted"}}, {"_id": 0})
        if not rec:
            raise HTTPException(404, "Resume not found")
        resp = await file_response(rec, download)
        await audit_log(admin, "download_resume" if download else "view_resume", "candidate", cid,
                        {"resume_id": rid, "version": rec.get("version")})
        return resp

    return r, {"set_completion": set_completion, "permissions": PERMISSIONS}
