import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Building2, CheckCircle2, Mail, MapPin, Paperclip, Upload, User, X } from "lucide-react";
import { api, uploadForm } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatDate } from "@/lib/constants";
import { Badge, Button, Card, Chip, ChipRow, EmptyState, errMsg, Input, Modal, notify, PageHeader, Switch } from "@/components/kit";
import { Page } from "@/components/Layout";

export const TRACK_STATUSES = [
  ["interested", "Interested", "I am interested in this opportunity."],
  ["contacted", "Contacted Recruiter", "I contacted the recruiter/company."],
  ["applied", "Applied", "I independently submitted my application outside JobRadar."],
  ["responded", "Recruiter Responded", "The recruiter/company contacted me."],
  ["interview_scheduled", "Interview Scheduled", "I received an interview invitation."],
  ["interview_completed", "Interview Completed", "I attended the interview."],
  ["offer_received", "Offer Received", "I received a job offer."],
  ["hired", "Hired", "I was selected and joined the company."],
  ["not_selected", "Not Selected", "My application was rejected."],
  ["no_response", "No Response", "I have not received any response."],
];
const EVIDENCE = [["interview_invite", "Interview invitation"], ["interview_confirmation", "Interview confirmation"],
  ["offer_letter", "Offer letter"], ["joining_confirmation", "Joining confirmation"]];
const statusColor = (s) => (s === "hired" || s === "offer_received" ? "success" : s === "not_selected" ? "error" : s === "no_response" ? "warning" : "brand");

function StatusDialog({ item, onClose, onSaved }) {
  const [status, setStatus] = useState(item.status);
  const [f, setF] = useState({
    interview_company: item.interview?.company || item.company || "", interview_date: item.interview?.date || "",
    interview_mode: item.interview?.mode || "", interview_comments: item.interview?.comments || "",
    hire_company: item.hire?.company || item.company || "", hire_designation: item.hire?.designation || item.designation || "",
    joining_date: item.hire?.joining_date || "", hire_feedback: item.hire?.feedback || "",
  });
  const [busy, setBusy] = useState(false);
  const bind = (k) => ({ value: f[k], onChange: (e) => setF((x) => ({ ...x, [k]: e.target.value })) });
  const save = async () => {
    if (status === "interview_scheduled" && (!f.interview_date || !f.interview_mode)) return notify("Add the interview date and mode", "error");
    if (status === "hired" && (!f.hire_company.trim() || !f.hire_designation.trim() || !f.joining_date)) return notify("Add company, designation and joining date", "error");
    setBusy(true);
    try {
      await api(`/tracker/${item.tracker_id}/status`, { method: "PUT", body: { status, ...f } });
      notify("Progress updated", "success");
      onSaved();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose} wide>
      <p className="text-xl font-extrabold">Update progress</p>
      <p className="muted">{item.designation} · {item.company}</p>
      <div className="mt-5 grid gap-2 sm:grid-cols-2">
        {TRACK_STATUSES.map(([k, label, desc]) => (
          <button key={k} onClick={() => setStatus(k)} data-testid={`tracker-status-${k}`}
            className={`rounded-xl border-2 p-3 text-left transition-colors ${status === k ? "border-brand bg-brand-mist" : "border-gray-200 hover:border-brand/50"}`}>
            <p className="text-sm font-bold">{label}</p>
            <p className="text-xs text-gray-500">{desc}</p>
          </button>
        ))}
      </div>
      {status === "interview_scheduled" ? (
        <div className="mt-5 grid gap-4 rounded-xl bg-brand-mist p-4 sm:grid-cols-2" data-testid="tracker-interview-form">
          <Input label="Company name" {...bind("interview_company")} data-testid="tracker-iv-company" />
          <Input label="Interview date *" type="date" {...bind("interview_date")} data-testid="tracker-iv-date" />
          <div className="sm:col-span-2">
            <ChipRow label="Interview mode *">
              {["Phone", "Video", "Face-to-Face"].map((m) => (
                <Chip key={m} label={m} selected={f.interview_mode === m} onClick={() => setF((x) => ({ ...x, interview_mode: m }))} data-testid={`tracker-iv-mode-${m}`} />
              ))}
            </ChipRow>
          </div>
          <Input className="sm:col-span-2" multiline rows={2} label="Comments (optional)" {...bind("interview_comments")} data-testid="tracker-iv-comments" />
        </div>
      ) : null}
      {status === "hired" ? (
        <div className="mt-5 grid gap-4 rounded-xl bg-emerald-50 p-4 sm:grid-cols-2" data-testid="tracker-hire-form">
          <Input label="Company name *" {...bind("hire_company")} data-testid="tracker-hire-company" />
          <Input label="Designation *" {...bind("hire_designation")} data-testid="tracker-hire-designation" />
          <Input label="Joining date *" type="date" {...bind("joining_date")} data-testid="tracker-hire-date" />
          <Input multiline rows={2} label="Feedback (optional)" {...bind("hire_feedback")} data-testid="tracker-hire-feedback" />
        </div>
      ) : null}
      <div className="mt-6 flex justify-end gap-2">
        <Button variant="ghost" title="Cancel" onClick={onClose} data-testid="tracker-status-cancel" />
        <Button title="Save Progress" loading={busy} onClick={save} data-testid="tracker-status-save" />
      </div>
    </Modal>
  );
}

function EvidenceDialog({ item, onClose, onSaved }) {
  const [kind, setKind] = useState("interview_invite");
  const [redacted, setRedacted] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);
  const onFile = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) return notify("Please choose a file under 5 MB", "error");
    setBusy(true);
    try {
      await uploadForm(`/tracker/${item.tracker_id}/evidence`, file, "file", { kind, redacted: "true" });
      notify("Evidence shared privately with the JobRadar team", "success");
      onSaved();
    } catch (err) {
      notify(errMsg(err), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose}>
      <p className="text-xl font-extrabold">Share supporting evidence (optional)</p>
      <p className="muted mt-1">This helps us verify your result. It is never shown to other candidates — only authorised JobRadar admins can view it.</p>
      <div className="mt-5 space-y-4">
        <ChipRow label="What are you sharing?">
          {EVIDENCE.map(([k, l]) => <Chip key={k} label={l} selected={kind === k} onClick={() => setKind(k)} data-testid={`evidence-kind-${k}`} />)}
        </ChipRow>
        <p className="rounded-xl bg-amber-50 p-3 text-xs text-amber-800">
          Please hide (black out or crop) your salary, phone number, address and any other private details before uploading. A screenshot of the email subject and company name is enough.
        </p>
        <label className="flex items-start gap-3 text-sm">
          <input type="checkbox" checked={redacted} onChange={(e) => setRedacted(e.target.checked)} className="mt-1 h-4 w-4 accent-[#7C3AED]" data-testid="evidence-redacted" />
          I have hidden my salary and private contact details.
        </label>
        <input ref={ref} type="file" accept="application/pdf,image/png,image/jpeg,image/webp" className="hidden" onChange={onFile} data-testid="evidence-file-input" />
        <Button full title="Choose PDF or image (max 5 MB)" icon={<Upload className="h-4 w-4" />} loading={busy} disabled={!redacted}
          onClick={() => ref.current?.click()} data-testid="evidence-upload" />
      </div>
    </Modal>
  );
}

function TrackerCard({ item, refresh }) {
  const navigate = useNavigate();
  const [dialog, setDialog] = useState(null);
  const done = () => { setDialog(null); refresh(); };
  const dismiss = async () => {
    await api(`/tracker/${item.tracker_id}/dismiss-reminder`, { method: "POST" }).catch(() => {});
    refresh();
  };
  const untrack = async () => {
    if (!window.confirm("Stop tracking this job?")) return;
    await api(`/tracker/${item.tracker_id}`, { method: "DELETE" }).catch(() => {});
    refresh();
  };
  const verified = (v) => (v === "verified" ? <Badge label="Verified" color="success" /> : v ? <Badge label="Candidate reported" color="info" /> : null);
  return (
    <Card className="space-y-4" data-testid={`tracker-item-${item.job_id}`}>
      {item.reminder ? (
        <div className="flex items-center gap-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-800" data-testid={`tracker-reminder-${item.job_id}`}>
          <BellRing className="h-4 w-4 shrink-0" />
          <span className="flex-1 font-semibold">{item.reminder.text}</span>
          <button onClick={() => setDialog("status")} className="font-bold underline" data-testid={`tracker-reminder-update-${item.job_id}`}>Update</button>
          <button onClick={dismiss} data-testid={`tracker-reminder-dismiss-${item.job_id}`}><X className="h-4 w-4" /></button>
        </div>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <button onClick={() => navigate(`/job/${item.job_id}`)} className="text-left">
          <p className="text-lg font-extrabold text-gray-900 hover:text-brand">{item.designation}</p>
          <p className="mt-1 flex flex-wrap items-center gap-3 text-sm text-gray-500">
            <span className="flex items-center gap-1"><Building2 className="h-3.5 w-3.5" />{item.company}</span>
            {item.location ? <span className="flex items-center gap-1"><MapPin className="h-3.5 w-3.5" />{item.location}</span> : null}
            <span>Saved {formatDate(item.created_at)}</span>
          </p>
        </button>
        <Badge label={item.status_label} color={statusColor(item.status)} data-testid={`tracker-status-badge-${item.job_id}`} />
      </div>
      {item.recruiter_name || item.recruiter_email ? (
        <p className="flex flex-wrap gap-4 text-sm text-gray-600">
          {item.recruiter_name ? <span className="flex items-center gap-1"><User className="h-3.5 w-3.5 text-brand" />{item.recruiter_name}</span> : null}
          {item.recruiter_email ? <span className="flex items-center gap-1"><Mail className="h-3.5 w-3.5 text-brand" />{item.recruiter_email}</span> : null}
        </p>
      ) : null}
      {item.interview ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-gray-600">Interview: {item.interview.company} · {formatDate(item.interview.date)} · {item.interview.mode} {verified(item.interview_verification)}</p>
      ) : null}
      {item.hire ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-gray-600">Hired: {item.hire.designation} at {item.hire.company} · joining {formatDate(item.hire.joining_date)} {verified(item.hire_verification)}</p>
      ) : null}
      <div className="flex flex-wrap gap-1.5">
        {(item.status_history || []).map((h, i) => (
          <span key={i} className="rounded-full bg-gray-100 px-2.5 py-1 text-[11px] text-gray-600">
            {TRACK_STATUSES.find((s) => s[0] === h.status)?.[1]} · {new Date(h.at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
          </span>
        ))}
      </div>
      {item.evidence?.length ? (
        <p className="flex items-center gap-2 text-xs text-gray-500"><Paperclip className="h-3.5 w-3.5" />{item.evidence.length} file(s) shared privately for verification</p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" title="Update Progress" onClick={() => setDialog("status")} data-testid={`tracker-update-${item.job_id}`} />
        {item.interview || item.hire || ["offer_received", "interview_completed"].includes(item.status) ? (
          <Button size="sm" variant="outline" title="Share Evidence (optional)" onClick={() => setDialog("evidence")} data-testid={`tracker-evidence-${item.job_id}`} />
        ) : null}
        <Button size="sm" variant="ghost" title="Stop Tracking" onClick={untrack} data-testid={`tracker-remove-${item.job_id}`} />
      </div>
      {dialog === "status" ? <StatusDialog item={item} onClose={() => setDialog(null)} onSaved={done} /> : null}
      {dialog === "evidence" ? <EvidenceDialog item={item} onClose={() => setDialog(null)} onSaved={done} /> : null}
    </Card>
  );
}

export default function Tracker() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const qc = useQueryClient();
  const { data, refetch } = useQuery({ queryKey: ["tracker", user?.user_id], queryFn: () => api("/tracker"), enabled: !!user });
  const items = data?.items || [];
  const refresh = () => { refetch(); qc.invalidateQueries({ queryKey: ["tracker-job"] }); };
  const toggleEmail = async (v) => {
    await api("/tracker/settings", { method: "PUT", body: { email_reminders: v } }).catch(() => {});
    refetch();
  };
  return (
    <Page>
      <PageHeader title="My Job Search Tracker"
        subtitle="Keep track of jobs you found on JobRadar and update your progress as you contact recruiters and apply directly. Tracking a job is not an application."
        right={
          <label className="flex items-center gap-3 text-sm font-semibold text-gray-600">
            Email reminders
            <Switch checked={data?.email_reminders !== false} onChange={toggleEmail} data-testid="tracker-email-toggle" />
          </label>
        } />
      {items.length === 0 ? (
        <>
          <EmptyState title="No tracked jobs yet" subtitle="Open any job and click “I'm Interested in This Job – Track It”." data-testid="tracker-empty" />
          <div className="flex justify-center"><Button title="Explore Jobs" onClick={() => navigate("/explore")} data-testid="tracker-explore" /></div>
        </>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2" data-testid="tracker-list">
          {items.map((it) => <TrackerCard key={it.tracker_id} item={it} refresh={refresh} />)}
        </div>
      )}
      <p className="mt-8 flex items-center gap-2 text-xs text-gray-400">
        <CheckCircle2 className="h-4 w-4" /> Your progress is private. JobRadar uses it only in anonymous totals to measure how helpful our listings are.
      </p>
    </Page>
  );
}

export function TrackButton({ jobId }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const { data } = useQuery({ queryKey: ["tracker-job", jobId, user?.user_id], queryFn: () => api(`/tracker/job/${jobId}`), enabled: user?.role === "candidate" });
  if (user && user.role !== "candidate") return null;
  const tracked = data?.item;
  if (tracked) {
    return (
      <Button full variant="secondary" title={`Tracking · ${tracked.status_label}`} icon={<CheckCircle2 className="h-4 w-4" />}
        onClick={() => navigate("/tracker")} data-testid="job-tracked-btn" />
    );
  }
  const track = async () => {
    if (!user) return navigate("/auth/login");
    setBusy(true);
    try {
      await api("/tracker", { method: "POST", body: { job_id: jobId } });
      notify("Added to My Job Search Tracker", "success");
      qc.invalidateQueries({ queryKey: ["tracker-job"] });
      qc.invalidateQueries({ queryKey: ["tracker"] });
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return <Button full variant="outline" title="I'm Interested in This Job – Track It" loading={busy} onClick={track} data-testid="job-track-btn" />;
}
