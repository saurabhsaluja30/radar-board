import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/constants";
import { Badge, Button, Card, EmptyState, errMsg, Input, notify, PageHeader, Spinner } from "@/components/kit";

const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v && v !== "All"));
const n = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("en-IN"));
const pct = (a, b) => (b ? `${Math.round((a * 100) / b)}%` : "—");
export const bytes = (b) => {
  if (b === null || b === undefined) return "—";
  const u = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = b;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
};
const usd = (v) => (v === null || v === undefined ? "—" : `$${Number(v).toFixed(v < 1 ? 3 : 2)}`);
const inr = (v) => (v === null || v === undefined ? "—" : `₹${Number(v).toLocaleString("en-IN")}`);

const Stat = ({ label, value, hint, tone, testId }) => (
  <Card data-testid={testId} className="!p-4">
    <p className={`text-2xl font-extrabold ${tone === "warn" ? "text-amber-600" : tone === "bad" ? "text-red-600" : "text-brand"}`}>{value}</p>
    <p className="mt-1 text-xs font-semibold text-gray-600">{label}</p>
    {hint ? <p className="mt-0.5 text-[11px] text-gray-400">{hint}</p> : null}
  </Card>
);

const Section = ({ title, subtitle, children, testId }) => (
  <section className="space-y-4" data-testid={testId}>
    <div>
      <h2 className="text-lg font-extrabold text-gray-900">{title}</h2>
      {subtitle ? <p className="text-sm text-gray-500">{subtitle}</p> : null}
    </div>
    {children}
  </section>
);

function Bars({ title, rows, testId }) {
  const max = Math.max(1, ...(rows || []).map((r) => r.count));
  return (
    <Card data-testid={testId}>
      <p className="mb-3 text-sm font-bold text-gray-800">{title}</p>
      {!rows?.length ? <p className="text-sm text-gray-400">No data yet.</p> : (
        <div className="space-y-2.5">
          {rows.map((r) => (
            <div key={r.name}>
              <div className="mb-1 flex justify-between gap-3 text-xs">
                <span className="truncate font-semibold text-gray-700">{r.name}</span>
                <b className="shrink-0 text-gray-900">{n(r.count)}</b>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-brand-soft">
                <div className="h-full rounded-full bg-brand" style={{ width: `${(r.count / max) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

/** Column chart for a daily or monthly series. `rows` items carry a label key and a value key. */
export function Columns({ title, rows, labelKey = "day", valueKey = "count", format = n, testId, limitLine, limitLabel }) {
  const vals = (rows || []).map((r) => r[valueKey] || 0);
  const max = Math.max(1e-9, ...vals, limitLine || 0);
  const total = vals.reduce((a, b) => a + b, 0);
  const first = rows?.[0]?.[labelKey];
  const last = rows?.[rows.length - 1]?.[labelKey];
  return (
    <Card data-testid={testId}>
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <p className="text-sm font-bold text-gray-800">{title}</p>
        {valueKey === "count" ? <span className="text-xs text-gray-500">Total {n(total)}</span> : null}
      </div>
      {!rows?.length ? <p className="text-sm text-gray-400">No data yet.</p> : (
        <>
          <div className="relative flex h-28 items-end gap-[2px]">
            {limitLine ? (
              <div className="absolute inset-x-0 border-t border-dashed border-red-400" style={{ bottom: `${(limitLine / max) * 100}%` }}>
                <span className="absolute -top-4 right-0 text-[10px] font-semibold text-red-500">{limitLabel}</span>
              </div>
            ) : null}
            {rows.map((r) => (
              <div key={r[labelKey]} className="group relative flex h-full flex-1 items-end">
                <div className="w-full rounded-t bg-brand/80 group-hover:bg-brand" style={{ height: `${Math.max(((r[valueKey] || 0) / max) * 100, r[valueKey] ? 3 : 0)}%` }} />
                <span className="pointer-events-none absolute -top-6 left-1/2 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded bg-gray-900 px-1.5 py-0.5 text-[10px] text-white group-hover:block">
                  {r[labelKey]}: {format(r[valueKey])}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-1 flex justify-between text-[10px] text-gray-400"><span>{first}</span><span>{last}</span></div>
        </>
      )}
    </Card>
  );
}

const Select = ({ label, value, options, onChange, testId }) => (
  <label className="block text-sm">
    <span className="mb-1.5 block font-semibold text-gray-700">{label}</span>
    <select className="field w-auto min-w-[10rem] py-2" value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
      <option>All</option>
      {(options || []).map((o) => <option key={o}>{o}</option>)}
    </select>
  </label>
);

// ---------------------------------------------------------------------------------------------- Platform analytics
export function AdminPlatformAnalytics() {
  const [f, setF] = useState({ start: "", end: "", industry: "All", source: "All" });
  const { data: d, isLoading, error } = useQuery({
    queryKey: ["admin-platform", f], queryFn: () => api("/admin/analytics/platform", { query: clean(f) }), keepPreviousData: true,
  });
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const c = d?.candidates;
  const j = d?.jobs;
  const m = d?.smartmatch;
  const a = d?.apify;
  const s = d?.storage;
  const ranged = f.start || f.end;
  return (
    <div className="space-y-8" data-testid="platform-analytics">
      <PageHeader title="Platform Analytics" subtitle="Candidates, jobs, SmartMatch, Apify and storage in one place. Counts come straight from the database." />
      <Card className="flex flex-wrap items-end gap-3">
        <Input label="From" type="date" value={f.start} onChange={(e) => set("start")(e.target.value)} data-testid="pa-start" />
        <Input label="To" type="date" value={f.end} onChange={(e) => set("end")(e.target.value)} data-testid="pa-end" />
        <Select label="Industry" value={f.industry} options={d?.options?.industries} onChange={set("industry")} testId="pa-industry" />
        <Select label="Job source" value={f.source} options={d?.options?.sources} onChange={set("source")} testId="pa-source" />
        {ranged || f.industry !== "All" || f.source !== "All" ? (
          <Button size="sm" variant="ghost" title="Clear filters" onClick={() => setF({ start: "", end: "", industry: "All", source: "All" })} data-testid="pa-clear" />
        ) : null}
        <p className="w-full text-xs text-gray-400">
          Dates limit new candidates, jobs added, matches, alerts and Apify runs to that period. Trend charts show {d ? `${d.range.start} to ${d.range.end}` : "the last 30 days"}.
          Industry applies to candidates and jobs; job source applies to jobs and SmartMatch.
        </p>
      </Card>

      {isLoading ? <Spinner /> : error ? <EmptyState title="Couldn't load analytics" subtitle={errMsg(error)} /> : (
        <>
          <Section title="Candidates" testId="pa-candidates">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
              <Stat label="Registered candidates" value={n(c.total)} hint={ranged ? `${n(c.new_in_range)} in period` : null} testId="pa-cand-total" />
              <Stat label="Resumes uploaded" value={n(c.with_resume)} hint={pct(c.with_resume, c.total)} testId="pa-cand-resume" />
              <Stat label="Complete profiles" value={n(c.complete_profiles)} hint={pct(c.complete_profiles, c.total)} testId="pa-cand-complete" />
              <Stat label="Job preferences set" value={n(c.with_preferences)} hint={pct(c.with_preferences, c.total)} />
              <Stat label="Job alerts switched on" value={n(c.alerts_on)} />
              <Stat label="In Talent Database (consented)" value={n(c.talent_consent)} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Columns title="Resume uploads per day" rows={c.resume_trend} testId="pa-resume-trend" />
              <Columns title="Registrations per day" rows={c.registration_trend} testId="pa-reg-trend" />
            </div>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Bars title="By industry" rows={c.by_industry} testId="pa-cand-industry" />
              <Bars title="By current designation" rows={c.by_designation} />
              <Bars title="By experience" rows={c.by_experience} />
              <Bars title="By location" rows={c.by_location} />
            </div>
          </Section>

          <Section title="Jobs" testId="pa-jobs">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
              <Stat label="Jobs collected" value={n(j.total)} hint={`${n(j.imported)} via Apify`} testId="pa-jobs-total" />
              <Stat label="Active (live)" value={n(j.active)} testId="pa-jobs-active" />
              <Stat label="Awaiting import approval" value={n(j.awaiting)} tone={j.awaiting ? "warn" : null} testId="pa-jobs-awaiting" />
              <Stat label="Expired" value={n(j.expired)} />
              <Stat label="Rejected" value={n(j.rejected)} />
              <Stat label="Possible duplicates" value={n(j.duplicates)} testId="pa-jobs-dupes" />
              <Stat label="Archived" value={n(j.archived)} />
            </div>
            <Columns title="Jobs added per day" rows={j.added_trend} testId="pa-jobs-trend" />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Bars title="By industry" rows={j.by_industry} />
              <Bars title="By source" rows={j.by_source} testId="pa-jobs-source" />
              <Bars title="By location" rows={j.by_location} />
              <Bars title="By status" rows={j.by_status} />
            </div>
          </Section>

          <Section title="SmartMatch" subtitle="Strong = score 80+, potential = 65–79." testId="pa-smartmatch">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
              <Stat label="Matches generated" value={n(m.total)} testId="pa-sm-total" />
              <Stat label="Strong matches" value={n(m.strong)} />
              <Stat label="Potential matches" value={n(m.potential)} />
              <Stat label="Approved by admin" value={n(m.approved)} />
              <Stat label="Candidates with relevant matches" value={n(m.candidates_relevant)} />
              <Stat label="Live jobs without suitable candidates" value={`${n(m.jobs_without_candidates)} / ${n(m.live_jobs)}`}
                tone={m.jobs_without_candidates ? "warn" : null} testId="pa-sm-nocand" />
              <Stat label="In-app alerts sent" value={n(m.notifications_in_app)}
                hint={`${n(m.notifications_auto)} automatic · ${n(m.notifications_admin)} admin${m.notifications_email ? ` · ${n(m.notifications_email)} email` : ""}`} testId="pa-sm-alerts" />
            </div>
            {m.jobs_without_candidates_sample?.length ? (
              <Card>
                <p className="mb-2 text-sm font-bold text-gray-800">Live jobs with no candidate scoring 65+</p>
                <ul className="divide-y divide-gray-100 text-sm">
                  {m.jobs_without_candidates_sample.map((x) => (
                    <li key={x.job_id} className="flex justify-between gap-3 py-1.5">
                      <span className="truncate"><b>{x.title}</b> · {x.company}</span>
                      <span className="shrink-0 text-xs text-gray-400">{x.industry_category || ""}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            ) : null}
          </Section>

          <Section title="Apify job collection" subtitle={`Rupee figures use ₹${a.usd_inr_rate} per US$ (set USD_INR_RATE to change).`} testId="pa-apify">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
              <Stat label="Actor runs" value={n(a.runs)} hint={a.running ? `${a.running} running` : null} testId="pa-apify-runs" />
              <Stat label="Successful" value={n(a.succeeded)} />
              <Stat label="Failed" value={n(a.failed)} tone={a.failed ? "bad" : null} />
              <Stat label="Jobs imported" value={n(a.imported)} hint={`${n(a.items)} items read`} />
              <Stat label="Duplicates detected" value={n(a.duplicates)} />
              <Stat label="Spend this month" value={usd(a.month_spend_usd)} hint={`≈ ${inr(a.month_spend_inr)}`} testId="pa-apify-spend" />
              <Stat label="Projected this month" value={usd(a.month_projected_usd)} hint={`≈ ${inr(a.month_projected_inr)}`}
                tone={a.month_projected_usd > a.month_budget_usd ? "bad" : null} />
              <Stat label="Monthly budget" value={usd(a.month_budget_usd)} hint={`≈ ${inr(a.month_budget_inr)}${a.paid_runs_approved ? "" : " · paid runs not approved"}`} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Columns title="Apify spend by month (US$)" rows={a.monthly} labelKey="month" valueKey="usd" format={usd}
                limitLine={a.month_budget_usd} limitLabel="Budget" testId="pa-apify-monthly" />
              <Card>
                <p className="mb-3 text-sm font-bold text-gray-800">Results by source</p>
                {!a.by_source.length ? <p className="text-sm text-gray-400">No sources yet.</p> : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs" data-testid="pa-apify-sources">
                      <thead className="text-gray-500"><tr>
                        <th className="py-1.5 pr-2">Source</th><th className="px-2">Imported</th><th className="px-2">Awaiting</th>
                        <th className="px-2">Approved</th><th className="px-2">Rejected</th><th className="px-2">Duplicates</th><th className="px-2">Published</th>
                      </tr></thead>
                      <tbody className="divide-y divide-gray-100">
                        {a.by_source.map((x) => (
                          <tr key={x.source_id}>
                            <td className="py-1.5 pr-2 font-semibold text-gray-800">{x.name}{x.enabled ? "" : <span className="ml-1 text-gray-400">(off)</span>}</td>
                            <td className="px-2">{n(x.imported)}</td><td className="px-2">{n(x.awaiting)}</td><td className="px-2">{n(x.approved)}</td>
                            <td className="px-2">{n(x.rejected)}</td><td className="px-2">{n(x.duplicates)}</td><td className="px-2">{n(x.published)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {a.avg_cost_per_run_usd !== null ? <p className="mt-3 text-xs text-gray-400">Average cost per run: {usd(a.avg_cost_per_run_usd)}</p> : null}
              </Card>
            </div>
          </Section>

          <Section title="Storage" subtitle="Counted from JobRadar's own records; the storage provider's quota isn't available through its API." testId="pa-storage">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Stat label="Resume files" value={n(s.resume_files)} hint={bytes(s.resume_bytes)} testId="pa-storage-resumes" />
              <Stat label="Tracker evidence files" value={n(s.evidence_files)} hint={bytes(s.evidence_bytes)} />
              <Stat label="Total stored" value={bytes(s.total_bytes)} />
            </div>
            {s.trend?.length > 1 ? (
              <Columns title="Stored files by day" rows={s.trend} valueKey="total_bytes" format={bytes} testId="pa-storage-trend" />
            ) : <p className="text-xs text-gray-400">A storage snapshot is saved once a day; the trend chart appears after the second day.</p>}
          </Section>
          <p className="text-right text-xs text-gray-400">Updated {formatDate(d.generated_at)}</p>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- System health
const HEALTH = {
  ok: ["Healthy", "success"], overdue: ["Overdue", "warning"], failed: ["Last run failed", "error"],
  never_run: ["Not run yet", "warning"], idle: ["Not scheduled", "info"],
};
const REC = { ok: "success", notice: "warning", warning: "error", info: "info" };
const ms = (v) => (v === null || v === undefined ? "—" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);
const ago = (iso) => {
  if (!iso) return "—";
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
};

function Meter({ label, value, max, guaranteed, unit, format = (v) => v }) {
  const p = value === null || value === undefined ? 0 : Math.min(100, (value / max) * 100);
  const g = guaranteed ? (guaranteed / max) * 100 : null;
  const tone = p >= 80 ? "bg-red-500" : p >= 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="font-semibold text-gray-700">{label}</span>
        <span className="text-gray-500"><b className="text-gray-900">{value === null || value === undefined ? "—" : format(value)}</b> of {format(max)} {unit}</span>
      </div>
      <div className="relative h-2.5 overflow-hidden rounded-full bg-gray-100">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${p}%` }} />
        {g !== null ? <div className="absolute inset-y-0 w-px bg-gray-500" style={{ left: `${g}%` }} title="Guaranteed" /> : null}
      </div>
    </div>
  );
}

export function AdminSystemHealth() {
  const qc = useQueryClient();
  const { data: d, isLoading, error, isFetching } = useQuery({
    queryKey: ["admin-system-health"], queryFn: () => api("/admin/system/health"), refetchInterval: 60000,
  });
  const [busy, setBusy] = useState(false);
  const sample = async () => {
    setBusy(true);
    try {
      await api("/admin/system/sample", { method: "POST" });
      qc.invalidateQueries({ queryKey: ["admin-system-health"] });
      notify("Resource sample saved", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  if (isLoading) return <Spinner />;
  if (error) return <EmptyState title="Couldn't load system health" subtitle={errMsg(error)} />;
  const { jobs, queues: q, resources: r } = d;
  const t = r.this_replica;
  const w = r.week;
  const st = r.starter;
  const memMax = t.mem_limit_mb || st.mem_burst_mb;
  const cpuMax = t.cpu_limit || st.cpu_burst;
  const hourly = r.hourly.map((h) => ({
    ...h, hour: new Date(`${h.hour}:00:00Z`).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
  }));
  return (
    <div className="space-y-8" data-testid="system-health">
      <PageHeader title="System Health" subtitle="Background jobs, processing queues and Starter hosting usage."
        right={<Button size="sm" variant="ghost" icon={<RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />} title="Refresh"
          onClick={() => qc.invalidateQueries({ queryKey: ["admin-system-health"] })} data-testid="sh-refresh" />} />

      <Card className={`border-l-4 ${r.recommendation.upgrade ? "border-l-red-500" : "border-l-emerald-500"}`} data-testid="sh-recommendation">
        <div className="flex flex-wrap items-center gap-2">
          <Badge label={r.recommendation.upgrade ? "Review hosting" : "No upgrade needed"} color={REC[r.recommendation.level]} />
          <p className="text-sm text-gray-700">{r.recommendation.message}</p>
        </div>
      </Card>

      <Section title="Scheduled jobs" subtitle="Each run is recorded with its duration; records are kept for 30 days." testId="sh-jobs">
        <Card className="overflow-x-auto !p-0">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50 text-xs text-gray-500"><tr>
              <th className="px-4 py-2">Job</th><th className="px-3">Schedule</th><th className="px-3">Status</th><th className="px-3">Last run</th>
              <th className="px-3">Last duration</th><th className="px-3">Runs (7 days)</th><th className="px-3">Failures (7 days)</th><th className="px-3">Avg / max</th>
            </tr></thead>
            <tbody className="divide-y divide-gray-100">
              {jobs.map((x) => (
                <tr key={x.name} data-testid={`sh-job-${x.name}`}>
                  <td className="px-4 py-2.5 font-semibold text-gray-800">{x.name}</td>
                  <td className="px-3 text-xs text-gray-500">{x.schedule}</td>
                  <td className="px-3"><Badge label={HEALTH[x.health][0]} color={HEALTH[x.health][1]} /></td>
                  <td className="px-3 text-xs" title={x.last?.started_at}>{ago(x.last?.started_at)}{x.last?.error ? <p className="text-red-500">{x.last.error}</p> : null}</td>
                  <td className="px-3 text-xs">{ms(x.last?.duration_ms)}</td>
                  <td className="px-3 text-xs">{x.runs_7d}</td>
                  <td className={`px-3 text-xs ${x.failed_7d ? "font-bold text-red-600" : ""}`}>{x.failed_7d}</td>
                  <td className="px-3 text-xs">{ms(x.avg_ms)} / {ms(x.max_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </Section>

      <Section title="Processing queues" testId="sh-queues">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="SmartMatch: waiting" value={n(q.smartmatch.queued)} tone={q.smartmatch.oldest_queued_min > 30 ? "warn" : null}
            hint={q.smartmatch.oldest_queued_min !== null ? `oldest ${q.smartmatch.oldest_queued_min} min` : `${n(q.smartmatch.done_7d)} done in 7 days`} testId="sh-q-sm" />
          <Stat label="SmartMatch: stuck or failed" value={n(q.smartmatch.stuck + q.smartmatch.failed)} tone={q.smartmatch.stuck + q.smartmatch.failed ? "bad" : null} />
          <Stat label="Resumes: waiting to parse" value={n(q.resumes.queued + q.resumes.processing)} tone={q.resumes.oldest_queued_min > 30 ? "warn" : null}
            hint={q.resumes.oldest_queued_min !== null ? `oldest ${q.resumes.oldest_queued_min} min` : `${n(q.resumes.parsed + q.resumes.confirmed)} parsed`} testId="sh-q-resume" />
          <Stat label="Resumes: failed parsing" value={n(q.resumes.failed + q.resumes.stuck)} tone={q.resumes.failed ? "bad" : null} />
          <Stat label="Emails failed (24 h)" value={n(q.email.failed_24h)} hint={`${n(q.email.awaiting_retry)} waiting for retry`} tone={q.email.failed_24h ? "warn" : null} />
          <Stat label="Apify runs in progress" value={n(q.apify.running)} />
          <Stat label="Apify runs failed (7 days)" value={n(q.apify.failed_7d)} tone={q.apify.failed_7d ? "bad" : null} />
          <Stat label="Background tasks on this server" value={n(q.in_process_tasks)} />
        </div>
        {q.resumes.recent_failures?.length ? (
          <Card>
            <p className="mb-2 text-sm font-bold text-gray-800">Recent resume parsing failures</p>
            <ul className="divide-y divide-gray-100 text-xs">
              {q.resumes.recent_failures.map((x) => (
                <li key={x.resume_id} className="flex justify-between gap-3 py-1.5">
                  <span className="truncate">{x.file_name} · {x.error}</span><span className="shrink-0 text-gray-400">{x.attempts} attempts · {ago(x.uploaded_at)}</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </Section>

      <Section title="Starter hosting usage"
        subtitle={`Starter guarantees ${st.cpu_guaranteed} vCPU / ${st.mem_guaranteed_mb} MB and can burst to ${st.cpu_burst} vCPU / ${st.mem_burst_mb} MB per replica. Each server records a sample every 15 minutes.`}
        testId="sh-resources">
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="space-y-4" data-testid="sh-this-replica">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-bold text-gray-800">This server right now</p>
              <Button size="sm" variant="ghost" title="Save sample now" loading={busy} onClick={sample} data-testid="sh-sample" />
            </div>
            <Meter label="CPU" value={t.vcpu} max={cpuMax} guaranteed={st.cpu_guaranteed} unit="vCPU" format={(v) => Number(v).toFixed(3)} />
            <Meter label={t.kind === "peak" ? "Memory (peak)" : "Memory"} value={t.rss_mb} max={memMax} guaranteed={st.mem_guaranteed_mb} unit="MB" format={(v) => Math.round(v)} />
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-gray-600">
              <span>Server</span><b className="truncate text-gray-900">{t.replica}</b>
              <span>Up for</span><b className="text-gray-900">{t.uptime_min < 120 ? `${t.uptime_min} min` : `${Math.round(t.uptime_min / 60)} h`}</b>
              <span>Requests (15 min)</span><b className="text-gray-900">{n(t.last_15_min.requests)}</b>
              <span>Response time p50 / p95</span><b className="text-gray-900">{ms(t.last_15_min.p50_ms)} / {ms(t.last_15_min.p95_ms)}</b>
              <span>Server errors (15 min)</span><b className={t.last_15_min.errors_5xx ? "text-red-600" : "text-gray-900"}>{n(t.last_15_min.errors_5xx)}</b>
              <span>Database round trip</span><b className="text-gray-900">{ms(t.db_ping_ms)}</b>
            </div>
            <p className="text-[11px] text-gray-400">The grey tick marks the guaranteed amount. CPU is averaged since the last sample. {t.mem_limit_mb ? "" : "Container limits aren't visible here, so Starter's burst limits are used."}</p>
          </Card>
          <Card data-testid="sh-week">
            <p className="mb-3 text-sm font-bold text-gray-800">Last 7 days ({n(w.samples)} samples{w.replicas?.length ? `, ${w.replicas.length} server${w.replicas.length > 1 ? "s" : ""}` : ""})</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs text-gray-600">
              <span>Average CPU</span><b className="text-gray-900">{w.vcpu_avg === null ? "—" : `${w.vcpu_avg} vCPU`}</b>
              <span>Busiest CPU (95th percentile)</span><b className="text-gray-900">{w.vcpu_p95 === null ? "—" : `${w.vcpu_p95} vCPU`}</b>
              <span>Highest memory</span><b className="text-gray-900">{w.rss_max_mb === null ? "—" : `${Math.round(w.rss_max_mb)} MB`}</b>
              <span>Slow responses (95th percentile)</span><b className="text-gray-900">{ms(w.p95_ms_p95)}</b>
              <span>Samples near CPU limit</span><b className="text-gray-900">{w.cpu_high_pct === null ? "—" : `${w.cpu_high_pct}%`}</b>
              <span>Samples near memory limit</span><b className="text-gray-900">{w.mem_high_pct === null ? "—" : `${w.mem_high_pct}%`}</b>
              <span>Requests</span><b className="text-gray-900">{n(w.requests)}</b>
              <span>Server error rate</span><b className="text-gray-900">{w.error_rate_pct === null ? "—" : `${w.error_rate_pct}%`}</b>
            </div>
          </Card>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <Columns title="CPU by hour (busiest server, vCPU)" rows={hourly} labelKey="hour" valueKey="vcpu" format={(v) => Number(v || 0).toFixed(3)}
            limitLine={st.cpu_burst} limitLabel="Burst limit" testId="sh-cpu-chart" />
          <Columns title="Memory by hour (MB)" rows={hourly} labelKey="hour" valueKey="rss_mb" format={(v) => `${Math.round(v || 0)} MB`}
            limitLine={st.mem_burst_mb} limitLabel="Burst limit" />
          <Columns title="Slowest responses by hour (p95)" rows={hourly} labelKey="hour" valueKey="p95_ms" format={ms} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <p className="mb-2 text-sm font-bold text-gray-800">Slowest routes on this server (last 15 min)</p>
            {!t.last_15_min.slowest_routes.length ? <p className="text-sm text-gray-400">No requests yet.</p> : (
              <table className="w-full text-left text-xs" data-testid="sh-slow-routes">
                <thead className="text-gray-500"><tr><th className="py-1">Route</th><th className="px-2">Calls</th><th className="px-2">p95</th><th className="px-2">Max</th></tr></thead>
                <tbody className="divide-y divide-gray-100">
                  {t.last_15_min.slowest_routes.map((x) => (
                    <tr key={x.route}><td className="truncate py-1 font-mono">{x.route}</td><td className="px-2">{x.count}</td><td className="px-2">{ms(x.p95_ms)}</td><td className="px-2">{ms(x.max_ms)}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card data-testid="sh-database">
            <p className="mb-2 text-sm font-bold text-gray-800">Database</p>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-gray-600">
              <span>Data size</span><b className="text-gray-900">{bytes(r.database.data_bytes)}</b>
              <span>Index size</span><b className="text-gray-900">{bytes(r.database.index_bytes)}</b>
              <span>Storage used</span><b className="text-gray-900">{bytes(r.database.storage_bytes)}</b>
              <span>Documents</span><b className="text-gray-900">{n(r.database.objects)}</b>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 border-t border-gray-100 pt-3 text-xs text-gray-500">
              {Object.entries(r.database.collections).map(([k, v]) => (
                <React.Fragment key={k}><span className="font-mono">{k}</span><span className="text-gray-900">{n(v)}</span></React.Fragment>
              ))}
            </div>
          </Card>
        </div>
      </Section>
      <p className="text-right text-xs text-gray-400">Updated {formatDate(d.generated_at)} · refreshes every minute</p>
    </div>
  );
}
