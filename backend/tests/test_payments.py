# Phase 1: membership catalogue, Razorpay checkout (order, verify, webhook, refunds) and free-tier protection.
# Runs its own backend on port 8011 with test Razorpay keys, pointed at a local stand-in for the Razorpay API,
# so no real payment gateway is contacted.
import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from pymongo import MongoClient

HERE = next(p for p in ("/app/backend", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if os.path.exists(os.path.join(p, "server.py")))
sys.path.insert(0, HERE)
from payments import signature_ok  # noqa: E402

PORT, FAKE_PORT = 8011, 8790
API = f"http://127.0.0.1:{PORT}/api"
KEY_ID, KEY_SECRET, HOOK_SECRET = "rzp_test_phase1", "test_secret_phase1", "hook_secret_phase1"
CATALOGUE = {"monthly": (599, 30), "quarterly": (1499, 90), "half_yearly": (1999, 180), "annual": (2499, 365)}


def _env(key):
    if os.environ.get(key):
        return os.environ[key]
    for line in open(os.path.join(HERE, ".env")):
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')


# --------------------------------------------------------------------------- local Razorpay stand-in
ORDERS, PAYMENTS = {}, {}


class FakeRazorpay(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/v1/orders":
            oid = f"order_{uuid.uuid4().hex[:14]}"
            ORDERS[oid] = {"id": oid, "amount": body["amount"], "currency": body["currency"], "notes": body["notes"]}
            return self._send(200, ORDERS[oid])
        if self.path.endswith("/capture"):
            pid = self.path.split("/")[3]
            PAYMENTS[pid]["status"] = "captured"
            return self._send(200, PAYMENTS[pid])
        self._send(404, {"error": "not found"})

    def do_GET(self):
        parts = self.path.split("/")
        if self.path.startswith("/v1/payments/") and parts[3] in PAYMENTS:
            return self._send(200, PAYMENTS[parts[3]])
        if self.path.startswith("/v1/orders/") and self.path.endswith("/payments"):
            return self._send(200, {"items": [p for p in PAYMENTS.values() if p["order_id"] == parts[3]]})
        self._send(404, {"error": "not found"})


def fake_payment(order_id, status="captured", amount=None):
    pid = f"pay_{uuid.uuid4().hex[:14]}"
    PAYMENTS[pid] = {"id": pid, "order_id": order_id, "status": status, "method": "card", "captured": status == "captured",
                     "amount": ORDERS[order_id]["amount"] if amount is None else amount, "currency": "INR"}
    return pid


def sign(order_id, payment_id):
    return hmac.new(KEY_SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- unit
def test_signature_check():
    sig = hmac.new(b"s", b"o|p", hashlib.sha256).hexdigest()
    assert signature_ok(b"o|p", sig, "s")
    assert not signature_ok(b"o|p", sig, "other")
    assert not signature_ok(b"o|q", sig, "s")
    assert not signature_ok(b"o|p", "", "s")


def test_plan_tiers():
    from server import plan_tier
    assert [plan_tier(d) for d in (30, 90, 180, 365)] == ["monthly", "quarterly", "half_yearly", "annual"]


# --------------------------------------------------------------------------- live
@pytest.fixture(scope="module")
def stack():
    fake = ThreadingHTTPServer(("127.0.0.1", FAKE_PORT), FakeRazorpay)
    threading.Thread(target=fake.serve_forever, daemon=True).start()
    env = {**os.environ, "RAZORPAY_KEY_ID": KEY_ID, "RAZORPAY_KEY_SECRET": KEY_SECRET,
           "RAZORPAY_WEBHOOK_SECRET": HOOK_SECRET, "RAZORPAY_API_BASE": f"http://127.0.0.1:{FAKE_PORT}/v1"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "server:app", "--port", str(PORT)], cwd=HERE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    db = MongoClient(_env("MONGO_URL"))[_env("DB_NAME")]
    launch = db.app_settings.find_one({"key": "launch_offer"}, {"_id": 0}) or {}
    try:
        for _ in range(120):
            try:
                if requests.get(f"{API}/config", timeout=1).ok:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            pytest.fail("test backend did not start")
        # Plans must be on sale for checkout; restored afterwards.
        db.app_settings.update_one({"key": "launch_offer"}, {"$set": {"plans_hidden": False}})
        yield db
    finally:
        db.app_settings.update_one({"key": "launch_offer"}, {"$set": {"plans_hidden": launch.get("plans_hidden", True)}})
        users = [u["user_id"] for u in db.users.find({"email": {"$regex": "^test_pay_"}}, {"user_id": 1})]
        for coll in ("subscriptions", "payments", "career_usage", "email_logs"):
            db[coll].delete_many({"candidate_id": {"$in": users}})
        db.payment_webhooks.delete_many({"event_id": {"$regex": "^test_evt_"}})
        db.users.delete_many({"user_id": {"$in": users}})
        proc.terminate()
        proc.wait(10)
        fake.shutdown()


def candidate(db):
    email = f"test_pay_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register", json={
        "full_name": "TEST Pay User", "email": email, "mobile": "9000000000", "password": "secret123",
        "confirm_password": "secret123", "industry": "Travel & Hospitality", "current_designation": "Agent",
        "current_salary": "5 LPA", "preferred_location": "Mumbai", "preferred_work_mode": "Hybrid", "consent": True})
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["user_id"]
    db.subscriptions.delete_many({"candidate_id": uid})  # ignore any launch-offer grant; start on the free tier
    return {"Authorization": f"Bearer {r.json()['token']}"}, uid


def plans_by_tier():
    r = requests.get(f"{API}/plans")
    assert r.status_code == 200
    return {p["tier"]: p for p in r.json()["plans"] if p.get("tier")}, r.json()


def order(h, plan_id):
    r = requests.post(f"{API}/checkout/razorpay/order", headers=h, json={"plan_id": plan_id})
    assert r.status_code == 200, r.text
    return r.json()


def pay(h, oid, **kw):
    pid = fake_payment(oid, **kw)
    return requests.post(f"{API}/checkout/razorpay/verify", headers=h, json={
        "razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sign(oid, pid)}), pid


def membership(h):
    return requests.get(f"{API}/membership", headers=h).json()["membership"]


def days_left(m):
    exp = datetime.fromisoformat(m["expiry_date"].replace("Z", "+00:00"))
    return (exp - datetime.now(timezone.utc)).days


def webhook(event, payload, event_id=None, secret=HOOK_SECRET):
    body = json.dumps({"event": event, "payload": payload}).encode()
    return requests.post(f"{API}/payments/razorpay/webhook", data=body, headers={
        "Content-Type": "application/json", "X-Razorpay-Event-Id": event_id or f"test_evt_{uuid.uuid4().hex[:10]}",
        "X-Razorpay-Signature": hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()})


# One class: these tests flip the shared "plans hidden" setting, so they must run on one xdist worker.
class TestMembershipsAndPayments:
    # ---- catalogue
    def test_four_paid_plans_with_final_prices(self, stack):
        tiers, data = plans_by_tier()
        assert {t: (p["price"], p["duration_days"]) for t, p in tiers.items()} == CATALOGUE
        assert tiers["annual"]["best_value"] is True and tiers["annual"]["featured"] is True
        assert all(p["ai_limits"] and p["features"] for p in tiers.values()), "plans show their AI limits"
        assert data["payments"] == {"gateway": "razorpay", "test_mode": True}
        assert len(data["plans"]) == 4, "older plans are switched off, not offered alongside"

    def test_old_plans_kept_but_inactive(self, stack):
        assert stack.plans.count_documents({"tier": {"$exists": False}, "active": True}) == 0
        for p in stack.plans.find({"tier": {"$exists": False}}):
            assert p.get("price") is not None, "retired plans keep their records for existing subscriptions"

    def test_restart_does_not_reset_prices(self, stack):
        tiers, _ = plans_by_tier()
        stack.plans.update_one({"tier": "monthly"}, {"$set": {"price": 649}})
        try:
            import asyncio
            import server
            asyncio.run(server._migrate_plan_catalogue())
            assert stack.plans.find_one({"tier": "monthly"})["price"] == 649, "admin price edits survive restarts"
            assert stack.plans.count_documents({"tier": "monthly"}) == 1
        finally:
            stack.plans.update_one({"tier": "monthly"}, {"$set": {"price": 599}})


    # ---- free tier is unchanged
    def test_registration_needs_no_payment_and_free_access_is_kept(self, stack):
        h, uid = candidate(stack)
        assert membership(h)["is_active"] is False
        assert stack.payments.count_documents({"candidate_id": uid}) == 0
        usage = requests.get(f"{API}/career/usage", headers=h).json()
        assert usage["tier"] == "free"
        assert {k: v["limit"] for k, v in usage["usage"].items()} == {
            "resume_generation": 2, "resume_analysis": 2, "interview_sessions": 1}
        assert all(t["free_access"] for t in usage["tools"].values())
        jobs = requests.get(f"{API}/jobs", headers=h).json()
        assert jobs["jobs"] and all(j["locked"] for j in jobs["jobs"]), "free users still browse job previews"

    def test_demo_checkout_is_off_when_razorpay_is_configured(self, stack):
        h, _ = candidate(stack)
        plan = plans_by_tier()[0]["monthly"]
        r = requests.post(f"{API}/checkout/demo", headers=h, json={"plan_id": plan["plan_id"]})
        assert r.status_code == 403
        assert membership(h)["is_active"] is False


    # ---- Razorpay checkout
    def test_successful_payment_activates_once(self, stack):
        h, uid = candidate(stack)
        plan = plans_by_tier()[0]["monthly"]
        o = order(h, plan["plan_id"])
        assert o["key_id"] == KEY_ID and o["amount"] == 59900
        assert membership(h)["is_active"] is False, "creating an order activates nothing"
        r, pid = pay(h, o["order_id"])
        assert r.status_code == 200 and r.json()["status"] == "successful", r.text
        m = membership(h)
        assert m["is_active"] and 29 <= days_left(m) <= 30 and m["is_demo"] is False
        p = stack.payments.find_one({"order_id": o["order_id"]})
        assert p["status"] == "successful" and p["transaction_id"] == pid and p["receipt_no"].startswith("JR-")
        # the same confirmation again, and the webhook for it: still one membership
        again = requests.post(f"{API}/checkout/razorpay/verify", headers=h, json={
            "razorpay_order_id": o["order_id"], "razorpay_payment_id": pid, "razorpay_signature": sign(o["order_id"], pid)})
        assert again.status_code == 200
        assert webhook("payment.captured", {"payment": {"entity": PAYMENTS[pid]}}).json()["status"] == "fulfilled"
        assert stack.subscriptions.count_documents({"candidate_id": uid}) == 1
        rec = requests.get(f"{API}/payments/{p['payment_id']}/receipt", headers=h)
        assert rec.status_code == 200 and rec.json()["receipt"]["amount"] == 599

    def test_bad_signature_never_activates(self, stack):
        h, uid = candidate(stack)
        o = order(h, plans_by_tier()[0]["quarterly"]["plan_id"])
        pid = fake_payment(o["order_id"])
        r = requests.post(f"{API}/checkout/razorpay/verify", headers=h, json={
            "razorpay_order_id": o["order_id"], "razorpay_payment_id": pid, "razorpay_signature": "0" * 64})
        assert r.status_code == 400
        assert membership(h)["is_active"] is False and stack.subscriptions.count_documents({"candidate_id": uid}) == 0

    def test_amount_mismatch_never_activates(self, stack):
        h, _ = candidate(stack)
        o = order(h, plans_by_tier()[0]["annual"]["plan_id"])
        r, _ = pay(h, o["order_id"], amount=100)
        assert r.status_code == 400
        assert membership(h)["is_active"] is False

    def test_authorized_payment_is_captured_then_activated(self, stack):
        h, _ = candidate(stack)
        o = order(h, plans_by_tier()[0]["half_yearly"]["plan_id"])
        r, _ = pay(h, o["order_id"], status="authorized")
        assert r.json()["status"] == "successful"
        assert 179 <= days_left(membership(h)) <= 180

    def test_webhook_alone_activates_if_candidate_closes_the_page(self, stack):
        h, _ = candidate(stack)
        o = order(h, plans_by_tier()[0]["quarterly"]["plan_id"])
        pid = fake_payment(o["order_id"])
        evt = f"test_evt_{uuid.uuid4().hex[:10]}"
        assert webhook("order.paid", {"payment": {"entity": PAYMENTS[pid]}}, event_id=evt).json()["status"] == "fulfilled"
        assert webhook("order.paid", {"payment": {"entity": PAYMENTS[pid]}}, event_id=evt).json()["status"] == "duplicate"
        assert 89 <= days_left(membership(h)) <= 90

    def test_webhook_rejects_bad_signature(self, stack):
        assert webhook("payment.captured", {}, secret="wrong").status_code == 400

    def test_failed_payment_keeps_current_access(self, stack):
        h, uid = candidate(stack)
        tiers = plans_by_tier()[0]
        pay(h, order(h, tiers["monthly"]["plan_id"])["order_id"])
        before = membership(h)
        o = order(h, tiers["monthly"]["plan_id"])
        pid = fake_payment(o["order_id"], status="failed")
        PAYMENTS[pid]["error_description"] = "Card declined"
        assert webhook("payment.failed", {"payment": {"entity": PAYMENTS[pid]}}).json()["status"] == "failed"
        assert stack.payments.find_one({"order_id": o["order_id"]})["status"] == "failed"
        assert membership(h)["expiry_date"] == before["expiry_date"] and membership(h)["is_active"]

    def test_renewal_adds_days_and_shorter_plan_waits(self, stack):
        h, _ = candidate(stack)
        tiers = plans_by_tier()[0]
        pay(h, order(h, tiers["monthly"]["plan_id"])["order_id"])
        pay(h, order(h, tiers["monthly"]["plan_id"])["order_id"])
        assert 59 <= days_left(membership(h)) <= 60, "renewal is added after the current expiry"
        pay(h, order(h, tiers["annual"]["plan_id"])["order_id"])
        assert 364 <= days_left(membership(h)) <= 365, "a longer plan starts today"
        r = requests.post(f"{API}/checkout/razorpay/order", headers=h, json={"plan_id": tiers["monthly"]["plan_id"]})
        assert r.status_code == 400, "no switch to a shorter plan while one is active"

    def test_renewing_a_retired_plan_with_the_new_one_keeps_remaining_days(self, stack):
        h, uid = candidate(stack)
        old = stack.plans.find_one({"tier": {"$exists": False}, "duration_days": 90})
        if not old:
            pytest.skip("no retired 90-day plan in this database")
        stack.subscriptions.insert_one({
            "subscription_id": f"sub_test_{uuid.uuid4().hex[:8]}", "candidate_id": uid, "plan_id": old["plan_id"],
            "plan_name": old["name"], "start_date": datetime.now(timezone.utc).isoformat(),
            "expiry_date": datetime.fromtimestamp(time.time() + 40 * 86400, timezone.utc).isoformat(),
            "status": "active", "is_demo": False, "reminders_sent": [],
            "created_at": datetime.now(timezone.utc).isoformat()})
        pay(h, order(h, plans_by_tier()[0]["quarterly"]["plan_id"])["order_id"])
        assert 129 <= days_left(membership(h)) <= 130

    def test_refund_is_recorded(self, stack):
        h, uid = candidate(stack)
        o = order(h, plans_by_tier()[0]["monthly"]["plan_id"])
        _, pid = pay(h, o["order_id"])
        ref = {"id": f"rfnd_{uuid.uuid4().hex[:10]}", "payment_id": pid, "amount": 59900, "status": "processed"}
        assert webhook("refund.processed", {"refund": {"entity": ref}}).status_code == 200
        p = stack.payments.find_one({"order_id": o["order_id"]})
        assert p["status"] == "refunded" and p["refunded_amount"] == 599

    def test_admin_reconcile_activates_a_missed_payment(self, stack):
        h, uid = candidate(stack)
        o = order(h, plans_by_tier()[0]["monthly"]["plan_id"])
        fake_payment(o["order_id"])  # paid, but neither verify nor webhook arrived
        admin = requests.post(f"{API}/auth/admin/login", json={"email": "admin@eevolvex.com", "password": "Admin@12345"})
        ah = {"Authorization": "Bearer " + admin.json()["token"]}
        summary = requests.get(f"{API}/admin/payments/summary", headers=ah).json()
        assert summary["mode"]["gateway"] == "razorpay" and summary["webhook_configured"] is True
        internal = stack.payments.find_one({"order_id": o["order_id"]})["payment_id"]
        r = requests.post(f"{API}/admin/payments/{internal}/reconcile", headers=ah)
        assert r.status_code == 200 and r.json()["outcome"] == "activated", r.text
        assert membership(h)["is_active"]
        assert requests.post(f"{API}/admin/payments/{internal}/reconcile").status_code in (401, 403)
