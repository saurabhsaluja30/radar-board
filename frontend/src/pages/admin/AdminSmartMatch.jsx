import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, ClipboardCheck, Megaphone, Search, Users } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, INDUSTRIES, INDUSTRY_SHORT, JOB_SOURCES, JOB_STATUS_LABEL, JOB_STATUSES, MATCH_STATUS_LABEL, NOTICE_PERIODS, PREF_WORK_MODES, WORK_MODES } from "@/lib/constants";
import { Badge, Button, Card, Chip, EmptyState, errMsg, Input, notify, PageHeader, Spinner, Switch } from "@/components/kit";
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

const WEIGHT_LABEL = { skills: "Skills", designation: "Designation", experience: "Experience", industry: "Industry",
  location: "Location", salary: "Salary", work_mode: "Work mode" };

function WeightsCard({ onSaved }) {
  const { data, refetch } = useQuery({ queryKey: ["sm-weights"], queryFn: () => api("/admin/smartmatch/weights") });
  const [w, setW] = useState(null);
  const [busy, setBusy] = useState("");
  useEffect(() => { if (data) setW(Object.fromEntries(Object.entries(data.weights).map(([k, v]) => [k, String(v)]))); }, [data]);
  if (!w) return null;
  const total = Object.values(w).reduce((a, v) => a + (Number(v) || 0), 0);
  const save = async () => {
    setBusy("save");
    try {
      await api("/admin/smartmatch/weights", { method: "PUT", body: { weights: Object.fromEntries(Object.entries(w).map(([k, v]) => [k, Number(v) || 0])) } });
      await refetch();
      notify("Weights saved. Candidates' My Matches pages use them now; rescore to update stored matches.", "success");
      onSaved?.();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy("");
    }
  };
  const rescore = async () => {
    setBusy("rescore");
    try {
      const res = await api("/admin/smartmatch/rescore-all", { method: "POST" });
      notify(`${res.queued_jobs} open jobs queued for rescoring`, "success");
      onSaved?.();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy("");
    }
  };
  return (
    <Card className="space-y-4" data-testid="sm-weights">
      <div className="flex items-center justify-between"><p className="h-sec">Matching weights</p>
        <span className={`text-sm font-bold ${total === 100 ? "text-emerald-700" : "text-red-600"}`} data-testid="sm-weights-total">Total {total}/100</span></div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 2xl:grid-cols-4">
        {Object.keys(WEIGHT_LABEL).map((k) => (
          <Input key={k} label={WEIGHT_LABEL[k]} inputMode="numeric" value={w[k]} onChange={(e) => setW((x) => ({ ...x, [k]: e.target.value.replace(/\D/g, "") }))} data-testid={`sm-weight-${k}`} />
        ))}
      </div>
      <p className="text-xs text-gray-500">Defaults: {Object.entries(data.defaults).map(([k, v]) => `${WEIGHT_LABEL[k]} ${v}`).join(" · ")}. Scores are advisory; missing information never counts as a match.</p>
      <div className="flex flex-wrap gap-2">
        <Button title="Save weights" loading={busy === "save"} disabled={total !== 100} onClick={save} data-testid="sm-weights-save" />
        <Button variant="outline" title="Rescore all open jobs" loading={busy === "rescore"} onClick={rescore} data-testid="sm-rescore" />
      </div>
    </Card>
  );
}

function AutoAlertsCard() {
  const { data, refetch } = useQuery({ queryKey: ["sm-auto-alerts"], queryFn: () => api("/admin/smartmatch/auto-alerts") });
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setS(Object.fromEntries(Object.entries(data.settings).map(([k, v]) => [k, typeof v === "boolean" ? v : String(v)]))); }, [data]);
  if (!s) return null;
  const save = async () => {
    setBusy(true);
    try {
      await api("/admin/smartmatch/auto-alerts", { method: "PUT", body: { enabled: s.enabled, min_score: Number(s.min_score), max_per_day: Number(s.max_per_day), max_job_age_days: Number(s.max_job_age_days) } });
      await refetch();
      notify("Job alert settings saved", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const set = (k) => (e) => setS((x) => ({ ...x, [k]: e.target.value.replace(/\D/g, "") }));
  return (
    <Card className="space-y-4" data-testid="sm-auto-alerts">
      <div className="flex items-center justify-between"><p className="h-sec">Automatic in-app job alerts</p>
        <Switch checked={s.enabled} onChange={(v) => setS((x) => ({ ...x, enabled: v }))} data-testid="sm-auto-alerts-switch" /></div>
      <p className="text-sm text-gray-600">{data.sent_last_7_days} alerts to {data.candidates_alerted_7_days} candidates in the last 7 days. In-app only — no email cost.</p>
      <div className="grid grid-cols-3 gap-3">
        <Input label="Minimum score" inputMode="numeric" value={s.min_score} onChange={set("min_score")} data-testid="sm-auto-min" />
        <Input label="Max alerts / candidate / day" inputMode="numeric" value={s.max_per_day} onChange={set("max_per_day")} />
        <Input label="Only jobs published in last (days)" inputMode="numeric" value={s.max_job_age_days} onChange={set("max_job_age_days")} />
      </div>
      <p className="text-xs text-gray-500">Sent when a new job is matched or a candidate's profile changes. Candidates who opted out or muted the job's category are skipped; candidates who haven't chosen a preference still get in-app alerts. Never more than one alert per job.</p>
      <Button title="Save alert settings" loading={busy} onClick={save} data-testid="sm-auto-save" />
    </Card>
  );
}

function ControlRoom() {
  const navigate = useNavigate();
  const { data, refetch } = useQuery({ queryKey: ["sm-control-room"], queryFn: () => api("/admin/smartmatch/control-room"), refetchInterval: 30000 });
  if (!data) return <Spinner />;
  const q = data.queue || {};
  const tiles = [
    ["Registered candidates", data.total_candidates], ["Candidates with resumes", data.candidates_with_resumes], ["Active approved jobs", data.active_jobs],
    ["Strong matches (80+)", data.strong_matches], ["Potential matches (65–79)", data.potential_matches], ["Awaiting review", data.awaiting_review],
    ["Approved by admin", data.approved], ["Contacted / shortlisted", `${data.contacted} / ${data.shortlisted}`],
    ["Jobs without suitable candidates", data.jobs_without_suitable], ["Candidates without suitable jobs", data.candidates_without_suitable],
  ];
  return (
    <div className="mb-8 space-y-6" data-testid="sm-control-room">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {tiles.map(([l, v]) => (
          <div key={l} className="rounded-xl bg-brand-mist p-4"><p className="text-2xl font-extrabold text-brand">{v}</p><p className="text-xs font-semibold text-gray-500">{l}</p></div>
        ))}
      </div>
      <p className="text-xs text-gray-500" data-testid="sm-queue">Automatic matching: {q.queued || 0} queued · {q.processing || 0} running · {q.failed || 0} failed
        {data.last_processed_at ? ` · last run ${formatDate(data.last_processed_at)}` : ""}. Newly published jobs and updated candidate profiles are matched automatically in the background.</p>
      <div className="grid gap-6 lg:grid-cols-2">
        <WeightsCard onSaved={refetch} />
        <AutoAlertsCard />
        <Card className="space-y-2" data-testid="sm-lonely-jobs">
          <p className="h-sec">Jobs without suitable candidates</p>
          {!data.jobs_without_suitable_list.length ? <p className="text-sm text-gray-500">Every open job has at least one candidate scoring 65+.</p>
            : data.jobs_without_suitable_list.map((j) => (
              <button key={j.job_id} onClick={() => navigate(`/admin/smartmatch/job/${j.job_id}`)} className="block w-full rounded-lg p-2 text-left text-sm hover:bg-brand-mist">
                <b>{j.title}</b> · {j.company}<span className="block text-xs text-gray-500">{j.last_matched_at ? `Last matched ${formatDate(j.last_matched_at)}` : "Not matched yet"}</span>
              </button>
            ))}
        </Card>
      </div>
    </div>
  );
}

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
      <ControlRoom />
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
                    <p className="mt-1 text-[11px] text-gray-500">{c.profile_status} · {{ enabled: "alerts on", none: "no preference", opted_out: "opted out" }[c.alert_pref]}</p></td>
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
    ["Alerts", c.alert_pref === "enabled" ? `On · ${c.job_alert_frequency || "Instant"}` : c.alert_pref === "opted_out" ? "Opted out" : "No preference selected (in-app only)"],
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
          <Card data-testid="sma-alert-prefs">
            <p className="h-sec mb-3">Job alert preferences & notifications</p>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
              {[["Active candidates", "active_candidates"], ["Job alerts enabled", "enabled"], ["No preference selected", "none"], ["Opted out", "opted_out"],
                ["Eligible for in-app", "eligible_in_app"], ["Notifications sent", "notifications_sent"], ["Notifications delivered", "notifications_delivered"],
                ["Notifications failed", "notifications_failed"], ["Candidate responses", "candidate_responses"]].map(([l, k]) => <Stat key={k} label={l} value={data.alert_prefs[k]} testId={`sma-ap-${k}`} />)}
            </div>
          </Card>
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

const RECIPIENT_FILTERS = [["eligible", "All eligible active candidates"], ["complete", "Completed profiles"], ["incomplete", "Incomplete profiles"],
  ["enabled", "Job alerts enabled"], ["none", "No preference selected"], ["opted_out", "Opted out (view only)"]];

export function AlertManager() {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState("");
  const [rf, setRf] = useState("eligible");
  const [status, setStatus] = useState("All");
  const [view, setView] = useState("candidates");
  const [busy, setBusy] = useState(false);
  const { data: jobs } = useQuery({ queryKey: ["am-jobs"], queryFn: () => api("/admin/alert-manager/jobs") });
  const { data: rec } = useQuery({ queryKey: ["am-recipients", jobId], queryFn: () => api(`/admin/alert-manager/jobs/${jobId}/recipients`), enabled: !!jobId && view === "received" });
  const job = jobs?.jobs.find((j) => j.job_id === jobId);
  const find = async () => {
    setBusy(true);
    try {
      const res = await api(`/admin/smartmatch/jobs/${jobId}/find-candidates`, { method: "POST" });
      notify(`${res.scored} candidates scored`, "success");
      qc.invalidateQueries({ queryKey: ["sm-matches"] });
      qc.invalidateQueries({ queryKey: ["am-jobs"] });
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const filters = clean({ job_id: jobId, status, ...(["complete", "incomplete"].includes(rf) ? { profile: rf, alert_pref: "eligible" } : { alert_pref: rf }) });
  return (
    <>
      <PageHeader title="JobRadar Job Alert Manager" subtitle="Pick a verified, open job, find relevant candidates, approve them and send in-app notifications. Opted-out candidates are never notified." />
      <Card className="mb-5 space-y-4" data-testid="am-job-picker">
        <label className="block"><span className="label">Verified, active job</span>
          <select className="field mt-1.5" value={jobId} onChange={(e) => setJobId(e.target.value)} data-testid="am-job-select">
            <option value="">Select a job…</option>
            {(jobs?.jobs || []).map((j) => <option key={j.job_id} value={j.job_id}>{j.title} — {j.company} ({j.location || j.city || "—"}) · {j.matches} matched · {j.notified} notified</option>)}
          </select>
        </label>
        {jobs && jobs.jobs.length === 0 ? <p className="text-sm text-amber-700">No verified, open, non-expired jobs. Verify and publish a job in Job Management first.</p> : null}
        {job ? (
          <div className="flex flex-wrap items-center gap-3">
            <Button title="Find Matching Candidates" icon={<Search className="h-4 w-4" />} loading={busy} onClick={find} data-testid="am-find" />
            <span className="text-sm text-gray-500">{job.matches} matched · {job.approved} approved · {job.notified} received in-app</span>
          </div>
        ) : null}
      </Card>
      {job ? (
        <>
          <div className="mb-4 flex gap-2">
            <Chip label="Candidates" selected={view === "candidates"} onClick={() => setView("candidates")} data-testid="am-view-candidates" />
            <Chip label="Already received / delivery status" selected={view === "received"} onClick={() => setView("received")} data-testid="am-view-received" />
          </div>
          {view === "candidates" ? (
            <>
              <Card className="mb-5 space-y-4" data-testid="am-filters">
                <Chips label="Recipients" value={rf} options={RECIPIENT_FILTERS.map((x) => x[0])} short={(o) => (o === "All" ? "Everyone" : RECIPIENT_FILTERS.find((x) => x[0] === o)?.[1])} onChange={setRf} testId="am-rf" />
                <Chips label="Review status" value={status} options={Object.keys(MATCH_STATUS_LABEL)} short={(o) => MATCH_STATUS_LABEL[o] || o} onChange={setStatus} testId="am-status" />
              </Card>
              <MatchTable filters={filters} mode="job" title="Suggested candidates" defaultChannels={["in_app"]} readOnly={rf === "opted_out"} />
            </>
          ) : (
            <Card className="overflow-x-auto p-0" data-testid="am-received">
              {!rec ? <Spinner /> : rec.recipients.length === 0 ? <div className="p-6"><EmptyState title="Nobody has been notified about this job yet" /></div> : (
                <table className="w-full text-sm">
                  <thead className="bg-gray-50/70 text-left text-xs uppercase tracking-wider text-gray-400"><tr><th className="px-4 py-3">Candidate</th><th className="px-3">Channel</th><th className="px-3">Status</th><th className="px-3">Sent</th><th className="px-3">Read</th></tr></thead>
                  <tbody className="divide-y divide-gray-100">
                    {rec.recipients.map((n) => (
                      <tr key={n.notification_id} data-testid={`am-rec-${n.notification_id}`}>
                        <td className="px-4 py-3"><p className="font-bold">{n.candidate_name || "—"}</p><p className="text-xs text-gray-500">{n.candidate_email}</p></td>
                        <td className="px-3">{n.channel === "email" ? "Email" : "In-app"}</td>
                        <td className="px-3"><Badge label={n.status === "sent" ? "Delivered" : n.status} color={n.status === "sent" ? "success" : "error"} />{n.error ? <p className="text-[11px] text-red-600">{n.error}</p> : null}</td>
                        <td className="px-3 text-xs">{n.sent_at ? new Date(n.sent_at).toLocaleString("en-IN") : "—"}</td>
                        <td className="px-3 text-xs">{n.channel === "in_app" ? (n.read_at ? "Read" : "Unread") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          )}
        </>
      ) : null}
    </>
  );
}
