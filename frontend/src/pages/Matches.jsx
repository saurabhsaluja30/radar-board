import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bookmark, Briefcase, Building2, Calendar, ExternalLink, MapPin, Mail, Search, ThumbsDown } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatDate, scoreColor } from "@/lib/constants";
import { Badge, Button, Card, Chip, EmptyState, errMsg, notify, PageHeader, Spinner } from "@/components/kit";
import { Page } from "@/components/Layout";
import { ALERT_NOTICE, ProfileCompletion } from "@/components/SmartProfile";
import { areaCls } from "@/components/career";
import { TRACK_STATUSES } from "@/pages/Tracker";

const STAGE_LABEL = Object.fromEntries(TRACK_STATUSES.map(([k, l]) => [k, l]));
const VERDICT_COLOR = { Suitable: "success", "Partially Suitable": "warning", "Not Currently Suitable": "error" };

// Candidate's own JD check. Uses the same SmartMatch rules as their job matches, against their confirmed profile.
function JdCheck() {
  const navigate = useNavigate();
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState(null);
  const { data: saved } = useQuery({ queryKey: ["saved-jobs"], queryFn: () => api("/saved-jobs") });
  const run = async (body) => {
    setBusy(true);
    try {
      setRes(await api("/smartmatch/jd-check", { method: "POST", body }));
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const list = (label, items, cls) => (items?.length ? <p className={`text-sm ${cls}`}><b>{label}:</b> {items.join(", ")}</p> : null);
  return (
    <div className="grid gap-6 lg:grid-cols-2" data-testid="jd-check">
      <Card className="space-y-3">
        <p className="font-extrabold">Check how well a job fits your profile</p>
        <p className="text-sm text-gray-500">Paste any job description, or pick a saved job. JobRadar compares it with your confirmed profile using the same rules as your matches. It's free and doesn't use your AI tool limits.</p>
        {saved?.jobs?.length ? (
          <select className="field" defaultValue="" onChange={(e) => e.target.value && run({ job_id: e.target.value })} data-testid="jd-check-job">
            <option value="">Check one of my saved jobs…</option>
            {saved.jobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.title} · {j.company}</option>)}
          </select>
        ) : null}
        <textarea value={jd} onChange={(e) => setJd(e.target.value)} maxLength={12000} className={`${areaCls} min-h-[220px]`} placeholder="Paste the complete job description" data-testid="jd-check-text" />
        <Button title="Check My Fit" loading={busy} onClick={() => run({ jd_text: jd })} data-testid="jd-check-run" />
      </Card>
      {res ? (
        <Card className="space-y-4" data-testid="jd-check-result">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Badge label={res.verdict} color={VERDICT_COLOR[res.verdict]} />
              <p className="mt-2 text-sm text-gray-600">{res.summary}</p>
            </div>
            <div className="text-right"><p className="text-3xl font-extrabold text-brand" data-testid="jd-check-score">{res.score}</p><p className="text-xs text-gray-500">out of 100</p></div>
          </div>
          <p className="text-xs text-gray-500">Based on {res.assessed_factors} of {res.total_factors} factors. {res.not_assessed?.length ? `Not assessed: ${res.not_assessed.join(", ")}.` : ""}</p>
          {list("Matched skills", res.matched_skills, "text-emerald-700")}
          {res.missing_mandatory_skills?.length ? (
            <p className="flex items-start gap-1.5 rounded-lg bg-red-50 p-2 text-sm text-red-700"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />Missing required skills: {res.missing_mandatory_skills.join(", ")}</p>
          ) : null}
          {list("Nice-to-have skills you don't show", res.missing_preferred_skills, "text-amber-700")}
          {list("Experience", res.experience_gaps, "text-gray-700")}
          <div><p className="text-sm font-bold">What to do next</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-gray-700">{res.recommendations.map((r) => <li key={r}>{r}</li>)}</ul></div>
          {res.profile?.missing?.length ? <Button size="sm" variant="outline" title="Complete my profile" onClick={() => navigate("/profile")} data-testid="jd-check-profile" /> : null}
          <p className="text-[11px] text-gray-400">{res.disclaimer} Only skills JobRadar recognises are compared, so read the job description yourself too.</p>
        </Card>
      ) : null}
    </div>
  );
}

const expText = (j) => (j.experience_min != null && j.experience_max != null ? `${j.experience_min}–${j.experience_max} yrs` : j.experience_required || "Experience not specified");

export function MatchCard({ j, refresh }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(null);
  const m = j.match;
  const run = async (key, fn, ok) => {
    setBusy(key);
    try {
      await fn();
      if (ok) notify(ok, "success");
      refresh();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(null);
    }
  };
  const save = () => run("save", () => api(`/jobs/${j.job_id}/save`, { method: j.is_saved ? "DELETE" : "POST" }), j.is_saved ? "Removed from saved" : "Job saved");
  const interested = () => run("int", () => api("/tracker", { method: "POST", body: { job_id: j.job_id } }), "Marked as interested — added to your tracker");
  const notInt = () => run("not", () => api("/smartmatch/respond", { method: "POST", body: { job_id: j.job_id, response: "not_interested" } }), "We'll show this job less");
  const applied = () => run("app", async () => {
    const t = await api("/tracker", { method: "POST", body: { job_id: j.job_id } });
    await api(`/tracker/${t.item.tracker_id}/status`, { method: "PUT", body: { status: "applied" } });
  }, "Recorded: you applied independently");
  return (
    <Card className="flex flex-col gap-3" data-testid={`match-card-${j.job_id}`}>
      <div className="flex items-start justify-between gap-3">
        <button onClick={() => navigate(`/job/${j.job_id}`)} className="text-left">
          <p className="text-lg font-extrabold hover:text-brand">{j.title}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-500">
            <span className="flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{j.company}</span>
            <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{j.location || j.city || j.country}</span>
            <span>{j.work_mode}</span>
            {j.industry_category ? <span>{j.industry_category}</span> : null}
          </p>
        </button>
        <div className="shrink-0 text-right">
          <p className="text-2xl font-extrabold text-brand" data-testid={`match-score-${j.job_id}`}>{m.match_score}%</p>
          <Badge label={m.category} color={scoreColor(m.match_score)} />
        </div>
      </div>
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
        <span className="flex items-center gap-1"><Briefcase className="h-3.5 w-3.5" />{expText(j)}</span>
        <span>{j.locked ? "Salary visible to members" : j.salary_range || "Salary not disclosed"}</span>
        <span className="flex items-center gap-1"><Calendar className="h-3.5 w-3.5" />Posted {formatDate(j.date_published || j.date_added)}</span>
      </p>
      {m.explanation.length ? (
        <div className="text-sm text-gray-600"><b className="text-gray-800">Why this job matches your profile:</b> {m.explanation.slice(0, 4).join(" · ")}</div>
      ) : null}
      {m.matched_skills?.length ? (
        <p className="text-xs text-emerald-700" data-testid={`match-skills-${j.job_id}`}><b>Your matching skills:</b> {m.matched_skills.join(", ")}</p>
      ) : null}
      {m.missing_mandatory_skills.length ? (
        <p className="flex items-start gap-1.5 rounded-lg bg-red-50 p-2 text-xs text-red-700" data-testid={`match-gaps-${j.job_id}`}><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />Mandatory skill gaps: {m.missing_mandatory_skills.join(", ")}</p>
      ) : null}
      {m.provisional ? <p className="text-[11px] text-amber-700">Provisional match — not enough information about: {m.missing_data.join(", ")}</p> : null}
      {j.tracked_status ? <Badge label={`In your tracker: ${STAGE_LABEL[j.tracked_status] || j.tracked_status}`} color="brand" /> : null}
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Button size="sm" title="View Details" onClick={() => navigate(`/job/${j.job_id}`)} data-testid={`mc-view-${j.job_id}`} />
        <Button size="sm" variant="outline" title={j.is_saved ? "Saved" : "Save Job"} icon={<Bookmark className="h-3.5 w-3.5" />} loading={busy === "save"} onClick={save} data-testid={`mc-save-${j.job_id}`} />
        {!j.tracked_status ? <Button size="sm" variant="secondary" title="Mark as Interested" loading={busy === "int"} onClick={interested} data-testid={`mc-interested-${j.job_id}`} /> : null}
        {j.tracked_status !== "applied" ? <Button size="sm" variant="ghost" title="I applied independently" loading={busy === "app"} onClick={applied} data-testid={`mc-applied-${j.job_id}`} /> : null}
        <Button size="sm" variant="ghost" title="Contact Recruiter" icon={<Mail className="h-3.5 w-3.5" />} onClick={() => (j.recruiter_email ? (window.location.href = `mailto:${j.recruiter_email}`) : navigate(`/job/${j.job_id}`))} data-testid={`mc-contact-${j.job_id}`} />
        {j.application_link ? <Button size="sm" variant="ghost" title="Apply on Company Website" icon={<ExternalLink className="h-3.5 w-3.5" />} onClick={() => window.open(j.application_link, "_blank", "noopener")} data-testid={`mc-apply-${j.job_id}`} /> : null}
        {!j.tracked_status ? <button onClick={notInt} title="Not interested" className="ml-auto text-gray-400 hover:text-red-600" data-testid={`mc-not-${j.job_id}`}><ThumbsDown className="h-4 w-4" /></button> : null}
      </div>
    </Card>
  );
}

// "Find jobs for me": one live search a day, run in the background. The server allows only one search at a time
// per candidate, so repeated clicks just return the current status.
function FindJobs({ search, onChange, onShow }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  if (!search || !search.enabled) return null;
  const running = search.status === "running";
  const done = search.status === "done";
  const start = async () => {
    setBusy(true);
    try {
      const res = await api("/me/job-search", { method: "POST" });
      if (res.mode === "database") notify(`You already have ${res.matches} good matches below — no new search needed today.`, "success");
      else if (res.status === "done") notify("New jobs added to 'Found for you'.", "success");
      else notify("Searching for jobs for you. We'll notify you when they're ready.", "success");
      onChange();
    } catch (e) {
      notify(errMsg(e), "error");
      if (String(errMsg(e)).includes("CV")) navigate("/profile");
    } finally {
      setBusy(false);
    }
  };
  const reset = new Date(search.next_reset_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return (
    <Card className="mb-6 flex flex-wrap items-center justify-between gap-4" data-testid="find-jobs">
      <div>
        <p className="font-extrabold">Find new jobs for me</p>
        <p className="text-sm text-gray-500">
          {running ? `Searching${search.searching_for ? ` for ${search.searching_for.title} in ${search.searching_for.city}` : ""}… this usually takes a minute.`
            : done ? `Today's search found ${search.delivered_today} job${search.delivered_today === 1 ? "" : "s"} for you. Next search after ${reset}.`
            : `We search for jobs matching your profile — up to ${search.limit} new jobs a day${search.is_member ? "" : " (members get more)"}. Resets at ${reset}.`}
        </p>
      </div>
      <div className="flex gap-2">
        {search.jobs.length ? <Button variant="outline" title={`Found for you (${search.jobs.length})`} onClick={onShow} data-testid="find-jobs-show" /> : null}
        <Button title={running ? "Searching…" : done ? "Done for today" : "Find jobs for me"} icon={<Search className="h-4 w-4" />}
          loading={busy} disabled={running || done || busy} onClick={start} data-testid="find-jobs-btn" />
      </div>
    </Card>
  );
}

function FoundCard({ j }) {
  const navigate = useNavigate();
  return (
    <Card className="flex flex-col gap-2" data-testid={`found-card-${j.job_id}`}>
      <button onClick={() => navigate(`/job/${j.job_id}`)} className="text-left">
        <p className="text-lg font-extrabold hover:text-brand">{j.title}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-gray-500">
          <span className="flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{j.company}</span>
          <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{j.location || j.city || j.country}</span>
          {j.work_mode ? <span>{j.work_mode}</span> : null}
        </p>
      </button>
      <p className="text-sm text-gray-600">{j.preview}</p>
      <p className="text-xs text-gray-400">Found for you on {formatDate(j.found_at)}</p>
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Button size="sm" title="View Details" onClick={() => navigate(`/job/${j.job_id}`)} />
        {j.application_link ? <Button size="sm" variant="ghost" title="Apply" icon={<ExternalLink className="h-3.5 w-3.5" />} onClick={() => window.open(j.application_link, "_blank", "noopener")} /> : null}
      </div>
    </Card>
  );
}

const TABS = [["found", "Found for you"], ["shared", "Job Alerts"], ["recommended", "Recommended Jobs"], ["strong", "Strong Matches"], ["recent", "Recently Added"],
  ["saved", "Saved Jobs"], ["viewed", "Previously Viewed"], ["check", "Check a Job Description"]];

export default function Matches() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState("recommended");
  const { data, isLoading, refetch } = useQuery({ queryKey: ["my-matches", user?.user_id], queryFn: () => api("/smartmatch/me"), enabled: user?.role === "candidate" });
  const searchQ = useQuery({ queryKey: ["my-job-search", user?.user_id], queryFn: () => api("/me/job-search"), enabled: user?.role === "candidate",
    refetchInterval: (q) => (q.state.data?.status === "running" ? 10000 : false) });
  const search = searchQ.data;
  const wasRunning = React.useRef(false);
  useEffect(() => {  // a background search just finished: refresh alerts and show what it found
    if (wasRunning.current && search && search.status !== "running") { refetch(); if (search.jobs.length) setTab("found"); }
    wasRunning.current = search?.status === "running";
  }, [search, refetch]);
  const refresh = () => { refetch(); qc.invalidateQueries({ queryKey: ["tracker"] }); };
  const list = tab === "found" ? search?.jobs || [] : data?.[tab] || [];
  const markRead = (n) => !n.read_at && api(`/smartmatch/notifications/${n.notification_id}/read`, { method: "POST" }).then(refetch).catch(() => {});
  return (
    <Page>
      <PageHeader title="My Job Matches" subtitle="Jobs ranked by how well they fit your profile. JobRadar never applies on your behalf — contact the recruiter or use the company's own application link." />
      {!data && isLoading ? <Spinner /> : !data ? null : (
        <>
          <FindJobs search={search} onChange={() => searchQ.refetch()} onShow={() => setTab("found")} />
          <div className="mb-6 grid gap-4 lg:grid-cols-[1fr_360px]">
            <div className="flex flex-wrap content-start gap-2" data-testid="matches-tabs">
              {TABS.filter(([k]) => k !== "found" || search?.enabled || search?.jobs?.length).map(([k, l]) => (
                <Chip key={k} label={k === "check" ? l : `${l} (${(k === "found" ? search?.jobs : data[k] || []).length})${k === "shared" && data.unread ? ` · ${data.unread} new` : ""}`} selected={tab === k} onClick={() => setTab(k)} data-testid={`matches-tab-${k}`} />
              ))}
              <p className="w-full text-xs text-gray-500" data-testid="matches-alert-notice">
                {data.alerts.pref === "opted_out" ? "You turned off job alerts, so JobRadar won't send you opportunities. Your matches below are still based on your profile. " : `${ALERT_NOTICE} `}
                <button className="font-bold text-brand underline" onClick={() => navigate("/profile")} data-testid="matches-alert-settings">Notification preferences</button>
              </p>
            </div>
            <ProfileCompletion compact />
          </div>
          {tab === "check" ? <JdCheck /> : list.length === 0 ? (
            <EmptyState title="Nothing here yet" subtitle={tab === "found" ? "Use 'Find jobs for me' above and the jobs we find appear here." : tab === "shared" ? "When a new job strongly matches your profile, JobRadar alerts you here." : "Complete your profile to improve your matches."} data-testid="matches-empty" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2" data-testid={`matches-list-${tab}`}>
              {list.map((j) => (
                <div key={j.job_id} onMouseEnter={() => j.notification && markRead(j.notification)}>
                  {j.notification ? (
                    <p className="mb-1.5 text-xs font-semibold text-brand">{j.notification.read_at ? "" : "New · "}Job alert from JobRadar on {formatDate(j.notification.sent_at)}</p>
                  ) : null}
                  {tab === "found" ? <FoundCard j={j} /> : <MatchCard j={j} refresh={refresh} />}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Page>
  );
}
