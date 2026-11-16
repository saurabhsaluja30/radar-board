import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, ClipboardCheck, Megaphone, Search, Users } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, INDUSTRIES, INDUSTRY_SHORT, JOB_SOURCES, JOB_STATUS_LABEL, JOB_STATUSES, MATCH_STATUS_LABEL, NOTICE_PERIODS, PREF_WORK_MODES, WORK_MODES } from "@/lib/constants";
import { Badge, Button, Card, Chip, EmptyState, errMsg, Input, notify, PageHeader, Spinner } from "@/components/kit";
import { MatchTable } from "@/components/MatchTable";

const clean = (o) => Object.fromEntries(Object.entries(o).filter(([, v]) => v !== "" && v !== "All" && v != null));

const Chips = ({ label, value, options, onChange, testId, short }) => (
  <div>
    <p className="mb-1.5 text-xs font-bold uppercase tracking-wider text-gray-400">{label}</p>
    <div className="flex flex-wrap gap-1.5">
      {["All", ...options].map((o) => <Chip key={o} label={short ? short(o) : o} selected={value === o} onClick={() => onChange(o)} data-testid={`${testId}-${o}`} />)}
    </div>
  </div>
);

const SmallInput = (props) => <Input {...props} className="min-w-0" />;

export function SmartMatchHome() {
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["sm-analytics", {}], queryFn: () => api("/admin/smartmatch/analytics") });
  const tiles = [
    [Briefcase, "Job Management", "Add, verify, publish, pause, expire jobs", "/admin/jobs"],
    [Search, "Find Matching Candidates", "Pick an open, verified job", "/admin/jobs"],
    [Users, "Find Matching Jobs", "Pick a candidate profile", "/admin/smartmatch/candidates"],
    [ClipboardCheck, "Match Review", `${data?.matches.awaiting_review ?? "—"} awaiting review`, "/admin/smartmatch/review"],
    [Megaphone, "Alerts & Templates", "Message template, related industries, audit log", "/admin/smartmatch/alerts"],
  ];
  return (
    <>
      <PageHeader title="JobRadar SmartMatch" subtitle="Rule-based candidate–job matching with admin review. Scores are advisory — people make every decision." />
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {tiles.map(([Icon, t, d, to]) => (
          <button key={t} onClick={() => navigate(to)} className="flex items-start gap-4 rounded-2xl border border-gray-200 bg-white p-5 text-left transition-transform hover:-translate-y-0.5 hover:border-brand" data-testid={`sm-tile-${t}`}>
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft"><Icon className="h-5 w-5 text-brand" /></span>
            <span><span className="block font-extrabold">{t}</span><span className="text-sm text-gray-500">{d}</span></span>
          </button>
        ))}
      </div>
      <div className="mt-10"><SmartMatchAnalytics embedded /></div>
    </>
  );
}

export function SmartMatchJob() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ status: "All", min_score: "", designation: "", skills: "", notice_period: "All", candidate_status: "All", min_exp: "", max_exp: "", max_ctc: "" });
  const { data } = useQuery({ queryKey: ["admin-job", id], queryFn: () => api(`/admin/jobs/${id}`) });
  const j = data?.job;
  const find = async () => {
    setBusy(true);
    try {
      const res = await api(`/admin/smartmatch/jobs/${id}/find-candidates`, { method: "POST" });
      notify(`${res.scored} candidates scored`, "success");
      qc.invalidateQueries({ queryKey: ["sm-matches"] });
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const bind = (k) => ({ value: f[k], onChange: (e) => setF((x) => ({ ...x, [k]: e.target.value })) });
  if (!j) return <Spinner />;
  return (
    <>
      <PageHeader title={j.title} subtitle={`${j.company} · ${j.location || j.city || ""} · ${j.job_id}`}
        right={<Button title="FIND MATCHING CANDIDATES" loading={busy} icon={<Search className="h-4 w-4" />} onClick={find} data-testid="find-candidates-btn" />} />
      <div className="mb-5 flex flex-wrap gap-2">
        <Badge label={JOB_STATUS_LABEL[j.status] || j.status} color={j.status === "Published" ? "success" : "info"} />
        <Badge label={j.verification_status} color={j.verification_status === "Verified" ? "success" : "warning"} />
        <Badge label={j.job_source || "Source not set"} color="info" />
        {j.expiry_date ? <Badge label={`Expires ${formatDate(j.expiry_date)}`} color="info" /> : null}
        <span className="text-xs text-gray-500">Mandatory: {j.required_skills || "—"} · Preferred: {j.preferred_skills || "—"} · Exp {j.experience_min ?? "?"}–{j.experience_max ?? "?"} yrs</span>
      </div>
      <Card className="mb-5 space-y-4" data-testid="job-match-filters">
        <Chips label="Review status" value={f.status} options={Object.keys(MATCH_STATUS_LABEL)} short={(o) => MATCH_STATUS_LABEL[o] || o} onChange={(v) => setF((x) => ({ ...x, status: v }))} testId="jmf-status" />
        <div className="grid gap-3 md:grid-cols-4 lg:grid-cols-8">
          <SmallInput label="Min score" {...bind("min_score")} data-testid="jmf-min-score" />
          <SmallInput label="Designation" {...bind("designation")} data-testid="jmf-designation" />
          <SmallInput label="Skill" {...bind("skills")} data-testid="jmf-skills" />
          <SmallInput label="Min exp" {...bind("min_exp")} data-testid="jmf-min-exp" />
          <SmallInput label="Max exp" {...bind("max_exp")} data-testid="jmf-max-exp" />
          <SmallInput label="Max expected CTC" {...bind("max_ctc")} data-testid="jmf-max-ctc" />
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Chips label="Notice period" value={f.notice_period} options={NOTICE_PERIODS} onChange={(v) => setF((x) => ({ ...x, notice_period: v }))} testId="jmf-notice" />
          <Chips label="Candidate status" value={f.candidate_status} options={["Active", "Inactive"]} onChange={(v) => setF((x) => ({ ...x, candidate_status: v }))} testId="jmf-cstatus" />
        </div>
      </Card>
      <MatchTable filters={clean({ ...f, job_id: id })} mode="job" title="Matching candidates" />
    </>
  );
}

export function SmartMatchCandidates() {
  const navigate = useNavigate();
  const [f, setF] = useState({ q: "", industry: "All", designation: "", skills: "", location: "", country: "", work_mode: "All", notice_period: "All", candidate_status: "All", min_exp: "", max_exp: "" });
  const [page, setPage] = useState(1);
  const query = clean({ ...f, page });
  const { data, isLoading } = useQuery({ queryKey: ["sm-candidates", query], queryFn: () => api("/admin/smartmatch/candidates", { query }) });
  const bind = (k) => ({ value: f[k], onChange: (e) => { setPage(1); setF((x) => ({ ...x, [k]: e.target.value })); } });
  const setChip = (k) => (v) => { setPage(1); setF((x) => ({ ...x, [k]: v })); };
  const rows = data?.candidates || [];
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <>
      <PageHeader title="SmartMatch Candidates" subtitle="Open a candidate to find matching jobs." />
      <Card className="mb-5 space-y-4" data-testid="smc-filters">
        <div className="grid gap-3 md:grid-cols-4 lg:grid-cols-7">
          <SmallInput label="Name / email / ID" {...bind("q")} data-testid="smc-q" />
          <SmallInput label="Designation" {...bind("designation")} data-testid="smc-designation" />
          <SmallInput label="Skill" {...bind("skills")} data-testid="smc-skills" />
          <SmallInput label="Location" {...bind("location")} data-testid="smc-location" />
          <SmallInput label="Country" {...bind("country")} data-testid="smc-country" />
          <SmallInput label="Min exp" {...bind("min_exp")} data-testid="smc-min-exp" />
          <SmallInput label="Max exp" {...bind("max_exp")} data-testid="smc-max-exp" />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Chips label="Industry" value={f.industry} options={INDUSTRIES} short={(o) => INDUSTRY_SHORT[o] || o} onChange={setChip("industry")} testId="smc-ind" />
          <Chips label="Work mode" value={f.work_mode} options={PREF_WORK_MODES} onChange={setChip("work_mode")} testId="smc-wm" />
          <Chips label="Notice period" value={f.notice_period} options={NOTICE_PERIODS} onChange={setChip("notice_period")} testId="smc-notice" />
          <Chips label="Candidate status" value={f.candidate_status} options={["Active", "Inactive"]} onChange={setChip("candidate_status")} testId="smc-status" />
        </div>
      </Card>
      {isLoading ? <Spinner /> : rows.length === 0 ? <EmptyState title="No candidates match" /> : (
        <Card className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead className="bg-gray-50/70 text-left text-xs uppercase tracking-wider text-gray-400">
              <tr><th className="px-4 py-3">Candidate</th><th className="px-3">Designation · Exp</th><th className="px-3">Skills</th><th className="px-3">Prefers</th><th className="px-3">Profile</th><th className="px-3" /></tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((c) => (
                <tr key={c.user_id} className="align-top" data-testid={`smc-row-${c.email}`}>
                  <td className="px-4 py-3"><p className="font-bold">{c.full_name || "—"}</p><p className="text-xs text-gray-500">{c.user_id}</p></td>
                  <td className="px-3 py-3 text-xs">{c.current_designation || "—"}<br />{c.total_experience ?? "—"} yrs · {c.notice_period || "notice —"}</td>
                  <td className="max-w-[220px] truncate px-3 py-3 text-xs">{c.primary_skills.join(", ") || "—"}</td>
                  <td className="px-3 py-3 text-xs">{c.preferred_titles.join(", ") || "—"}<br />{c.preferred_locations.join(", ") || "—"} · {c.preferred_work_mode || "—"}</td>
                  <td className="px-3 py-3"><Badge label={`${c.completion}% complete`} color={c.completion === 100 ? "success" : c.completion >= 60 ? "warning" : "error"} />
                    <p className="mt-1 text-[11px] text-gray-500">{c.profile_status}{c.job_alert_consent ? " · alerts on" : " · no alert consent"}</p></td>
                  <td className="px-3 py-3"><Button size="sm" variant="outline" title="Find Matching Jobs" onClick={() => navigate(`/admin/smartmatch/candidate/${c.user_id}`)} data-testid={`smc-open-${c.email}`} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {pages > 1 ? (
            <div className="flex items-center justify-end gap-3 border-t border-gray-100 p-4 text-sm">
              <Button size="sm" variant="ghost" title="‹ Prev" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="smc-prev" />
              <span>Page {page} of {pages}</span>
              <Button size="sm" variant="ghost" title="Next ›" disabled={page >= pages} onClick={() => setPage(page + 1)} data-testid="smc-next" />
            </div>
          ) : null}
        </Card>
      )}
    </>
  );
}

export function SmartMatchCandidate() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ status: "All", min_score: "", job_status: "All", work_mode: "All", industry: "All", location: "", country: "" });
  const { data } = useQuery({ queryKey: ["sm-candidate", id], queryFn: () => api(`/admin/smartmatch/candidates/${id}`) });
  const c = data?.candidate;
  const find = async () => {
    setBusy(true);
    try {
      const res = await api(`/admin/smartmatch/candidates/${id}/find-jobs`, { method: "POST" });
      notify(`${res.scored} open jobs scored`, "success");
      qc.invalidateQueries({ queryKey: ["sm-matches"] });
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  if (!c) return <Spinner />;
  const rows = [["Current", `${c.current_designation || "—"} at ${c.current_company || "—"}`], ["Industry", c.industry || "—"],
    ["Experience", c.total_experience != null ? `${c.total_experience} yrs` : "—"], ["Current CTC", c.current_salary || "—"],
    ["Expected CTC", c.expected_ctc ? `${c.expected_ctc_currency} ${Number(c.expected_ctc).toLocaleString("en-IN")}` : "—"],
    ["Primary skills", c.primary_skills.join(", ") || "—"], ["Secondary skills", c.secondary_skills.join(", ") || "—"],
    ["Preferred titles", c.preferred_titles.join(", ") || "—"], ["Preferred industries", c.preferred_industries.join(", ") || "—"],
    ["Preferred locations", `${c.preferred_locations.join(", ") || "—"}${c.preferred_country ? ` · ${c.preferred_country}` : ""}`],
    ["Work mode · Type", `${c.preferred_work_mode || "—"} · ${c.employment_type_pref || "—"}`],
    ["Notice · Relocate", `${c.notice_period || "—"} · ${c.willing_to_relocate ? "Willing to relocate" : "Not specified / no"}`],
    ["Alerts", c.job_alert_consent ? `Consented · ${c.job_alert_frequency || "Instant"}` : "No consent"],
    ["Last profile update", formatDate(c.updated_at)]];
  return (
    <>
      <PageHeader title={c.full_name || "Candidate"} subtitle={`${c.user_id} · ${c.email}`}
        right={<Button title="FIND MATCHING JOBS" loading={busy} icon={<Search className="h-4 w-4" />} onClick={find} data-testid="find-jobs-btn" />} />
      <Card className="mb-5" data-testid="sm-candidate-profile">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Badge label={`${c.completion}% complete`} color={c.completion === 100 ? "success" : "warning"} />
          <Badge label={c.profile_status} color={c.profile_status === "Active" ? "success" : "error"} />
          {c.missing.length ? <span className="text-xs text-amber-700">Missing: {c.missing.join(", ")}</span> : null}
        </div>
        <div className="grid gap-x-8 gap-y-1.5 text-sm md:grid-cols-2">
          {rows.map(([k, v]) => <p key={k}><span className="text-gray-500">{k}:</span> <b className="font-semibold">{v}</b></p>)}
        </div>
      </Card>
      <Card className="mb-5 space-y-4">
        <Chips label="Review status" value={f.status} options={Object.keys(MATCH_STATUS_LABEL)} short={(o) => MATCH_STATUS_LABEL[o] || o} onChange={(v) => setF((x) => ({ ...x, status: v }))} testId="cmf-status" />
        <div className="grid gap-4 md:grid-cols-2">
          <Chips label="Job status" value={f.job_status} options={JOB_STATUSES} short={(o) => JOB_STATUS_LABEL[o] || o} onChange={(v) => setF((x) => ({ ...x, job_status: v }))} testId="cmf-jstatus" />
          <Chips label="Work mode" value={f.work_mode} options={WORK_MODES} onChange={(v) => setF((x) => ({ ...x, work_mode: v }))} testId="cmf-wm" />
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          <SmallInput label="Min score" value={f.min_score} onChange={(e) => setF((x) => ({ ...x, min_score: e.target.value }))} data-testid="cmf-min-score" />
          <SmallInput label="Location" value={f.location} onChange={(e) => setF((x) => ({ ...x, location: e.target.value }))} data-testid="cmf-location" />
          <SmallInput label="Country" value={f.country} onChange={(e) => setF((x) => ({ ...x, country: e.target.value }))} data-testid="cmf-country" />
        </div>
      </Card>
      <MatchTable filters={clean({ ...f, candidate_id: id })} mode="candidate" title="Matching jobs" />
    </>
  );
}

export function SmartMatchReview() {
  const [f, setF] = useState({ status: "awaiting", min_score: "", max_score: "", industry: "All", source: "All", location: "", company: "", job_title: "", designation: "", skills: "", work_mode: "All", country: "", notice_period: "All", candidate_status: "All", job_status: "All", min_exp: "", max_exp: "", max_ctc: "" });
  const bind = (k) => ({ value: f[k], onChange: (e) => setF((x) => ({ ...x, [k]: e.target.value })) });
  const setChip = (k) => (v) => setF((x) => ({ ...x, [k]: v }));
  return (
    <>
      <PageHeader title="Match Review" subtitle="Approve or reject system suggestions. Nothing reaches candidates until you approve and send it." />
      <Card className="mb-5 space-y-4" data-testid="review-filters">
        <Chips label="Review status" value={f.status} options={["awaiting", ...Object.keys(MATCH_STATUS_LABEL)]} short={(o) => (o === "awaiting" ? "Awaiting review" : MATCH_STATUS_LABEL[o] || o)} onChange={setChip("status")} testId="rf-status" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Chips label="Industry" value={f.industry} options={INDUSTRIES} short={(o) => INDUSTRY_SHORT[o] || o} onChange={setChip("industry")} testId="rf-ind" />
          <Chips label="Job source" value={f.source} options={JOB_SOURCES} onChange={setChip("source")} testId="rf-src" />
          <Chips label="Job status" value={f.job_status} options={JOB_STATUSES} short={(o) => JOB_STATUS_LABEL[o] || o} onChange={setChip("job_status")} testId="rf-jstatus" />
          <Chips label="Work mode" value={f.work_mode} options={WORK_MODES} onChange={setChip("work_mode")} testId="rf-wm" />
          <Chips label="Notice period" value={f.notice_period} options={NOTICE_PERIODS} onChange={setChip("notice_period")} testId="rf-notice" />
          <Chips label="Candidate status" value={f.candidate_status} options={["Active", "Inactive"]} onChange={setChip("candidate_status")} testId="rf-cstatus" />
        </div>
        <div className="grid gap-3 md:grid-cols-4 lg:grid-cols-6">
          <SmallInput label="Min score" {...bind("min_score")} data-testid="rf-min-score" />
          <SmallInput label="Max score" {...bind("max_score")} data-testid="rf-max-score" />
          <SmallInput label="Job title" {...bind("job_title")} data-testid="rf-job-title" />
          <SmallInput label="Company" {...bind("company")} data-testid="rf-company" />
          <SmallInput label="Job location" {...bind("location")} data-testid="rf-location" />
          <SmallInput label="Job country" {...bind("country")} data-testid="rf-country" />
          <SmallInput label="Candidate designation" {...bind("designation")} data-testid="rf-designation" />
          <SmallInput label="Candidate skill" {...bind("skills")} data-testid="rf-skills" />
          <SmallInput label="Min exp" {...bind("min_exp")} data-testid="rf-min-exp" />
          <SmallInput label="Max exp" {...bind("max_exp")} data-testid="rf-max-exp" />
          <SmallInput label="Max expected CTC" {...bind("max_ctc")} data-testid="rf-max-ctc" />
        </div>
      </Card>
      <MatchTable filters={clean(f)} mode="review" title="Matches" />
    </>
  );
}

export function SmartMatchAlerts() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["sm-template"], queryFn: () => api("/admin/smartmatch/template") });
  const { data: meta } = useQuery({ queryKey: ["sm-meta"], queryFn: () => api("/admin/smartmatch/meta") });
  const { data: audit } = useQuery({ queryKey: ["sm-audit"], queryFn: () => api("/admin/smartmatch/audit") });
  const [t, setT] = useState(null);
  const [pair, setPair] = useState(["", ""]);
  useEffect(() => { if (data?.template) setT(data.template); }, [data]);
  const save = async () => {
    try {
      await api("/admin/smartmatch/template", { method: "PUT", body: t });
      notify("Template saved", "success");
      qc.invalidateQueries({ queryKey: ["sm-audit"] });
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const savePairs = async (pairs) => {
    try {
      await api("/admin/smartmatch/related-industries", { method: "PUT", body: { pairs } });
      qc.invalidateQueries({ queryKey: ["sm-meta"] });
      notify("Related industries saved", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const pairs = meta?.related_industries || [];
  return (
    <>
      <PageHeader title="Alerts, Templates & Audit" />
      <div className="grid gap-6 lg:grid-cols-2">
        {t ? (
          <Card className="space-y-4" data-testid="template-card">
            <p className="h-sec">Job alert template</p>
            <p className="text-xs text-gray-500">Placeholders: {data.placeholders.join(" ")}</p>
            <Input label="Subject" value={t.subject} onChange={(e) => setT({ ...t, subject: e.target.value })} data-testid="template-subject" />
            <Input multiline rows={14} label="Message" value={t.body} onChange={(e) => setT({ ...t, body: e.target.value })} data-testid="template-body" />
            <Button title="Save Template" onClick={save} data-testid="template-save" />
          </Card>
        ) : <Spinner />}
        <div className="space-y-6">
          <Card className="space-y-3" data-testid="related-industries">
            <p className="h-sec">Related industries (admin approved)</p>
            <p className="text-xs text-gray-500">Candidates get partial industry credit (5/10) for jobs in an approved related industry.</p>
            {pairs.map((p, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-brand-mist px-3 py-2 text-sm">
                <span>{p[0]} ↔ {p[1]}</span>
                <button className="text-xs font-bold text-red-600" onClick={() => savePairs(pairs.filter((_, k) => k !== i))} data-testid={`related-remove-${i}`}>Remove</button>
              </div>
            ))}
            <div className="flex flex-wrap gap-2">
              {[0, 1].map((k) => (
                <select key={k} value={pair[k]} onChange={(e) => setPair((x) => (k ? [x[0], e.target.value] : [e.target.value, x[1]]))} className="field w-auto py-2" data-testid={`related-select-${k}`}>
                  <option value="">Select industry</option>
                  {INDUSTRIES.map((x) => <option key={x}>{x}</option>)}
                </select>
              ))}
              <Button size="sm" title="Add" disabled={!pair[0] || !pair[1] || pair[0] === pair[1]} onClick={() => { savePairs([...pairs, pair]); setPair(["", ""]); }} data-testid="related-add" />
            </div>
          </Card>
          <Card data-testid="audit-log">
            <p className="h-sec mb-3">Admin audit trail</p>
            <div className="max-h-[420px] space-y-1 overflow-auto text-xs">
              {(audit?.entries || []).map((a) => (
                <p key={a.audit_id} className="border-b border-gray-100 py-1.5"><b>{a.action.replaceAll("_", " ")}</b> · {a.entity} {a.entity_id} · {a.admin_email} · {new Date(a.at).toLocaleString("en-IN")}</p>
              ))}
              {audit?.entries?.length === 0 ? <p className="text-gray-500">No actions yet.</p> : null}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

const Stat = ({ label, value, testId }) => (
  <div className="rounded-xl border border-gray-100 bg-white p-4" data-testid={testId}><p className="text-2xl font-extrabold text-brand">{value ?? "—"}</p><p className="text-xs font-semibold text-gray-500">{label}</p></div>
);

export function SmartMatchAnalytics({ embedded }) {
  const [f, setF] = useState({ start: "", end: "", industry: "All", source: "All", location: "", designation: "" });
  const query = clean(f);
  const { data } = useQuery({ queryKey: ["sm-analytics", query], queryFn: () => api("/admin/smartmatch/analytics", { query }) });
  const bind = (k) => ({ value: f[k], onChange: (e) => setF((x) => ({ ...x, [k]: e.target.value })) });
  return (
    <>
      {embedded ? <p className="h-sec mb-4">SmartMatch Analytics</p> : <PageHeader title="SmartMatch Analytics" subtitle="Calculated live from matches, alerts and candidate-reported progress." />}
      <Card className="mb-5 space-y-4" data-testid="sma-filters">
        <div className="grid gap-3 md:grid-cols-4">
          <Input label="From" type="date" {...bind("start")} data-testid="sma-start" />
          <Input label="To" type="date" {...bind("end")} data-testid="sma-end" />
          <Input label="Location" {...bind("location")} data-testid="sma-location" />
          <Input label="Designation" {...bind("designation")} data-testid="sma-designation" />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Chips label="Industry" value={f.industry} options={INDUSTRIES} short={(o) => INDUSTRY_SHORT[o] || o} onChange={(v) => setF((x) => ({ ...x, industry: v }))} testId="sma-ind" />
          <Chips label="Job source" value={f.source} options={JOB_SOURCES} onChange={(v) => setF((x) => ({ ...x, source: v }))} testId="sma-src" />
        </div>
      </Card>
      {!data ? <Spinner /> : (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
            <Stat label="Registered candidates" value={data.candidates.total} testId="sma-cand-total" />
            <Stat label="Active candidates" value={data.candidates.active} testId="sma-cand-active" />
            <Stat label="Complete profiles" value={data.candidates.complete_profiles} testId="sma-cand-complete" />
            <Stat label="Jobs received" value={data.jobs.received} testId="sma-jobs-received" />
            <Stat label="Verified jobs" value={data.jobs.verified} testId="sma-jobs-verified" />
            <Stat label="Active jobs (matchable)" value={data.jobs.active} testId="sma-jobs-active" />
            <Stat label="Expired jobs" value={data.jobs.expired} testId="sma-jobs-expired" />
            <Stat label="Candidates matched" value={data.matches.candidates_matched} testId="sma-matched" />
            <Stat label="Awaiting review" value={data.matches.awaiting_review} testId="sma-awaiting" />
            <Stat label="Matches approved" value={data.matches.approved} testId="sma-approved" />
            <Stat label="Shared with candidates" value={data.matches.shared} testId="sma-shared" />
            <Stat label="Candidate responses" value={data.matches.responses} testId="sma-responses" />
            <Stat label="Reported applying" value={data.matches.applied} testId="sma-applied" />
            <Stat label="Interviews reported" value={data.matches.interviews} testId="sma-interviews" />
            <Stat label="Offers reported" value={data.outcomes.offers_reported} testId="sma-offers" />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card data-testid="sma-kpis">
              <p className="h-sec mb-3">Performance indicators</p>
              {data.kpis.map((k) => (
                <div key={k.label} className="flex items-start justify-between gap-4 border-b border-gray-100 py-2 text-sm">
                  <span><b>{k.label}</b><span className="block text-xs text-gray-500">{k.explain}</span></span>
                  <b className="shrink-0 text-lg text-brand">{k.value === null ? "—" : `${k.value}%`}</b>
                </div>
              ))}
            </Card>
            <Card data-testid="sma-verified">
              <p className="h-sec mb-3">Candidate-reported vs verified (matched jobs)</p>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="Interviews — candidate reported" value={data.outcomes.interviews_reported} />
                <Stat label="Interviews — verified" value={data.outcomes.interviews_verified} />
                <Stat label="Hires — candidate reported" value={data.outcomes.hires_reported} />
                <Stat label="Hires — verified" value={data.outcomes.hires_verified} />
              </div>
              <p className="mt-3 text-xs text-gray-500">Saved or “interested” jobs are never counted as applications. Verify outcomes in JobRadar Success Analytics.</p>
              <p className="mt-2 text-xs text-gray-500">Alerts: {data.alerts.sent} delivered ({data.alerts.in_app_sent} in-app, {data.alerts.email_sent} email) · {data.alerts.failed} failed</p>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
