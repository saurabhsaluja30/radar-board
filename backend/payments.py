"""Razorpay checkout for paid memberships (one-time payments, manual renewal).

A membership is activated only after the server has checked the payment itself: either the checkout signature plus
Razorpay's own record of the payment, or a signed webhook. Every path goes through `fulfil`, which claims the order
atomically, so a payment can never activate a membership twice (two replicas, a retried webhook, or verify and webhook
arriving together). Free accounts never touch this module.

Secrets (Emergent Secrets): RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET.
"""
import hashlib
import hmac
import json
import logging
import os
import uuid
from html import escape
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)
API = "https://api.razorpay.com/v1"
REOPENABLE = ["created", "failed", "cancelled"]


def _keys():
    return (os.environ.get("RAZORPAY_KEY_ID") or "").strip(), (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()


def payment_mode() -> dict:
    key_id, secret = _keys()
    if key_id and secret:
        return {"gateway": "razorpay", "test_mode": key_id.startswith("rzp_test_")}
    return {"gateway": "demo", "test_mode": True}


def signature_ok(message: bytes, signature: str, secret: str) -> bool:
    if not (signature and secret):
        return False
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _slim(p: dict) -> dict:
    """Keep only what reconciliation needs; never store card, bank or contact details."""
    return {k: p.get(k) for k in ("id", "status", "method", "amount", "currency", "captured", "order_id",
                                  "error_code", "error_description", "created_at")}


class OrderReq(BaseModel):
    plan_id: str


class VerifyReq(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class CancelReq(BaseModel):
    order_id: str


def build_router(db, get_current_user, require_admin, checkout_plan, activate, send_email, wrap_email,
                 now_iso, audit_log):
    r = APIRouter()

    async def rzp(method: str, path: str, body: Optional[dict] = None) -> dict:
        key_id, secret = _keys()
        if not (key_id and secret):
            raise HTTPException(503, "Online payments are not configured yet. Please try again later.")
        try:
            async with httpx.AsyncClient(timeout=20) as c:
                # RAZORPAY_API_BASE exists only so tests can point at a local stand-in; never set it in production.
                base = (os.environ.get("RAZORPAY_API_BASE") or API).rstrip("/")
                resp = await c.request(method, f"{base}{path}", auth=(key_id, secret), json=body)
        except httpx.HTTPError as e:
            logger.warning(f"razorpay {path}: {e}")
            raise HTTPException(502, "Could not reach the payment gateway. Please try again.")
        if resp.status_code >= 400:
            logger.warning(f"razorpay {path} -> {resp.status_code}: {resp.text[:300]}")
            raise HTTPException(502, "The payment gateway rejected the request. Please try again.")
        return resp.json()

    async def next_receipt_no() -> str:
        doc = await db.app_settings.find_one_and_update(
            {"key": "receipt_seq"}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
        return f"JR-{now_iso()[:7].replace('-', '')}-{int(doc['seq']):05d}"

    async def fulfil(order_id: str, payment: dict, via: str) -> dict:
        """Activate the membership for a captured payment. Idempotent and safe under concurrency."""
        pay = await db.payments.find_one({"order_id": order_id, "gateway": "razorpay"}, {"_id": 0})
        if not pay:
            raise HTTPException(404, "Order not found")
        if pay.get("subscription_id"):
            return pay
        ok = (payment.get("status") == "captured" and payment.get("order_id") == order_id
              and int(payment.get("amount") or 0) == int(pay["amount_paise"])
              and (payment.get("currency") or "INR") == pay.get("currency", "INR"))
        if not ok:
            await db.payments.update_one({"order_id": order_id, "subscription_id": None}, {"$set": {
                "mismatch": _slim(payment), "updated_at": now_iso()}})
            logger.error(f"razorpay payment {payment.get('id')} does not match order {order_id}; not activated")
            raise HTTPException(400, "Payment details do not match this order. Our team has been alerted.")
        claimed = await db.payments.find_one_and_update(
            {"order_id": order_id, "gateway": "razorpay", "subscription_id": None,
             "activation": {"$nin": ["running", "done"]}},
            {"$set": {"activation": "running", "status": "successful", "transaction_id": payment["id"],
                      "payment_date": now_iso(), "verified_via": via, "gateway_response": _slim(payment),
                      "updated_at": now_iso()}},
            return_document=ReturnDocument.AFTER)
        if not claimed:  # another request is activating it, or already did
            return await db.payments.find_one({"order_id": order_id}, {"_id": 0})
        try:
            m = await activate(pay["candidate_id"], pay["plan"], False, pay["payment_id"])
        except Exception:
            await db.payments.update_one({"order_id": order_id}, {"$set": {"activation": "failed"}})
            logger.exception(f"activation failed for order {order_id}")
            raise HTTPException(500, "Your payment was received but activation failed. Our team will fix this.")
        receipt = await next_receipt_no()
        await db.payments.update_one({"order_id": order_id}, {"$set": {
            "activation": "done", "subscription_id": m["subscription_id"], "receipt_no": receipt,
            "updated_at": now_iso()}})
        user = await db.users.find_one({"user_id": pay["candidate_id"]}, {"_id": 0, "email": 1, "full_name": 1})
        if user:
            inner = (f'<p style="color:#374151;font-size:15px">Hi {escape(user.get("full_name") or "there")},</p>'
                     f'<p style="color:#374151;font-size:15px">We received your payment of '
                     f'<strong>₹{pay["amount"]:,.0f}</strong> for the <strong>{escape(pay["plan_name"])}</strong>. '
                     f'Your membership is active until <strong>{escape(m["expiry_date"][:10])}</strong>.</p>'
                     f'<p style="color:#6b7280;font-size:13px">Receipt {receipt} · Payment ID {escape(payment["id"])}</p>')
            try:
                await send_email(candidate_id=pay["candidate_id"], to=user["email"], email_type="membership_activated",
                                 subject="Payment received: your JobRadar membership is active",
                                 html=wrap_email("Membership activated", inner))
            except Exception:
                logger.exception("confirmation email failed")
        return await db.payments.find_one({"order_id": order_id}, {"_id": 0})

    async def capture_and_fulfil(order_id: str, payment_id: str, via: str) -> dict:
        p = await rzp("GET", f"/payments/{payment_id}")
        if p.get("status") == "authorized" and p.get("order_id") == order_id:
            p = await rzp("POST", f"/payments/{payment_id}/capture",
                          {"amount": p["amount"], "currency": p.get("currency", "INR")})
        if p.get("status") != "captured":
            return {"status": p.get("status") or "pending"}
        return {"status": "successful", "payment": await fulfil(order_id, p, via)}

    def public(p: dict) -> dict:
        return {k: v for k, v in p.items() if k not in ("mismatch", "activation", "amount_paise")}

    # ------------------------------------------------------------------ candidate
    @r.post("/checkout/razorpay/order")
    async def create_order(req: OrderReq, user=Depends(get_current_user)):
        if payment_mode()["gateway"] != "razorpay":
            raise HTTPException(503, "Online payments are not configured yet. Please try again later.")
        plan = await checkout_plan(user, req.plan_id)
        paise = int(round(float(plan["price"]) * 100))
        internal = f"pay_{uuid.uuid4().hex[:14]}"
        order = await rzp("POST", "/orders", {
            "amount": paise, "currency": plan.get("currency", "INR"), "receipt": internal,
            "notes": {"candidate_id": user["user_id"], "plan_id": plan["plan_id"]}})
        await db.payments.insert_one({
            "payment_id": internal, "order_id": order["id"], "gateway": "razorpay", "is_demo": False,
            "candidate_id": user["user_id"], "plan_id": plan["plan_id"], "plan_name": plan["name"],
            "plan": {k: plan[k] for k in ("plan_id", "name", "duration_days")},
            "amount": float(plan["price"]), "amount_paise": paise, "currency": plan.get("currency", "INR"),
            "status": "created", "transaction_id": None, "subscription_id": None, "payment_date": None,
            "webhook_status": "pending", "refunds": [], "refunded_amount": 0,
            "created_at": now_iso(), "updated_at": now_iso()})
        return {"key_id": _keys()[0], "order_id": order["id"], "amount": paise, "currency": order.get("currency"),
                "plan_name": plan["name"], "payment_id": internal,
                "prefill": {"name": user.get("full_name") or "", "email": user.get("email") or "",
                            "contact": user.get("mobile") or ""}}

    @r.post("/checkout/razorpay/verify")
    async def verify(req: VerifyReq, user=Depends(get_current_user)):
        pay = await db.payments.find_one({"order_id": req.razorpay_order_id, "candidate_id": user["user_id"],
                                          "gateway": "razorpay"}, {"_id": 0})
        if not pay:
            raise HTTPException(404, "Order not found")
        msg = f"{req.razorpay_order_id}|{req.razorpay_payment_id}".encode()
        if not signature_ok(msg, req.razorpay_signature, _keys()[1]):
            await db.payments.update_one({"order_id": req.razorpay_order_id}, {"$set": {
                "bad_signature_at": now_iso()}})
            raise HTTPException(400, "We could not verify this payment. If money was deducted, it will be "
                                     "confirmed automatically or refunded by Razorpay.")
        res = await capture_and_fulfil(req.razorpay_order_id, req.razorpay_payment_id, "checkout")
        if res["status"] != "successful":
            return {"status": "pending", "message": "Your payment is being confirmed. This usually takes a minute."}
        return {"status": "successful", "payment": public(res["payment"])}

    @r.post("/checkout/razorpay/cancel")
    async def cancel(req: CancelReq, user=Depends(get_current_user)):
        await db.payments.update_one({"order_id": req.order_id, "candidate_id": user["user_id"],
                                      "status": "created"}, {"$set": {"status": "cancelled", "updated_at": now_iso()}})
        return {"success": True}

    @r.get("/payments/{payment_id}/receipt")
    async def receipt(payment_id: str, user=Depends(get_current_user)):
        p = await db.payments.find_one({"payment_id": payment_id, "candidate_id": user["user_id"],
                                        "status": {"$in": ["successful", "refunded", "partially_refunded"]}},
                                       {"_id": 0})
        if not p:
            raise HTTPException(404, "Receipt not found")
        sub = await db.subscriptions.find_one({"subscription_id": p.get("subscription_id")},
                                              {"_id": 0, "start_date": 1, "expiry_date": 1})
        return {"receipt": {**public(p), "candidate_name": user.get("full_name"), "candidate_email": user.get("email"),
                            "valid_from": (sub or {}).get("start_date"), "valid_until": (sub or {}).get("expiry_date"),
                            "issuer": "JobRadar by EvolveMinds"}}

    # ------------------------------------------------------------------ webhook
    @r.post("/payments/razorpay/webhook")
    async def webhook(request: Request):
        secret = (os.environ.get("RAZORPAY_WEBHOOK_SECRET") or "").strip()
        body = await request.body()
        if not secret:
            raise HTTPException(503, "Webhook not configured")
        if not signature_ok(body, request.headers.get("x-razorpay-signature", ""), secret):
            raise HTTPException(400, "Invalid signature")
        evt = json.loads(body or b"{}")
        event_id = request.headers.get("x-razorpay-event-id") or hashlib.sha256(body).hexdigest()
        try:
            await db.payment_webhooks.insert_one({"event_id": event_id, "event": evt.get("event"),
                                                  "received_at": now_iso(), "status": "processing"})
        except DuplicateKeyError:
            return {"status": "duplicate"}
        result = "ignored"
        try:
            payload = evt.get("payload") or {}
            p = (payload.get("payment") or {}).get("entity") or {}
            name = evt.get("event")
            if name in ("payment.captured", "order.paid") and p.get("order_id"):
                if await db.payments.find_one({"order_id": p["order_id"], "gateway": "razorpay"}, {"_id": 1}):
                    await fulfil(p["order_id"], p, "webhook")
                    await db.payments.update_one({"order_id": p["order_id"]}, {"$set": {"webhook_status": "received"}})
                    result = "fulfilled"
            elif name == "payment.failed" and p.get("order_id"):
                await db.payments.update_one(
                    {"order_id": p["order_id"], "status": {"$in": ["created", "cancelled"]}},
                    {"$set": {"status": "failed", "gateway_response": _slim(p), "webhook_status": "received",
                              "failure_reason": p.get("error_description"), "updated_at": now_iso()}})
                result = "failed"
            elif name in ("refund.created", "refund.processed", "refund.failed"):
                ref = (payload.get("refund") or {}).get("entity") or {}
                result = await record_refund(ref)
        except HTTPException as e:
            result = f"error: {e.detail}"
        except Exception as e:  # keep the event so it can be inspected; Razorpay retries non-2xx anyway
            logger.exception("razorpay webhook")
            await db.payment_webhooks.update_one({"event_id": event_id}, {"$set": {"status": f"error: {e}"[:200]}})
            raise HTTPException(500, "Webhook processing failed")
        await db.payment_webhooks.update_one({"event_id": event_id}, {"$set": {"status": result}})
        return {"status": result}

    async def record_refund(ref: dict) -> str:
        pay = await db.payments.find_one({"transaction_id": ref.get("payment_id"), "gateway": "razorpay"}, {"_id": 0})
        if not pay or not ref.get("id"):
            return "refund for unknown payment"
        refunds = [x for x in pay.get("refunds", []) if x.get("id") != ref["id"]]
        refunds.append({"id": ref["id"], "amount": (ref.get("amount") or 0) / 100, "status": ref.get("status"),
                        "at": now_iso()})
        done = sum(x["amount"] for x in refunds if x.get("status") in ("processed", "created", "pending"))
        status = pay["status"]
        if pay["status"] in ("successful", "refunded", "partially_refunded"):
            status = "refunded" if done >= pay["amount"] else "partially_refunded" if done > 0 else "successful"
        await db.payments.update_one({"payment_id": pay["payment_id"]}, {"$set": {
            "refunds": refunds, "refunded_amount": done, "status": status, "updated_at": now_iso()}})
        return f"refund {ref.get('status')}"

    # ------------------------------------------------------------------ admin
    @r.post("/admin/payments/{payment_id}/reconcile")
    async def reconcile(payment_id: str, admin=Depends(require_admin)):
        pay = await db.payments.find_one({"payment_id": payment_id, "gateway": "razorpay"}, {"_id": 0})
        if not pay:
            raise HTTPException(404, "Razorpay payment not found")
        items = (await rzp("GET", f"/orders/{pay['order_id']}/payments")).get("items", [])
        captured = next((p for p in items if p.get("status") == "captured"), None)
        if captured:
            out = await fulfil(pay["order_id"], captured, "reconcile")
            outcome = "activated" if not pay.get("subscription_id") else "already active"
        elif items and all(p.get("status") == "failed" for p in items):
            await db.payments.update_one({"payment_id": payment_id, "status": {"$in": REOPENABLE}},
                                         {"$set": {"status": "failed", "updated_at": now_iso()}})
            out, outcome = await db.payments.find_one({"payment_id": payment_id}, {"_id": 0}), "no successful payment"
        else:
            out, outcome = pay, ("no payment attempt yet" if not items else "payment still processing")
        await audit_log(admin, "reconcile_payment", "payment", payment_id, {"outcome": outcome})
        return {"outcome": outcome, "payment": public(out)}

    @r.get("/admin/payments/summary")
    async def summary(admin=Depends(require_admin)):
        rows = await db.payments.aggregate([
            {"$match": {"is_demo": {"$ne": True}}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}, "amount": {"$sum": "$amount"},
                        "refunded": {"$sum": {"$ifNull": ["$refunded_amount", 0]}}}}]).to_list(20)
        stuck = await db.payments.count_documents({"gateway": "razorpay", "status": "successful",
                                                   "subscription_id": None})
        return {"by_status": {x["_id"]: {"count": x["count"], "amount": x["amount"], "refunded": x["refunded"]}
                              for x in rows},
                "needs_attention": stuck, "mode": payment_mode(),
                "webhook_configured": bool((os.environ.get("RAZORPAY_WEBHOOK_SECRET") or "").strip())}

    return r


async def ensure_indexes(db):
    await db.payment_webhooks.create_index("event_id", unique=True)
    await db.payments.create_index("order_id")
    await db.payments.create_index("transaction_id")
    await db.payments.create_index([("candidate_id", 1), ("created_at", -1)])
