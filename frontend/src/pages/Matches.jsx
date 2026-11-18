import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Bookmark, Briefcase, Building2, Calendar, ExternalLink, MapPin, Mail, ThumbsDown } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatDate, scoreColor } from "@/lib/constants";
import { Badge, Button, Card, Chip, EmptyState, errMsg, notify, PageHeader, Spinner } from "@/components/kit";
import { Page } from "@/components/Layout";
import { ALERT_NOTICE, ProfileCompletion } from "@/components/SmartProfile";

const expText = (j) => (j.experience_min != null && j.experience_max != null ? `${j.experience_min}–${j.experience_max} yrs` : j.experience_required || "Experience not specified");

function MatchCard({ j, refresh }) {
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
      {m.missing_mandatory_skills.length ? (
        <p className="flex items-start gap-1.5 rounded-lg bg-red-50 p-2 text-xs text-red-700" data-testid={`match-gaps-${j.job_id}`}><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />Mandatory skill gaps: {m.missing_mandatory_skills.join(", ")}</p>
      ) : null}
      {m.provisional ? <p className="text-[11px] text-amber-700">Provisional match — not enough information about: {m.missing_data.join(", ")}</p> : null}
      {j.tracked_status ? <Badge label={`In your tracker: ${j.tracked_status.replace("_", " ")}`} color="brand" /> : null}
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

const TABS = [["shared", "Shared by JobRadar"], ["recommended", "Recommended Jobs"], ["strong", "Strong Matches"], ["recent", "Recently Added"],
  ["saved", "Saved Jobs"], ["viewed", "Previously Viewed"]];

export default function Matches() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState("recommended");
  const { data, isLoading, refetch } = useQuery({ queryKey: ["my-matches", user?.user_id], queryFn: () => api("/smartmatch/me"), enabled: user?.role === "candidate" });
  const refresh = () => { refetch(); qc.invalidateQueries({ queryKey: ["tracker"] }); };
  const list = data?.[tab] || [];
  const markRead = (n) => !n.read_at && api(`/smartmatch/notifications/${n.notification_id}/read`, { method: "POST" }).then(refetch).catch(() => {});
  return (
    <Page>
      <PageHeader title="My Job Matches" subtitle="Jobs ranked by how well they fit your profile. JobRadar never applies on your behalf — contact the recruiter or use the company's own application link." />
      {!data && isLoading ? <Spinner /> : !data ? null : (
        <>
          <div className="mb-6 grid gap-4 lg:grid-cols-[1fr_360px]">
            <div className="flex flex-wrap content-start gap-2" data-testid="matches-tabs">
              {TABS.map(([k, l]) => (
                <Chip key={k} label={`${l} (${(data[k] || []).length})${k === "shared" && data.unread ? ` · ${data.unread} new` : ""}`} selected={tab === k} onClick={() => setTab(k)} data-testid={`matches-tab-${k}`} />
              ))}
              <p className="w-full text-xs text-gray-500" data-testid="matches-alert-notice">
                {data.alerts.pref === "opted_out" ? "You turned off job alerts, so JobRadar won't send you opportunities. Your matches below are still based on your profile. " : `${ALERT_NOTICE} `}
                <button className="font-bold text-brand underline" onClick={() => navigate("/profile")} data-testid="matches-alert-settings">Notification preferences</button>
              </p>
            </div>
            <ProfileCompletion compact />
          </div>
          {list.length === 0 ? (
            <EmptyState title="Nothing here yet" subtitle={tab === "shared" ? "When JobRadar approves an opportunity for you, it will appear here." : "Complete your profile to improve your matches."} data-testid="matches-empty" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2" data-testid={`matches-list-${tab}`}>
              {list.map((j) => (
                <div key={j.job_id} onMouseEnter={() => j.notification && markRead(j.notification)}>
                  {j.notification ? (
                    <p className="mb-1.5 text-xs font-semibold text-brand">{j.notification.read_at ? "" : "New · "}Shared by JobRadar on {formatDate(j.notification.sent_at)}</p>
                  ) : null}
                  <MatchCard j={j} refresh={refresh} />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Page>
  );
}
