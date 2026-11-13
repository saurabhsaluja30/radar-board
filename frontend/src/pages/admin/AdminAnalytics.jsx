import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, ShieldCheck, X } from "lucide-react";
import { api, downloadFile, fetchBlob } from "@/lib/api";
import { formatDate, INDUSTRIES, INDUSTRY_SHORT, WORK_MODES } from "@/lib/constants";
import { Badge, Button, Card, Chip, EmptyState, errMsg, Input, Modal, notify, PageHeader, Spinner } from "@/components/kit";

const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v && v !== "All"));

function DateRange({ start, end, onChange }) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <Input label="From" type="date" value={start} onChange={(e) => onChange({ start: e.target.value, end })} data-testid="range-start" />
      <Input label="To" type="date" value={end} onChange={(e) => onChange({ start, end: e.target.value })} data-testid="range-end" />
      {start || end ? <Button size="sm" variant="ghost" title="Clear dates" onClick={() => onChange({ start: "", end: "" })} data-testid="range-clear" /> : null}
    </div>
  );
}

const Stat = ({ label, value, hint, testId }) => (
  <Card data-testid={testId}>
    <p className="text-3xl font-extrabold text-brand">{value ?? "—"}</p>
    <p className="mt-1 text-sm font-semibold text-gray-600">{label}</p>
    {hint ? <p className="mt-1 text-xs text-gray-400">{hint}</p> : null}
  </Card>
);

export function RegistrationStats({ range }) {
  const { data } = useQuery({ queryKey: ["admin-registration", range], queryFn: () => api("/admin/analytics/registration", { query: clean(range || {}) }) });
  const hasRange = range?.start || range?.end;
  return (
    <div data-testid="registration-stats">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        <Stat label="Total Registered Candidates" value={data?.total_registered} testId="reg-total" />
        <Stat label="Total Free Registered Candidates" value={data?.free_registered} hint="No successful payment on record" testId="reg-free" />
        <Stat label="Total Paid Candidates" value={data?.paid} hint={data?.paid_includes_demo ? "Includes demo-mode payments" : "At least one successful payment"} testId="reg-paid" />
        <Stat label="Active Subscriptions" value={data?.active_subscriptions} hint="Includes free launch-offer access" testId="reg-active" />
        <Stat label="Expired Subscriptions" value={data?.expired_subscriptions} testId="reg-expired" />
        <Stat label={hasRange ? "Newly Registered (selected dates)" : "Newly Registered (last 7 days)"} value={hasRange ? data?.new_in_range : data?.new_last_7_days} testId="reg-new" />
      </div>
      <p className="mt-3 text-xs text-gray-400">Visible to admins only. Never shown in the candidate app.</p>
    </div>
  );
}

export function AdminRegistration() {
  const [range, setRange] = useState({ start: "", end: "" });
  return (
    <>
      <PageHeader title="Candidate Registration Analytics" subtitle="Live figures calculated from candidate accounts, payments and subscriptions." />
      <div className="mb-6"><DateRange {...range} onChange={setRange} /></div>
      <RegistrationStats range={range} />
    </>
  );
}

function Bars({ rows, onPick, testId, showNew }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <p className="muted">No data yet.</p>;
  return (
    <div className="space-y-3" data-testid={testId}>
      {rows.map((r) => (
        <button key={r.name} onClick={onPick ? () => onPick(r.name) : undefined} disabled={!onPick}
          className={`block w-full text-left ${onPick ? "group cursor-pointer" : "cursor-default"}`} data-testid={`${testId}-${r.name}`}>
          <div className="mb-1 flex justify-between gap-3 text-sm">
            <span className={`truncate font-semibold text-gray-700 ${onPick ? "group-hover:text-brand" : ""}`}>{r.name}</span>
            <span className="shrink-0 text-gray-500">
              <b className="text-gray-900">{r.count}</b> · {r.pct}%{showNew && r.new_in_range !== undefined ? ` · ${r.new_in_range} new` : ""}
            </span>
          </div>
          <div className="h-2.5 overflow-hidden rounded-full bg-brand-soft">
            <div className="h-full rounded-full bg-brand transition-[width] duration-500" style={{ width: `${(r.count / max) * 100}%` }} />
          </div>
        </button>
      ))}
    </div>
  );
}

const LEVEL_COLOR = { High: "success", Moderate: "warning", Low: "error" };

function CandidateList({ filters, title, onClose }) {
  const { data, isLoading } = useQuery({ queryKey: ["admin-demand-list", filters], queryFn: () => api("/admin/analytics/candidates", { query: clean(filters) }) });
  const rows = data?.candidates || [];
  const exportCsv = () => downloadFile("/admin/analytics/candidates/export", filters, "jobradar-candidates.csv").catch((e) => notify(errMsg(e), "error"));
  return (
    <Modal open onClose={onClose} wide>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xl font-extrabold" data-testid="demand-list-title">{title}</p>
          <p className="muted">{data ? `${data.total} candidate${data.total === 1 ? "" : "s"}` : ""} · admin-only, handle per Privacy Policy</p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" title="Export CSV / Excel" icon={<Download className="h-4 w-4" />} onClick={exportCsv} data-testid="demand-list-export" />
          <button onClick={onClose} data-testid="demand-list-close"><X className="h-5 w-5" /></button>
        </div>
      </div>
      {isLoading ? <Spinner /> : rows.length === 0 ? <EmptyState title="No candidates match" /> : (
        <div className="mt-4 max-h-[60vh] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-white text-left text-xs uppercase text-gray-400">
              <tr><th className="py-2 pr-3">Candidate</th><th className="pr-3">Current</th><th className="pr-3">Prefers</th><th className="pr-3">Location</th><th>Membership</th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((c) => (
                <tr key={c.user_id} data-testid={`demand-row-${c.email}`}>
                  <td className="py-2.5 pr-3"><p className="font-bold">{c.full_name || "—"}</p><p className="text-xs text-gray-500">{c.email}</p></td>
                  <td className="pr-3 text-gray-600">{c.industry_raw}<br /><span className="text-xs">{c.current_designation}</span></td>
                  <td className="pr-3 text-gray-600">{c.preferred_industries.join(", ")}<br /><span className="text-xs">{c.preferred_designation}</span></td>
                  <td className="pr-3 text-gray-600">{c.location}<br /><span className="text-xs">{c.country} · {c.work_mode}</span></td>
                  <td><Badge label={c.membership_type} color={c.membership_type === "Paid" ? "success" : "info"} /> <span className="text-xs text-gray-500">{c.sub_status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Modal>
  );
}

const SelectChips = ({ label, value, options, onChange, testId, short }) => (
  <div>
    <p className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-400">{label}</p>
    <div className="flex flex-wrap gap-1.5">
      {["All", ...options].map((o) => <Chip key={o} label={short ? short(o) : o} selected={value === o} onClick={() => onChange(o)} data-testid={`${testId}-${o}`} />)}
    </div>
  </div>
);

const EMPTY_F = { industry: "All", dimension: "current", designation: "", experience: "All", location: "", country: "All", work_mode: "All", membership: "All", sub_status: "All" };

export function AdminDemand() {
  const [range, setRange] = useState({ start: "", end: "" });
  const [f, setF] = useState(EMPTY_F);
  const [list, setList] = useState(null);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  const query = clean({ ...range, ...f });
  const { data, isLoading } = useQuery({ queryKey: ["admin-demand", query], queryFn: () => api("/admin/analytics/demand", { query }) });
  const open = (dimension, industry) => setList({ title: `${industry} — ${dimension === "preferred" ? "preferred industry" : "current industry"}`, filters: { ...query, dimension, industry } });
  const opts = data?.options || {};
  return (
    <>
      <PageHeader title="Candidate Demand Analytics" subtitle="How many candidates are in — and want to move into — each industry. Click an industry to see its candidates."
        right={<Button variant="outline" title="Export filtered list" icon={<Download className="h-4 w-4" />} data-testid="demand-export-all"
          onClick={() => downloadFile("/admin/analytics/candidates/export", query, "jobradar-candidates.csv").catch((e) => notify(errMsg(e), "error"))} />} />
      <Card className="mb-6 space-y-5" data-testid="demand-filters">
        <DateRange {...range} onChange={setRange} />
        <div className="grid gap-5 lg:grid-cols-2">
          <SelectChips label="Industry" value={f.industry} options={[...INDUSTRIES, "Other", "Not Specified"]} onChange={set("industry")} testId="df-industry" short={(o) => INDUSTRY_SHORT[o] || o} />
          <div>
            <p className="mb-2 text-xs font-bold uppercase tracking-wider text-gray-400">Industry filter applies to</p>
            <div className="flex gap-1.5">
              <Chip label="Current industry" selected={f.dimension === "current"} onClick={() => set("dimension")("current")} data-testid="df-dim-current" />
              <Chip label="Preferred industry" selected={f.dimension === "preferred"} onClick={() => set("dimension")("preferred")} data-testid="df-dim-preferred" />
            </div>
          </div>
          <SelectChips label="Total work experience" value={f.experience} options={opts.experience || []} onChange={set("experience")} testId="df-exp" />
          <SelectChips label="Work mode" value={f.work_mode} options={[...WORK_MODES, "Any", "Not Specified"]} onChange={set("work_mode")} testId="df-wm" />
          <SelectChips label="Preferred country" value={f.country} options={opts.country || []} onChange={set("country")} testId="df-country" />
          <div className="grid grid-cols-2 gap-4">
            <SelectChips label="Membership" value={f.membership} options={["Free", "Paid"]} onChange={set("membership")} testId="df-membership" />
            <SelectChips label="Subscription" value={f.sub_status} options={["Active", "Expired"]} onChange={set("sub_status")} testId="df-sub" />
          </div>
          <Input label="Preferred designation contains" value={f.designation} onChange={(e) => set("designation")(e.target.value)} data-testid="df-designation" />
          <Input label="Preferred location contains" value={f.location} onChange={(e) => set("location")(e.target.value)} data-testid="df-location" />
        </div>
        <Button size="sm" variant="ghost" title="Reset filters" onClick={() => { setF(EMPTY_F); setRange({ start: "", end: "" }); }} data-testid="df-reset" />
      </Card>
      {isLoading || !data ? <Spinner /> : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
            <Stat label="Unique candidates (filtered)" value={data.total_candidates} testId="demand-total" />
            <Stat label={range.start || range.end ? "Registered in selected dates" : "Registered (all time)"} value={data.new_in_range} testId="demand-new" />
            <Stat label="Candidates with a preferred industry" value={data.with_preference} testId="demand-with-pref" />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <p className="h-sec">A. Current Industry</p>
              <p className="mb-4 text-xs text-gray-500">Where candidates work today. Each candidate counted once. % of filtered candidates · new = registered in selected dates.</p>
              <Bars rows={data.current_industry} onPick={(n) => open("current", n)} testId="demand-current" showNew />
            </Card>
            <Card>
              <p className="h-sec">B. Preferred Industry</p>
              <p className="mb-4 text-xs text-gray-500">Where candidates want their next job. A candidate choosing several industries is counted in each, so totals can exceed the unique count.</p>
              <Bars rows={data.preferred_industry} onPick={(n) => open("preferred", n)} testId="demand-preferred" showNew />
            </Card>
          </div>
          <Card data-testid="demand-recommendations">
            <p className="h-sec">Job Posting Recommendations</p>
            <p className="mb-4 text-xs text-gray-500">Based on preferred-industry counts. High ≥ 25% of filtered candidates · Moderate 10–25% · Low &lt; 10%. Suggestions only — no job is posted automatically.</p>
            <div className="space-y-2">
              {data.recommendations.map((r) => (
                <div key={r.industry} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-100 p-4" data-testid={`rec-${r.industry}`}>
                  <div>
                    <p className="font-bold">{r.industry}</p>
                    <p className="text-sm text-gray-500">{r.preferred_candidates} preferred candidate{r.preferred_candidates === 1 ? "" : "s"} · {r.published_jobs} published job{r.published_jobs === 1 ? "" : "s"}{r.candidates_per_job !== null ? ` · ${r.candidates_per_job} candidates per job` : ""}</p>
                  </div>
                  <Badge label={`${r.level} Availability`} color={LEVEL_COLOR[r.level]} />
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <p className="h-sec mb-4">Paid vs Free by Current Industry</p>
            <table className="w-full text-sm" data-testid="demand-paid-free">
              <thead className="text-left text-xs uppercase text-gray-400"><tr><th className="py-2">Industry</th><th>Paid</th><th>Free</th><th>Total</th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {data.current_industry.map((r) => <tr key={r.name}><td className="py-2 font-semibold">{r.name}</td><td>{r.paid}</td><td>{r.free}</td><td>{r.count}</td></tr>)}
              </tbody>
            </table>
          </Card>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card><p className="h-sec mb-4">Current Designation</p><Bars rows={data.current_designation} testId="demand-cur-desig" /></Card>
            <Card><p className="h-sec mb-4">Preferred Designation</p><Bars rows={data.preferred_designation} testId="demand-pref-desig" /></Card>
            <Card><p className="h-sec mb-1">Experience</p><p className="mb-4 text-xs text-gray-500">From the experience range candidates selected at registration.</p><Bars rows={data.experience} testId="demand-exp" /></Card>
            <Card><p className="h-sec mb-4">Preferred Work Mode</p><Bars rows={data.work_mode} testId="demand-wm" /></Card>
            <Card><p className="h-sec mb-4">Preferred Location</p><Bars rows={data.location} testId="demand-loc" /></Card>
            <Card><p className="h-sec mb-1">Preferred Country</p><p className="mb-4 text-xs text-gray-500">Derived from the “Preferred Job Location / Country” field.</p><Bars rows={data.country} testId="demand-country" /></Card>
          </div>
        </div>
      )}
      {list ? <CandidateList {...list} onClose={() => setList(null)} /> : null}
    </>
  );
}

const STAGES = [["saved", "Jobs saved / tracked"], ["contacted", "Contacted recruiters"], ["applied", "Independently applied"],
  ["responded", "Recruiter responses"], ["interview_scheduled", "Interview calls received"], ["interview_completed", "Interviews completed"],
  ["offer_received", "Offers received"], ["hired", "Reported hired"]];

function EvidenceViewer({ ev, onClose }) {
  const { data: url, isLoading, isError } = useQuery({
    queryKey: ["evidence", ev.evidence_id],
    queryFn: async () => URL.createObjectURL(await fetchBlob(`/admin/success/evidence/${ev.evidence_id}`)),
    staleTime: Infinity,
  });
  return (
    <Modal open onClose={onClose} wide>
      <div className="mb-3 flex items-center justify-between">
        <p className="font-extrabold">{ev.original_filename}</p>
        <button onClick={onClose} data-testid="evidence-close"><X className="h-5 w-5" /></button>
      </div>
      {isLoading ? <Spinner /> : isError ? <p className="text-red-600">Could not load file.</p> : ev.content_type === "application/pdf"
        ? <iframe title="evidence" src={url} className="h-[70vh] w-full rounded-lg border" data-testid="evidence-frame" />
        : <img src={url} alt="evidence" className="max-h-[70vh] w-full object-contain" data-testid="evidence-image" />}
    </Modal>
  );
}

const vBadge = (v) => (v === "verified" ? <Badge label="Verified" color="success" /> : <Badge label="Candidate reported" color="info" />);

export function AdminSuccess() {
  const qc = useQueryClient();
  const [range, setRange] = useState({ start: "", end: "" });
  const [f, setF] = useState({ industry: "All", company: "", designation: "", job_id: "", location: "" });
  const [ev, setEv] = useState(null);
  const query = clean({ ...range, ...f });
  const { data, isLoading } = useQuery({ queryKey: ["admin-success", query], queryFn: () => api("/admin/success", { query }) });
  const verify = async (t, kind, verified) => {
    try {
      await api(`/admin/success/${t.tracker_id}/verify`, { method: "POST", body: { kind, verified } });
      notify(verified ? "Marked as verified" : "Verification removed", "success");
      qc.invalidateQueries({ queryKey: ["admin-success"] });
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const bind = (k) => ({ value: f[k], onChange: (e) => setF((x) => ({ ...x, [k]: e.target.value })) });
  return (
    <>
      <PageHeader title="JobRadar Success Analytics" subtitle="Candidate-reported progress on jobs they found through JobRadar. Tracking a job is never counted as an application."
        right={<Button variant="outline" title="Export CSV / Excel" icon={<Download className="h-4 w-4" />} data-testid="success-export"
          onClick={() => downloadFile("/admin/success/export", query, "jobradar-success-report.csv").catch((e) => notify(errMsg(e), "error"))} />} />
      <Card className="mb-6 space-y-4" data-testid="success-filters">
        <DateRange {...range} onChange={setRange} />
        <SelectChips label="Industry" value={f.industry} options={[...INDUSTRIES, "Other"]} onChange={(v) => setF((x) => ({ ...x, industry: v }))} testId="sf-industry" short={(o) => INDUSTRY_SHORT[o] || o} />
        <div className="grid gap-4 md:grid-cols-4">
          <Input label="Company" {...bind("company")} data-testid="sf-company" />
          <Input label="Job designation" {...bind("designation")} data-testid="sf-designation" />
          <Input label="Job ID" {...bind("job_id")} data-testid="sf-jobid" />
          <Input label="Location" {...bind("location")} data-testid="sf-location" />
        </div>
      </Card>
      {isLoading || !data ? <Spinner /> : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" data-testid="success-totals">
            {STAGES.map(([k, l]) => (
              <Stat key={k} label={l} value={data.totals[k].records} hint={`${data.totals[k].candidates} unique candidate${data.totals[k].candidates === 1 ? "" : "s"}`} testId={`success-total-${k}`} />
            ))}
          </div>
          <p className="text-xs text-gray-400">Big number = unique candidate–job records that ever reached the stage (repeat updates are counted once). Hint = unique candidates. A stage counts only when the candidate explicitly selected it — e.g. an application is counted only when they confirm “Applied”. Date filters use the date tracking started.</p>
          <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
            <Card data-testid="success-conversions">
              <p className="h-sec mb-4">Conversion Rates</p>
              <div className="space-y-4">
                {data.conversions.map((c) => (
                  <div key={c.label}>
                    <div className="flex justify-between text-sm"><span className="font-semibold">{c.label}</span><b className="text-brand">{c.rate === null ? "—" : `${c.rate}%`}</b></div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-brand-soft"><div className="h-full bg-brand" style={{ width: `${c.rate || 0}%` }} /></div>
                    <p className="mt-1 text-xs text-gray-500">{c.numerator} ÷ {c.denominator}. {c.explain}</p>
                  </div>
                ))}
              </div>
            </Card>
            <Card data-testid="success-verification">
              <p className="h-sec mb-4">Candidate-Reported vs Verified</p>
              <div className="grid grid-cols-2 gap-3">
                {[["Interview calls — reported", data.verification.interview_reported], ["Interview calls — verified", data.verification.interview_verified],
                  ["Hires — reported", data.verification.hire_reported], ["Hires — verified", data.verification.hire_verified]].map(([l, v]) => (
                  <div key={l} className="rounded-xl bg-brand-mist p-4"><p className="text-2xl font-extrabold text-brand">{v}</p><p className="text-xs font-semibold text-gray-500">{l}</p></div>
                ))}
              </div>
              <p className="mt-3 text-xs text-gray-500">Outcomes are “Candidate reported” until an admin reviews evidence and marks them verified.</p>
            </Card>
          </div>
          <Card>
            <p className="h-sec mb-4">Tracked Jobs ({data.total_records})</p>
            {data.records.length === 0 ? <EmptyState title="No tracked jobs yet" data-testid="success-empty" /> : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase text-gray-400"><tr><th className="py-2 pr-3">Candidate</th><th className="pr-3">Job</th><th className="pr-3">Status</th><th className="pr-3">Outcome & verification</th><th>Evidence</th></tr></thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.records.map((t) => (
                      <tr key={t.tracker_id} className="align-top" data-testid={`success-row-${t.tracker_id}`}>
                        <td className="py-3 pr-3"><p className="font-bold">{t.candidate_name || "—"}</p><p className="text-xs text-gray-500">{t.candidate_email}</p></td>
                        <td className="pr-3"><p className="font-semibold">{t.designation}</p><p className="text-xs text-gray-500">{t.company} · {t.location} · {t.job_id}</p></td>
                        <td className="pr-3"><Badge label={t.status_label} color="brand" /><p className="mt-1 text-xs text-gray-400">updated {formatDate(t.updated_at)}</p></td>
                        <td className="space-y-2 pr-3">
                          {t.interview_verification ? (
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs">Interview {formatDate(t.interview?.date)} ({t.interview?.mode})</span>{vBadge(t.interview_verification)}
                              <Button size="sm" variant="ghost" title={t.interview_verification === "verified" ? "Unverify" : "Verify"} icon={<ShieldCheck className="h-3.5 w-3.5" />}
                                onClick={() => verify(t, "interview", t.interview_verification !== "verified")} data-testid={`verify-interview-${t.tracker_id}`} />
                            </div>
                          ) : null}
                          {t.hire_verification ? (
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs">Hired: {t.hire?.designation} at {t.hire?.company}, joining {formatDate(t.hire?.joining_date)}</span>{vBadge(t.hire_verification)}
                              <Button size="sm" variant="ghost" title={t.hire_verification === "verified" ? "Unverify" : "Verify"} icon={<ShieldCheck className="h-3.5 w-3.5" />}
                                onClick={() => verify(t, "hire", t.hire_verification !== "verified")} data-testid={`verify-hire-${t.tracker_id}`} />
                            </div>
                          ) : null}
                          {!t.interview_verification && !t.hire_verification ? <span className="text-xs text-gray-400">—</span> : null}
                        </td>
                        <td>
                          {t.evidence.length === 0 ? <span className="text-xs text-gray-400">None</span> : t.evidence.map((e) => (
                            <button key={e.evidence_id} onClick={() => setEv(e)} className="flex items-center gap-1 text-xs font-bold text-brand hover:underline" data-testid={`evidence-view-${e.evidence_id}`}>
                              <Eye className="h-3.5 w-3.5" />{data.evidence_kinds[e.kind]}
                            </button>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>
      )}
      {ev ? <EvidenceViewer ev={ev} onClose={() => setEv(null)} /> : null}
    </>
  );
}
