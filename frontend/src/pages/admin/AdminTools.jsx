import React, { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/constants";
import { Badge, Button, Card, EmptyState, Input, notify, PageHeader, Spinner, Switch } from "@/components/kit";

export function AdminEmails() {
  const qc = useQueryClient();
  const [compose, setCompose] = useState({ subject: "", message: "" });
  const [sending, setSending] = useState(false);
  const [polling, setPolling] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const { data } = useQuery({ queryKey: ["admin-emails"], queryFn: () => api("/admin/emails"), refetchInterval: polling ? 4000 : false });
  const emails = data?.emails || [];
  useEffect(() => {
    if (!polling) return undefined;
    const t = setTimeout(() => setPolling(false), 120000);
    return () => clearTimeout(t);
  }, [polling]);
  const retry = async () => {
    setRetrying(true);
    try {
      const res = await api("/admin/emails/retry-failed", { method: "POST" });
      notify(`Retrying ${res.queued} failed email${res.queued === 1 ? "" : "s"} — sending slowly to stay within limits`, "success");
      setPolling(true);
      qc.invalidateQueries({ queryKey: ["admin-emails"] });
    } catch (e) {
      notify(e.message || "Failed", "error");
    } finally {
      setRetrying(false);
    }
  };
  const send = async () => {
    if (!compose.subject || !compose.message) return notify("Enter subject and message", "error");
    setSending(true);
    try {
      const res = await api("/admin/announcement", { method: "POST", body: compose });
      notify(`Sending to ${res.queued} candidate${res.queued === 1 ? "" : "s"}${res.skipped_already_received ? ` · skipped ${res.skipped_already_received} who already received this subject` : ""}. Delivery status updates below.`, "success");
      setPolling(true);
      setCompose({ subject: "", message: "" });
      qc.invalidateQueries({ queryKey: ["admin-emails"] });
    } catch (e) {
      notify(e.message || "Failed", "error");
    } finally {
      setSending(false);
    }
  };
  return (
    <>
      <PageHeader title="Email Management" />
      <div className="grid gap-6 lg:grid-cols-[380px_1fr]">
        <Card className="h-fit space-y-4">
          <p className="h-sec">Send Announcement</p>
          <Input label="Subject" value={compose.subject} onChange={(e) => setCompose((c) => ({ ...c, subject: e.target.value }))} data-testid="email-subject" />
          <Input multiline label="Message" value={compose.message} onChange={(e) => setCompose((c) => ({ ...c, message: e.target.value }))} data-testid="email-message" />
          <Button full title="Send to all candidates" loading={sending} onClick={send} data-testid="email-send" />
        </Card>
        <div>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="h-sec">Email Logs ({emails.length}){polling ? <span className="ml-2 text-xs font-semibold text-brand">updating…</span> : null}</p>
            {data?.retryable ? <Button size="sm" variant="outline" title={`Retry failed (${data.retryable})`} loading={retrying} onClick={retry} data-testid="email-retry-failed" /> : null}
          </div>
          <p className="mb-3 text-xs text-gray-500">Emails are sent one at a time to stay within the email provider's limits. Re-sending an announcement with the same subject goes only to candidates who haven't received it yet.</p>
          <div className="space-y-2">
            {emails.map((e) => (
              <Card key={e.email_id} className="flex items-center justify-between gap-4 py-3.5" data-testid={`email-log-${e.email_id}`}>
                <div className="min-w-0">
                  <p className="truncate font-bold">{e.subject}</p>
                  <p className="text-sm text-gray-500">{e.to} · {e.email_type} · {formatDate(e.date_sent)}</p>
                </div>
                <Badge label={e.delivery_status} color={e.delivery_status === "sent" ? "success" : e.delivery_status === "failed" ? "error" : "info"} />
              </Card>
            ))}
            {emails.length === 0 ? <p className="muted">No emails logged yet.</p> : null}
          </div>
        </div>
      </div>
    </>
  );
}

const ACTIONS = [
  ["activate_90", "Activate 90-Day Plan", "Activate"], ["activate_180", "Activate 180-Day Plan", "Activate"], ["activate_365", "Activate 365-Day Plan", "Activate"],
  ["expire_now", "Expire Membership Now", "Expiry"], ["expiry_7", "Set Expiry in 7 Days", "Expiry"], ["expiry_3", "Set Expiry in 3 Days", "Expiry"], ["expiry_1", "Set Expiry Tomorrow", "Expiry"],
  ["reminder_7", "Trigger 7-Day Reminder", "Reminders"], ["reminder_3", "Trigger 3-Day Reminder", "Reminders"], ["reminder_1", "Trigger 1-Day Reminder", "Reminders"],
  ["simulate_failed_payment", "Simulate Failed Payment", "Payments"], ["simulate_renewal", "Simulate Successful Renewal", "Payments"],
  ["reset_account", "Reset Test Account", "Danger"], ["delete_subscription", "Delete Demo Subscription", "Danger"],
];
const GROUPS = ["Activate", "Expiry", "Reminders", "Payments", "Danger"];

export function AdminDevPanel() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(null);
  const { data, refetch } = useQuery({ queryKey: ["dev-candidates"], queryFn: () => api("/admin/dev/candidates") });
  const candidates = data?.candidates || [];
  const current = candidates.find((c) => c.user_id === selected);
  const run = async (action) => {
    if (!selected) return notify("Select a candidate first", "error");
    setBusy(action);
    try {
      const res = await api("/admin/dev/action", { method: "POST", body: { candidate_id: selected, action } });
      notify(res.message || "Done", "success");
      await refetch();
      qc.invalidateQueries();
    } catch (e) {
      notify(e.message || "Action failed", "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <>
      <PageHeader title="Developer Test Panel" />
      <p className="mb-6 rounded-xl bg-amber-50 p-3 text-sm font-semibold text-amber-700">Demo mode — all transactions are marked DEMO and excluded from real revenue.</p>
      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div>
          <p className="h-sec mb-3">1. Select a test candidate</p>
          <div className="max-h-[60vh] space-y-2 overflow-y-auto pr-1">
            {candidates.map((c) => (
              <button key={c.user_id} onClick={() => setSelected(c.user_id)} data-testid={`dev-candidate-${c.email}`}
                className={`w-full rounded-xl border p-3 text-left transition-colors ${selected === c.user_id ? "border-brand bg-brand text-white" : "border-gray-200 bg-white hover:border-brand"}`}>
                <p className="truncate font-bold">{c.full_name || c.email}</p>
                <p className={`truncate text-xs ${selected === c.user_id ? "text-violet-100" : "text-gray-500"}`}>{c.email}</p>
              </button>
            ))}
          </div>
        </div>
        <div className="space-y-5">
          {current ? (
            <Card className="flex items-center justify-between" data-testid="dev-current">
              <div><p className="font-extrabold">{current.full_name}</p><p className="text-sm text-gray-500">Expiry: {formatDate(current.expiry_date)} · {current.days_remaining} days left</p></div>
              <Badge label={(current.status || "").replace("_", " ")} color={current.status === "active" ? "success" : current.status === "expiring_soon" ? "warning" : current.status === "no_membership" ? "info" : "error"} />
            </Card>
          ) : null}
          <p className="h-sec">2. Run test actions</p>
          {GROUPS.map((g) => (
            <div key={g}>
              <p className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-400">{g}</p>
              <div className="grid gap-2 md:grid-cols-3">
                {ACTIONS.filter((a) => a[2] === g).map(([action, label]) => (
                  <Button key={action} variant={g === "Danger" ? "danger" : "outline"} size="sm" title={label} loading={busy === action}
                    onClick={() => run(action)} data-testid={`dev-action-${action}`} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

export function AdminLaunch() {
  const q = useQuery({ queryKey: ["admin-launch"], queryFn: () => api("/admin/launch-offer") });
  const qc = useQueryClient();
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(null);
  useEffect(() => { if (q.data?.settings) setS({ ...q.data.settings }); }, [q.data]);
  const run = async (key, fn, ok) => {
    setBusy(key);
    try {
      await fn();
      await q.refetch();
      qc.invalidateQueries({ queryKey: ["launch-offer"] });
      notify(ok, "success");
    } catch (e) {
      notify(e.message || "Failed", "error");
    } finally {
      setBusy(null);
    }
  };
  const save = () => run("save", () => api("/admin/launch-offer", {
    method: "PUT",
    body: { enabled: !!s.enabled, plans_hidden: !!s.plans_hidden, free_spots: Number(s.free_spots) || 0, free_days: Number(s.free_days) || 90 },
  }), "Launch offer saved");
  const wait = q.data?.waitlist || [];
  return (
    <>
      <PageHeader title="Launch Offer & Waitlist" />
      {q.isLoading ? <Spinner /> : null}
      {q.isError ? <EmptyState title="Could not load launch settings. Please try again." data-testid="admin-launch-error" /> : null}
      <div className="grid gap-6 lg:grid-cols-[420px_1fr]">
        {s ? (
          <Card className="h-fit space-y-4" data-testid="admin-launch-settings">
            <p className="h-sec">Free launch offer</p>
            <p className="muted">{s.granted || 0} of {s.free_spots} free spots used · new sign-ups only</p>
            <div className="flex items-center justify-between gap-4"><span className="text-sm font-semibold">Offer active (free access for new sign-ups)</span><Switch checked={!!s.enabled} onChange={(v) => setS({ ...s, enabled: v })} data-testid="admin-launch-enabled" /></div>
            <div className="flex items-center justify-between gap-4"><span className="text-sm font-semibold">Hide membership plans & payments</span><Switch checked={!!s.plans_hidden} onChange={(v) => setS({ ...s, plans_hidden: v })} data-testid="admin-launch-hidden" /></div>
            <div className="grid grid-cols-2 gap-4">
              <Input label="Free spots" value={String(s.free_spots)} onChange={(e) => setS({ ...s, free_spots: e.target.value.replace(/\D/g, "") })} data-testid="admin-launch-spots" />
              <Input label="Free access days" value={String(s.free_days)} onChange={(e) => setS({ ...s, free_days: e.target.value.replace(/\D/g, "") })} data-testid="admin-launch-days" />
            </div>
            <Button full title="Save" loading={busy === "save"} onClick={save} data-testid="admin-launch-save" />
          </Card>
        ) : <div />}
        <div>
          <p className="h-sec mb-4">Waitlist ({wait.length})</p>
          {wait.length === 0 ? <EmptyState title="No one on the waitlist" data-testid="admin-waitlist-empty" /> : null}
          <div className="space-y-2">
            {wait.map((w) => (
              <Card key={w.user_id} className="flex items-center justify-between gap-4 py-4" data-testid={`waitlist-${w.user_id}`}>
                <div><p className="font-bold">{w.full_name || "Candidate"}</p><p className="text-sm text-gray-500">{w.email}{w.mobile ? ` · ${w.mobile}` : ""} · joined {formatDate(w.waitlisted_at)}</p></div>
                <Button size="sm" title="Approve Free Access" loading={busy === w.user_id} data-testid={`waitlist-approve-${w.user_id}`}
                  onClick={() => run(w.user_id, () => api(`/admin/launch-offer/approve/${w.user_id}`, { method: "POST" }), "Access approved and email logged")} />
              </Card>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

const TOOLS = [["resume_builder", "ATS Resume Builder"], ["resume_analyser", "Resume Analyser"], ["interview_coach", "AI Interview Coach"]];
const KINDS = [["resume_generation", "Resume generations"], ["resume_analysis", "Resume analyses"], ["interview_sessions", "Interview sessions"]];
const TIERS = [["free", "Free users"], ["monthly", "Monthly"], ["quarterly", "Quarterly"], ["half_yearly", "Half-Yearly"], ["annual", "Annual"]];
const numCls = "field w-24 py-2 text-center";

export function AdminCareer() {
  const settingsQ = useQuery({ queryKey: ["admin-career-settings"], queryFn: () => api("/admin/career/settings") });
  const statsQ = useQuery({ queryKey: ["admin-career-stats"], queryFn: () => api("/admin/career/stats") });
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (settingsQ.data?.settings) setS(JSON.parse(JSON.stringify(settingsQ.data.settings))); }, [settingsQ.data]);
  const upd = (fn) => setS((prev) => { const d = JSON.parse(JSON.stringify(prev)); fn(d); return d; });
  const save = async () => {
    setSaving(true);
    try {
      await api("/admin/career/settings", { method: "PUT", body: { tools: s.tools, limits: s.limits, period_days: Number(s.period_days) || 30, addons: s.addons || [] } });
      await settingsQ.refetch();
      notify("Career Tools settings saved", "success");
    } catch (e) {
      notify(e.message || "Save failed", "error");
    } finally {
      setSaving(false);
    }
  };
  const st = statsQ.data;
  return (
    <>
      <PageHeader title="Career Tools" right={s ? <Button title="Save Settings" loading={saving} onClick={save} data-testid="admin-career-save" /> : null} />
      {st ? (
        <Card className="mb-6 space-y-4" data-testid="admin-career-stats">
          <p className="h-sec">Usage & AI cost (aggregate)</p>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[["Users", st.unique_users], ["Resumes saved", st.saved_resumes], ["Analyses", st.saved_analyses], ["Interviews", st.interview_sessions],
              ["AI calls", st.ai.total_calls], ["Failed calls", st.ai.failed_calls], ["Est. cost", `$${st.ai.est_cost_usd}`], ["Tokens", st.ai.input_tokens + st.ai.output_tokens]].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-brand-mist p-4"><p className="text-2xl font-extrabold text-brand">{String(v)}</p><p className="text-xs font-semibold text-gray-500">{l}</p></div>
            ))}
          </div>
          {KINDS.map(([k, l]) => <p key={k} className="text-sm text-gray-600">{l}: {st.usage[k].last_30d} in last 30 days · {st.usage[k].total} total</p>)}
          <p className="text-sm text-gray-600">Model: {st.ai.model} · AI configured: {st.ai_configured ? "Yes" : "No — set EMERGENT_LLM_KEY"}</p>
          <p className="label pt-2">Recent failed requests</p>
          {st.recent_failures.length === 0 ? <p className="text-sm text-gray-500">No failures</p> : null}
          {st.recent_failures.map((f, i) => <p key={i} className="text-xs text-red-600">{formatDate(f.created_at)} · {f.purpose} · {f.error}</p>)}
          <p className="text-xs text-gray-400">Private resumes and interview answers are never shown here.</p>
        </Card>
      ) : null}
      {s ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="space-y-4">
            <p className="h-sec">Tool access</p>
            {TOOLS.map(([k, l]) => (
              <div key={k} className="rounded-xl border border-gray-100 p-4">
                <p className="mb-2 font-bold">{l}</p>
                <div className="flex items-center justify-between text-sm"><span>Enabled</span><Switch checked={!!s.tools[k]?.enabled} onChange={(v) => upd((d) => (d.tools[k].enabled = v))} data-testid={`admin-career-${k}-enabled`} /></div>
                <div className="mt-2 flex items-center justify-between text-sm"><span>Available to free users</span><Switch checked={!!s.tools[k]?.free_access} onChange={(v) => upd((d) => (d.tools[k].free_access = v))} data-testid={`admin-career-${k}-free`} /></div>
              </div>
            ))}
            <p className="h-sec pt-2">Optional paid add-ons</p>
            <p className="text-xs text-gray-500">Add-ons are shown to candidates only when enabled. Candidates are never charged automatically.</p>
            {(s.addons || []).map((a, i) => (
              <div key={a.key} className="flex items-center justify-between text-sm"><span>{a.name} (₹{a.price})</span><Switch checked={!!a.enabled} onChange={(v) => upd((d) => (d.addons[i].enabled = v))} data-testid={`admin-addon-${a.key}`} /></div>
            ))}
          </Card>
          <Card className="space-y-4">
            <p className="h-sec">Usage limits</p>
            <p className="text-xs text-gray-500">Paid plans: total uses included for the whole plan (from purchase until expiry). Free users: uses per period below.</p>
            <div className="flex items-center justify-between text-sm font-semibold">
              <span>Free-user period (days)</span>
              <input className={numCls} value={String(s.period_days)} onChange={(e) => upd((d) => (d.period_days = e.target.value.replace(/\D/g, "")))} data-testid="admin-career-period" />
            </div>
            <table className="w-full text-sm">
              <thead><tr><th /> {KINDS.map(([k, l]) => <th key={k} className="pb-2 text-xs font-bold text-gray-400">{l}</th>)}</tr></thead>
              <tbody>
                {TIERS.map(([t, tl]) => (
                  <tr key={t}>
                    <td className="py-1.5 font-semibold">{tl}</td>
                    {KINDS.map(([k]) => (
                      <td key={k} className="py-1.5 text-center">
                        <input className={numCls} value={String(s.limits[t]?.[k] ?? 0)} data-testid={`admin-limit-${t}-${k}`}
                          onChange={(e) => upd((d) => (d.limits[t][k] = Number(e.target.value.replace(/\D/g, "")) || 0))} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      ) : null}
    </>
  );
}
