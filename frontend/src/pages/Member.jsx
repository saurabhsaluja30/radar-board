import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Briefcase, CheckCircle2, ChevronRight, Circle, CreditCard, FileText, HelpCircle, Info, LayoutGrid, LogOut, Mail, ShieldCheck, Sparkles, UserCog } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatDate, INDUSTRIES, INDUSTRIES_WITH_OTHER, INDUSTRY_SHORT, PREF_WORK_MODES, EXPERIENCE_RANGES, money } from "@/lib/constants";
import { Badge, Button, Card, Chip, ChipRow, EmptyState, Input, notify, PageHeader, SectionTitle } from "@/components/kit";
import { LaunchOfferCard, MembershipCard, OpportunityNotice, useLaunchOffer } from "@/components/Membership";
import { JobCard } from "@/components/JobCard";
import { CareerToolsCards } from "@/components/career";
import { Page } from "@/components/Layout";
import { ALERT_NOTICE, ProfileCompletion, SmartProfileForm } from "@/components/SmartProfile";
import { ResumeCard } from "@/components/ResumeCard";
import { GoogleButton, OrLine } from "@/pages/Auth";

function LoginPrompt({ title, text }) {
  const navigate = useNavigate();
  return (
    <Page narrow>
      <h1 className="h-page">{title}</h1>
      <p className="muted mt-3">{text}</p>
      <Button className="mt-6" title="Login" onClick={() => navigate("/auth/login")} data-testid="login-prompt-btn" />
    </Page>
  );
}

export function Account() {
  const navigate = useNavigate();
  const { user, membership, logout } = useAuth();
  const { data: launch } = useLaunchOffer();
  if (!user) {
    return (
      <Page narrow>
        <Card className="mx-auto max-w-md p-8 text-center">
          <h1 className="text-2xl font-extrabold">Welcome to JobRadar</h1>
          <p className="muted mt-2">Sign in to access your dashboard, membership, and saved jobs.</p>
          <div className="mt-6 space-y-3">
            <Button full title="Login" onClick={() => navigate("/auth/login")} data-testid="account-login-btn" />
            <Button full variant="outline" title="Create an account" onClick={() => navigate("/auth/register")} data-testid="account-register-btn" />
          </div>
          <OrLine />
          <GoogleButton testId="account-google-btn" />
          <button onClick={() => navigate("/admin")} className="mt-5 text-sm font-semibold text-gray-400 hover:text-brand" data-testid="account-admin-link">Admin login</button>
        </Card>
      </Page>
    );
  }
  const links = [
    { icon: LayoutGrid, label: "Dashboard", to: "/dashboard" },
    { icon: Sparkles, label: "My Job Search Tracker", to: "/tracker" },
    { icon: Briefcase, label: "Career Tools", to: "/career" },
    { icon: CreditCard, label: launch?.plans_hidden ? "My Access" : "Membership & Plans", to: "/membership" },
    { icon: UserCog, label: "Edit Profile", to: "/profile" },
    { icon: Info, label: "About JobRadar", to: "/about" },
    { icon: HelpCircle, label: "FAQ", to: "/faq" },
    { icon: Mail, label: "Contact Support", to: "/contact" },
    { icon: FileText, label: "Legal & Policies", to: "/legal/terms" },
  ];
  return (
    <Page>
      <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
        <div className="space-y-6">
          <Card className="flex items-center gap-4">
            {user.picture ? <img src={user.picture} alt="" className="h-16 w-16 rounded-full object-cover" /> : (
              <span className="flex h-16 w-16 items-center justify-center rounded-full bg-brand text-2xl font-extrabold text-white">
                {(user.full_name || user.email || "?")[0]?.toUpperCase()}
              </span>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-xl font-extrabold" data-testid="account-name">{user.full_name || "JobRadar Member"}</p>
              <p className="truncate text-sm text-gray-500" data-testid="account-email">{user.email}</p>
            </div>
            {user.role === "admin" ? (
              <Button size="sm" title="Admin" icon={<ShieldCheck className="h-4 w-4" />} onClick={() => navigate("/admin")} data-testid="account-admin-portal" />
            ) : null}
          </Card>
          <MembershipCard membership={membership} hidePlanName={!!launch?.plans_hidden} onRenew={launch?.plans_hidden ? undefined : () => navigate("/plans")} />
        </div>
        <Card className="p-2">
          {links.map((l) => (
            <button key={l.label} onClick={() => navigate(l.to)} data-testid={`account-link-${l.label}`}
              className="flex w-full items-center gap-4 rounded-xl px-4 py-4 text-left font-semibold text-gray-800 transition-colors hover:bg-brand-mist">
              <l.icon className="h-5 w-5 text-brand" />
              <span className="flex-1">{l.label}</span>
              <ChevronRight className="h-4 w-4 text-gray-400" />
            </button>
          ))}
          <div className="p-3">
            <Button full variant="outline" title="Log out" icon={<LogOut className="h-4 w-4" />} data-testid="account-logout-btn"
              onClick={async () => { await logout(); notify("Logged out"); navigate("/"); }} />
          </div>
        </Card>
      </div>
    </Page>
  );
}

const BENEFITS = ["Full curated job descriptions", "Recruiter contact where available", "Direct application links", "Save unlimited jobs", "Regularly updated listings"];
const LIMIT_LABELS = [["resume_generation", "AI resume generations"], ["resume_analysis", "AI resume analyses"], ["interview_sessions", "AI mock interviews"]];

let rzpScript;
function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve();
  rzpScript = rzpScript || new Promise((resolve, reject) => {
    const el = document.createElement("script");
    el.src = "https://checkout.razorpay.com/v1/checkout.js";
    el.onload = resolve;
    el.onerror = () => { rzpScript = null; reject(new Error("Could not load Razorpay checkout. Check your connection and try again.")); };
    document.body.appendChild(el);
  });
  return rzpScript;
}

// Opens Razorpay Checkout for a server-created order. Resolves after the server has verified the payment.
async function payWithRazorpay(planId) {
  const order = await api("/checkout/razorpay/order", { method: "POST", body: { plan_id: planId } });
  await loadRazorpay();
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency,
      name: "JobRadar by EvolveMinds", description: order.plan_name, prefill: order.prefill,
      theme: { color: "#7C3AED" },
      handler: (resp) => api("/checkout/razorpay/verify", { method: "POST", body: resp }).then(resolve, reject),
      modal: {
        ondismiss: () => {
          api("/checkout/razorpay/cancel", { method: "POST", body: { order_id: order.order_id } }).catch(() => {});
          reject(new Error("Payment cancelled. You have not been charged."));
        },
      },
    });
    rzp.on("payment.failed", (r) => notify(r?.error?.description || "Payment failed. You can try again.", "error"));
    rzp.open();
  });
}

export function Plans() {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const { data: launch } = useLaunchOffer();
  const { data } = useQuery({ queryKey: ["plans"], queryFn: () => api("/plans", { auth: false }) });
  const plans = data?.plans || [];
  const gateway = data?.payments?.gateway;
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const { data: memData } = useQuery({ queryKey: ["membership"], queryFn: () => api("/membership"), enabled: !!user });
  const mem = memData?.membership;

  useEffect(() => {
    if (plans.length && !selected) {
      const current = mem?.is_active ? plans.find((p) => p.plan_id === mem.plan_id) : null;
      setSelected((current || plans.find((p) => p.featured) || plans[0]).plan_id);
    }
  }, [plans, selected, mem]);
  useEffect(() => {
    if (mem?.is_active && mem.plan_id) setSelected(mem.plan_id);
  }, [mem?.is_active, mem?.plan_id]);

  const maxDuration = Math.max(...plans.map((p) => p.duration_days || 0), 0);
  const curDays = mem?.is_active ? (plans.find((p) => p.plan_id === mem.plan_id)?.duration_days || mem.plan_duration_days) : null;
  const selPlan = plans.find((p) => p.plan_id === selected);
  const isDowngrade = !!(curDays && selPlan && selPlan.duration_days < curDays);
  const exp = String(mem?.expiry_date || "").slice(0, 10);
  const changeNote = mem?.is_active && selPlan
    ? selPlan.plan_id === mem.plan_id || selPlan.duration_days === curDays
      ? `Renewal: ${selPlan.duration_days} days will be added after your current expiry (${exp}).`
      : isDowngrade
        ? `You can switch to the ${selPlan.name} after your current ${mem.plan_name} expires (${exp}).`
        : `Upgrade: your ${mem.plan_name} will be replaced. The ${selPlan.name} starts today and is valid for ${selPlan.duration_days} days.`
    : null;

  const checkout = async () => {
    if (!user) {
      notify("Please login to continue");
      return navigate("/auth/login");
    }
    if (!selected) return;
    setLoading(true);
    try {
      if (gateway === "razorpay") {
        const res = await payWithRazorpay(selected);
        await refresh();
        if (res?.status === "successful") notify("Payment received. Your membership is active.", "success");
        else notify(res?.message || "Your payment is being confirmed.", "info");
      } else {
        await api("/checkout/demo", { method: "POST", body: { plan_id: selected } });
        await refresh();
        notify("Membership activated (Demo)", "success");
      }
      navigate("/membership");
    } catch (e) {
      notify(e.message || "Payment failed", "error");
    } finally {
      setLoading(false);
    }
  };

  if (launch?.plans_hidden) {
    return (
      <Page narrow>
        <PageHeader title="My Access" />
        <div className="space-y-6"><LaunchOfferCard /><OpportunityNotice /></div>
      </Page>
    );
  }
  return (
    <Page>
      <PageHeader title="Unlock Premium Job Discovery" subtitle="Save hours of searching. Get curated opportunities and apply directly to employers." />
      {gateway !== "razorpay" || data?.payments?.test_mode ? (
        <p className="mb-6 inline-flex items-center gap-2 rounded-full bg-amber-50 px-4 py-2 text-sm font-semibold text-amber-700" data-testid="payment-mode-note">
          <Sparkles className="h-4 w-4" /> {gateway === "razorpay" ? "Razorpay test mode: use test cards, no real money is charged." : "Demo mode — no real payment is charged."}
        </p>
      ) : null}
      <div className="grid gap-8 lg:grid-cols-[1fr_340px]">
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {plans.map((p) => {
              const isSel = selected === p.plan_id;
              return (
                <button key={p.plan_id} onClick={() => setSelected(p.plan_id)} data-testid={`plan-${p.plan_id}`}
                  className={`rounded-2xl border-2 bg-white p-6 text-left transition-[border-color,transform] hover:-translate-y-0.5 ${isSel ? "border-brand" : "border-gray-200"}`}>
                  <div className="flex min-h-[24px] flex-wrap gap-1.5">
                    {p.featured ? <Badge label="Recommended" color="brand" /> : null}
                    {(p.best_value ?? (p.duration_days === maxDuration && plans.length > 1)) ? <Badge label="Best Value" color="success" /> : null}
                  </div>
                  <div className="mt-3 flex items-start justify-between">
                    <div>
                      <p className="font-extrabold text-gray-900">{p.name}</p>
                      <p className="text-sm text-gray-500">{p.duration_days} days access</p>
                    </div>
                    {isSel ? <CheckCircle2 className="h-6 w-6 fill-brand text-white" /> : <Circle className="h-6 w-6 text-gray-300" />}
                  </div>
                  <p className="mt-4 text-3xl font-extrabold text-brand">{money(p.price, p.currency)}</p>
                  {p.duration_days > 30 ? <p className="text-xs text-gray-500">≈ {money(Math.round(p.price / (p.duration_days / 30)), p.currency)} per month</p> : null}
                  {p.tagline ? <p className="mt-1 text-sm text-gray-500">{p.tagline}</p> : null}
                  {p.ai_limits ? (
                    <ul className="mt-3 space-y-1 border-t border-gray-100 pt-3 text-xs text-gray-600" data-testid={`plan-limits-${p.plan_id}`}>
                      {LIMIT_LABELS.map(([k, label]) => <li key={k}>{p.ai_limits[k] ?? 0} {label}</li>)}
                    </ul>
                  ) : null}
                </button>
              );
            })}
          </div>
          <OpportunityNotice />
          <p className="text-xs text-gray-400">
            Membership fees provide access to curated job information and platform features. Membership does not guarantee an interview, job offer, employment, salary, or response from any employer.
          </p>
        </div>
        <aside className="lg:sticky lg:top-24 lg:self-start">
          <Card>
            <h3 className="font-extrabold">Every plan includes</h3>
            <div className="mt-3 space-y-2.5">
              {(plans[0]?.features || BENEFITS).map((b) => <p key={b} className="flex items-center gap-2 text-sm text-gray-700"><CheckCircle2 className="h-4 w-4 text-emerald-600" />{b}</p>)}
            </div>
            <p className="mt-4 text-xs text-gray-500">AI tool limits apply to the whole plan period. One-time payment: plans do not renew automatically.</p>
            {changeNote ? <p className="mt-5 rounded-xl bg-brand-mist p-3 text-sm text-brand-ink" data-testid="plan-change-note">{changeNote}</p> : null}
            <Button full size="lg" className="mt-5" loading={loading} disabled={isDowngrade} onClick={checkout} data-testid="checkout-btn"
              title={isDowngrade ? "Available after current plan expires" : "Continue to Payment"} />
          </Card>
        </aside>
      </div>
    </Page>
  );
}

export function Membership() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: launch } = useLaunchOffer();
  const hidden = !!launch?.plans_hidden;
  const { data } = useQuery({ queryKey: ["membership", user?.user_id], queryFn: () => api("/membership"), enabled: !!user });
  if (!user) return <LoginPrompt title={hidden ? "My Access" : "Membership"} text={`Login to view your ${hidden ? "access" : "membership"}.`} />;
  const payments = data?.payments || [];
  const plans = data?.plans || [];
  return (
    <Page>
      <PageHeader title={hidden ? "My Access" : "Membership"} />
      <div className="grid gap-8 lg:grid-cols-2">
        <div className="space-y-6">
          <MembershipCard membership={data?.membership} hidePlanName={hidden} onRenew={hidden ? undefined : () => navigate("/plans")} />
          {hidden ? <LaunchOfferCard /> : <OpportunityNotice />}
          {!hidden ? (
            <div>
              <SectionTitle title="Available Plans" />
              <div className="space-y-3">
                {plans.map((p) => (
                  <Card key={p.plan_id} className="flex items-center justify-between py-4">
                    <div><p className="font-bold">{p.name}</p><p className="text-sm text-gray-500">{p.duration_days} days · {money(p.price, p.currency)}</p></div>
                    {p.featured ? <Badge label="Recommended" color="brand" /> : null}
                  </Card>
                ))}
              </div>
              <Button className="mt-4" title="Renew / Upgrade" onClick={() => navigate("/plans")} data-testid="membership-plans-btn" />
            </div>
          ) : null}
        </div>
        {!hidden ? (
          <div className="space-y-6">
            <div>
              <SectionTitle title="Payment History" />
              {payments.length === 0 ? <Card><p className="muted">No payments yet.</p></Card> : (
                <div className="space-y-3">{payments.map((p) => <PaymentRow key={p.payment_id} p={p} />)}</div>
              )}
            </div>
            <div>
              <SectionTitle title="Policies" />
              <Card className="space-y-4 text-sm">
                <div><p className="font-bold">Refund Policy</p><p className="text-gray-600">Membership fees are generally non-refundable once premium access is activated. See the full Refund Policy for exceptions.</p></div>
                <div><p className="font-bold">Cancellation Policy</p><p className="text-gray-600">You may cancel anytime; access continues until your current expiry date. Memberships are one-time payments and never renew automatically.</p></div>
              </Card>
            </div>
          </div>
        ) : null}
      </div>
    </Page>
  );
}

export function Receipt() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data, isError } = useQuery({ queryKey: ["receipt", id], queryFn: () => api(`/payments/${id}/receipt`), enabled: !!user });
  if (!user) return <LoginPrompt title="Receipt" text="Login to view your receipt." />;
  if (isError) return <Page narrow><EmptyState title="Receipt not found." /></Page>;
  const r = data?.receipt;
  if (!r) return null;
  const rows = [
    ["Receipt number", r.receipt_no || "-"], ["Date", formatDate(r.payment_date)], ["Billed to", `${r.candidate_name || ""} (${r.candidate_email || ""})`],
    ["Plan", r.plan_name], ["Valid", `${formatDate(r.valid_from)} to ${formatDate(r.valid_until)}`],
    ["Payment method", "Razorpay"], ["Razorpay payment ID", r.transaction_id], ["Order ID", r.order_id],
    ["Amount paid", money(r.amount, r.currency)],
    ...(r.refunded_amount ? [["Refunded", money(r.refunded_amount, r.currency)]] : []),
  ];
  return (
    <Page narrow>
      <Card className="space-y-5" data-testid="receipt">
        <div className="flex items-start justify-between">
          <div><p className="text-xl font-extrabold text-brand">JobRadar by EvolveMinds</p><p className="text-sm text-gray-500">Payment receipt</p></div>
          <Badge label={PAY_LABEL[r.status] || r.status} color={r.status === "successful" ? "success" : "info"} />
        </div>
        <dl className="divide-y divide-gray-100 text-sm">
          {rows.map(([k, v]) => <div key={k} className="flex justify-between gap-4 py-2"><dt className="text-gray-500">{k}</dt><dd className="text-right font-semibold text-gray-900">{v}</dd></div>)}
        </dl>
        <p className="text-xs text-gray-400">One-time payment for access to JobRadar membership features. Membership does not guarantee an interview, job offer or employment.</p>
        <Button title="Print or save as PDF" variant="outline" onClick={() => window.print()} data-testid="receipt-print" />
      </Card>
    </Page>
  );
}

const PAY_LABEL = { created: "Not completed", cancelled: "Cancelled", partially_refunded: "Partly refunded" };

function PaymentRow({ p }) {
  const navigate = useNavigate();
  const hasReceipt = ["successful", "refunded", "partially_refunded"].includes(p.status) && !p.is_demo;
  return (
    <Card className="flex items-center justify-between py-4" data-testid={`payment-${p.payment_id}`}>
      <div>
        <p className="flex items-center gap-2 font-bold">{p.plan_name} {p.is_demo ? <Badge label="DEMO" color="warning" /> : null}</p>
        <p className="text-sm text-gray-500">{formatDate(p.payment_date)}{p.gateway ? ` · ${p.gateway}` : ""}</p>
      </div>
      <div className="text-right">
        <p className="font-extrabold">{money(p.amount, p.currency)}</p>
        {p.status ? <Badge label={PAY_LABEL[p.status] || p.status} color={p.status === "successful" ? "success" : p.status === "failed" ? "error" : "info"} /> : null}
        {hasReceipt ? <button className="mt-1 block w-full text-right text-xs font-semibold text-brand hover:underline" onClick={() => navigate(`/receipt/${p.payment_id}`)} data-testid={`receipt-${p.payment_id}`}>Receipt</button> : null}
      </div>
    </Card>
  );
}

const JobGrid = ({ items }) => (
  <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{items.map((j) => <JobCard key={j.job_id} job={j} />)}</div>
);

export function Dashboard() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: launch } = useLaunchOffer();
  const { data } = useQuery({ queryKey: ["dashboard", user?.user_id], queryFn: () => api("/dashboard"), enabled: !!user });
  if (!user) return <LoginPrompt title="Dashboard" text="Login to view your dashboard." />;
  const saved = data?.saved_jobs || [];
  const recommended = data?.recommended_jobs || [];
  const recent = data?.recent_jobs || [];
  const payments = data?.payments || [];
  const hidden = launch?.plans_hidden;
  return (
    <Page>
      <PageHeader title={`Welcome, ${(user.full_name || "there").split(" ")[0]}`} subtitle="Here is your JobRadar snapshot." />
      <div className="grid gap-8 lg:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-12">
          <JobNotifications />
          <ProfileCompletion compact />
          <Card className="flex flex-wrap items-center gap-4" data-testid="dashboard-matches">
            <div className="flex-1"><p className="h-sec">My Job Matches</p><p className="muted mt-1">Jobs ranked by how well they fit your profile, plus opportunities JobRadar shares with you.</p></div>
            <Button size="sm" title="View Matches" onClick={() => navigate("/matches")} data-testid="dashboard-matches-open" />
          </Card>
          <TrackerSummary />
          <div data-testid="dashboard-career-tools">
            <SectionTitle title="Career Tools" action="Open" onAction={() => navigate("/career")} />
            <CareerToolsCards />
          </div>
          {recommended.length > 0 ? (
            <div data-testid="dashboard-recommended">
              <SectionTitle title="Recommended for you" action="Explore" onAction={() => navigate("/explore")} />
              <JobGrid items={recommended} />
            </div>
          ) : null}
          <div data-testid="dashboard-recent">
            <SectionTitle title="Recently Added" action="See all" onAction={() => navigate("/explore")} />
            <JobGrid items={recent} />
          </div>
          <div data-testid="dashboard-saved">
            <SectionTitle title="Saved Jobs" action="View" onAction={() => navigate("/saved")} />
            {saved.length === 0 ? <Card><p className="muted">No saved jobs yet. Use the bookmark on any job to save it.</p></Card> : <JobGrid items={saved} />}
          </div>
        </div>
        <aside className="space-y-6">
          <MembershipCard membership={data?.membership} hidePlanName={!!hidden} onRenew={hidden ? undefined : () => navigate("/plans")} />
          <div>
            <SectionTitle title={hidden ? "Payments" : "Payment History"} />
            {hidden ? <Card><p className="muted">No payment needed — you have free access during our launch.</p></Card>
              : payments.length === 0 ? <Card><p className="muted">No payments yet.</p></Card>
                : <div className="space-y-3">{payments.slice(0, 5).map((p) => <PaymentRow key={p.payment_id} p={p} />)}</div>}
          </div>
        </aside>
      </div>
    </Page>
  );
}

function JobNotifications() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data, refetch } = useQuery({ queryKey: ["my-notifications", user?.user_id], queryFn: () => api("/smartmatch/notifications"), enabled: user?.role === "candidate" });
  if (!data) return null;
  const open = async (n) => {
    if (!n.read_at) await api(`/smartmatch/notifications/${n.notification_id}/read`, { method: "POST" }).catch(() => {});
    refetch();
    navigate(`/job/${n.job_id}`);
  };
  return (
    <Card className="space-y-3" data-testid="dashboard-notifications">
      <div className="flex items-center justify-between gap-3">
        <p className="h-sec">Job notifications {data.unread ? <span className="ml-1 rounded-full bg-brand px-2 py-0.5 text-xs text-white" data-testid="notifications-unread">{data.unread} new</span> : null}</p>
        <button onClick={() => navigate("/matches")} className="text-sm font-bold text-brand hover:underline" data-testid="notifications-all">All matches</button>
      </div>
      {data.pref === "opted_out" ? <p className="muted">You turned off job alerts. Turn them back on in your profile anytime.</p>
        : data.notifications.length === 0 ? <p className="muted">No new opportunities yet. When JobRadar finds a relevant job for you, it will appear here.</p>
        : data.notifications.slice(0, 5).map((n) => (
          <button key={n.notification_id} onClick={() => open(n)} className="flex w-full items-center justify-between gap-3 rounded-xl border border-gray-100 p-3 text-left hover:border-brand" data-testid={`notification-${n.notification_id}`}>
            <span><span className="block font-bold">{n.title}</span><span className="text-xs text-gray-500">{n.company} · {formatDate(n.sent_at)}</span></span>
            {!n.read_at ? <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-brand" /> : null}
          </button>
        ))}
      <p className="text-[11px] text-gray-400">{ALERT_NOTICE}</p>
    </Card>
  );
}

function TrackerSummary() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data } = useQuery({ queryKey: ["tracker", user?.user_id], queryFn: () => api("/tracker"), enabled: !!user });
  const items = data?.items || [];
  const reminders = items.filter((i) => i.reminder).length;
  return (
    <Card className="flex flex-wrap items-center gap-4" data-testid="dashboard-tracker">
      <div className="flex-1">
        <p className="h-sec">My Job Search Tracker</p>
        <p className="muted mt-1">
          {items.length ? `${items.length} tracked job${items.length === 1 ? "" : "s"}${reminders ? ` · ${reminders} need${reminders === 1 ? "s" : ""} an update` : ""}` : "Track jobs you're interested in and record your progress."}
        </p>
      </div>
      <Button size="sm" title="Open Tracker" onClick={() => navigate("/tracker")} data-testid="dashboard-tracker-open" />
    </Card>
  );
}

export function Profile() {
  const navigate = useNavigate();
  const { user, refresh } = useAuth();
  const [form, setForm] = useState(() => ({
    full_name: user?.full_name || "", mobile: user?.mobile || "", industry: user?.industry || "",
    current_designation: user?.current_designation || "", current_salary: user?.current_salary || "",
    preferred_designation: user?.preferred_designation || "", preferred_location: user?.preferred_location || "",
    preferred_work_mode: user?.preferred_work_mode || "", preferred_experience: user?.preferred_experience || "",
  }));
  const [pref, setPref] = useState(user?.preferred_industries || []);
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [busy, setBusy] = useState(null);
  useEffect(() => { if (!user) navigate("/auth/login"); }, [user, navigate]);
  if (!user) return null;
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const bind = (k) => ({ value: form[k], onChange: (e) => set(k, e.target.value) });
  const run = async (key, fn, ok) => {
    setBusy(key);
    try {
      await fn();
      notify(ok, "success");
    } catch (e) {
      notify(e.message || "Failed", "error");
    } finally {
      setBusy(null);
    }
  };
  const save = () => run("save", async () => {
    await api("/auth/profile", { method: "PUT", body: { ...form, preferred_industries: pref } });
    await refresh();
  }, "Profile updated");
  const changePw = () => {
    if (!pw.current_password || !pw.new_password) return notify("Fill both password fields", "error");
    run("pw", async () => {
      await api("/auth/change-password", { method: "POST", body: pw });
      setPw({ current_password: "", new_password: "" });
    }, "Password changed");
  };
  return (
    <Page>
      <PageHeader title="Edit Profile" />
      <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
        <Card className="space-y-5 p-8">
          <div className="grid gap-4 md:grid-cols-2">
            <Input label="Full Name" {...bind("full_name")} data-testid="profile-name" />
            <Input label="Email" value={user.email} disabled data-testid="profile-email" />
            <Input label="Mobile" {...bind("mobile")} data-testid="profile-mobile" />
            <Input label="Current Designation" placeholder="Not Provided" {...bind("current_designation")} data-testid="profile-designation" />
            <Input label="Current Annual CTC" placeholder="Not Provided" {...bind("current_salary")} data-testid="profile-salary" />
            <Input label="Preferred Designation" placeholder="Not Provided" {...bind("preferred_designation")} data-testid="profile-pref-designation" />
            <Input label="Preferred Location / Country" placeholder="Not Provided" {...bind("preferred_location")} data-testid="profile-location" />
          </div>
          <ChipRow label="Industry">
            {INDUSTRIES_WITH_OTHER.map((c) => <Chip key={c} label={INDUSTRY_SHORT[c] || c} selected={form.industry === c} onClick={() => set("industry", c)} data-testid={`profile-industry-${c}`} />)}
          </ChipRow>
          <ChipRow label="Preferred Industry (select multiple)">
            {INDUSTRIES.map((c) => (
              <Chip key={c} label={INDUSTRY_SHORT[c] || c} selected={pref.includes(c)} data-testid={`profile-pref-ind-${c}`}
                onClick={() => setPref((p) => (p.includes(c) ? p.filter((x) => x !== c) : [...p, c]))} />
            ))}
          </ChipRow>
          <ChipRow label="Preferred Work Mode">
            {PREF_WORK_MODES.map((m) => <Chip key={m} label={m} selected={form.preferred_work_mode === m} onClick={() => set("preferred_work_mode", m)} data-testid={`profile-wm-${m}`} />)}
          </ChipRow>
          <ChipRow label="Preferred Experience">
            {EXPERIENCE_RANGES.map((e) => (
              <Chip key={e} label={e} selected={form.preferred_experience === e} data-testid={`profile-exp-${e}`}
                onClick={() => set("preferred_experience", form.preferred_experience === e ? "" : e)} />
            ))}
          </ChipRow>
          <Button title="Save Changes" loading={busy === "save"} onClick={save} data-testid="profile-save" />
        </Card>
        {user.role === "candidate" ? <div className="space-y-6 lg:col-span-2"><ProfileCompletion /><ResumeCard /><SmartProfileForm key={user.updated_at} /></div> : null}
        {user.auth_provider === "password" ? (
          <Card className="h-fit space-y-4">
            <h3 className="h-sec">Change Password</h3>
            <Input label="Current Password" type="password" value={pw.current_password} onChange={(e) => setPw((p) => ({ ...p, current_password: e.target.value }))} data-testid="pw-current" />
            <Input label="New Password" type="password" value={pw.new_password} onChange={(e) => setPw((p) => ({ ...p, new_password: e.target.value }))} data-testid="pw-new" />
            <Button full variant="outline" title="Update Password" loading={busy === "pw"} onClick={changePw} data-testid="pw-submit" />
          </Card>
        ) : null}
      </div>
    </Page>
  );
}


