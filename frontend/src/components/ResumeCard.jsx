import React, { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FileText, Trash2, Upload } from "lucide-react";
import { api, downloadFile, fetchBlob, uploadForm } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { NOTICE_PERIODS } from "@/lib/constants";
import { Badge, Button, Card, errMsg, Input, notify, Switch } from "@/components/kit";

const STATUS = {
  queued: ["Waiting to be read", "warning"], processing: ["Reading your resume…", "warning"], parsed: ["Ready to review", "info"],
  confirmed: ["Details confirmed", "success"], failed: ["Couldn't read this file", "error"],
};
// [extracted key, label, kind]. Keys are what the parser returns; the backend maps them onto profile fields.
const FIELDS = [
  ["current_designation", "Current designation", "text"], ["current_company", "Current company", "text"],
  ["total_experience", "Total experience (years)", "text"], ["current_location", "Current location", "text"],
  ["phone", "Mobile number", "text"], ["skills", "Skills", "list"], ["tools", "Software & tools", "list"],
  ["certifications", "Certifications", "list"], ["highest_qualification", "Highest qualification", "text"],
  ["institution", "Institution", "text"], ["current_ctc", "Current CTC", "text"], ["expected_ctc", "Expected CTC (e.g. 9 LPA)", "text"],
  ["notice_period", "Notice period", "notice"], ["previous_companies", "Previous companies", "list"],
  ["industry_experience", "Industry experience", "list"],
];
const PROFILE_KEY = { phone: "mobile", skills: "primary_skills", current_ctc: "current_salary" };
const toText = (v) => (Array.isArray(v) ? v.join(", ") : v ?? "");
const fmtDate = (s) => (s ? new Date(s).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");

export function ResumeConsent() {
  const { user, refresh } = useAuth();
  const [busy, setBusy] = useState(false);
  const toggle = async (v) => {
    setBusy(true);
    try {
      await api("/auth/profile", { method: "PUT", body: { talent_db_consent: v } });
      await refresh();
      notify(v ? "You're now visible to JobRadar recruiters" : "You've been removed from the recruiter talent database", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="flex items-start justify-between gap-4 rounded-xl bg-brand-mist p-4 text-sm" data-testid="talent-consent">
      <span><b>Let JobRadar recruiters find my profile</b><br />
        <span className="text-xs text-gray-500">Adds your profile and resume to JobRadar's private recruiter search. Never shown to employers without your permission. You can withdraw at any time.</span></span>
      <Switch checked={user.talent_db_consent === true} onChange={(v) => !busy && toggle(v)} data-testid="talent-consent-switch" />
    </label>
  );
}

function Review({ rec, confirmed, onDone }) {
  const ex = rec.extracted || {};
  const keys = FIELDS.filter(([k]) => ex[k] !== undefined && ex[k] !== null && toText(ex[k]) !== "");
  const isConfirmed = (k) => confirmed.includes(PROFILE_KEY[k] || k);
  const [vals, setVals] = useState(() => Object.fromEntries(keys.map(([k]) => [k, toText(ex[k])])));
  // Fields already confirmed earlier stay unticked, so a new resume never silently replaces them.
  const [use, setUse] = useState(() => Object.fromEntries(keys.map(([k]) => [k, !isConfirmed(k)])));
  const [busy, setBusy] = useState(false);
  if (!keys.length) return <p className="text-sm text-gray-500" data-testid="resume-nothing-found">We couldn't find profile details in this file. You can still fill in your profile below.</p>;
  const save = async () => {
    const fields = {};
    keys.forEach(([k, , kind]) => {
      if (!use[k]) return;
      fields[k] = kind === "list" ? vals[k].split(",").map((x) => x.trim()).filter(Boolean) : vals[k];
    });
    if (ex.employment_history && Object.keys(fields).length) fields.employment_history = ex.employment_history;
    if (!Object.keys(fields).length) return notify("Tick at least one detail to save", "error");
    setBusy(true);
    try {
      await api(`/resume/${rec.resume_id}/confirm`, { method: "POST", body: { fields } });
      notify("Profile updated from your resume", "success");
      onDone();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="space-y-4" data-testid="resume-review">
      <div>
        <p className="text-sm font-bold">Check the details we found</p>
        <p className="text-xs text-gray-500">Edit anything that's wrong and untick anything you don't want saved. Nothing is added to your profile until you confirm.</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {keys.map(([k, label, kind]) => (
          <div key={k} className="flex items-start gap-2">
            <input type="checkbox" className="mt-9 h-4 w-4 accent-[var(--brand,#6D28D9)]" checked={!!use[k]}
              onChange={(e) => setUse((u) => ({ ...u, [k]: e.target.checked }))} data-testid={`resume-use-${k}`} />
            <div className="flex-1">
              {kind === "notice" ? (
                <label className="block"><span className="label">{label}</span>
                  <select className="field mt-1.5" value={vals[k]} onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))}>
                    {NOTICE_PERIODS.map((n) => <option key={n}>{n}</option>)}
                  </select></label>
              ) : (
                <Input label={label} value={vals[k]} onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} data-testid={`resume-field-${k}`} />
              )}
              {isConfirmed(k) ? <p className="mt-1 text-xs text-amber-700">You confirmed this before — tick to replace it.</p> : null}
            </div>
          </div>
        ))}
      </div>
      {ex.employment_history?.length ? (
        <div className="rounded-xl bg-gray-50 p-3 text-xs text-gray-600">
          <p className="mb-1 font-bold text-gray-800">Employment history found</p>
          {ex.employment_history.map((j, i) => <p key={i}>{[j.title, j.company].filter(Boolean).join(" · ")} — {j.start} to {j.end}</p>)}
        </div>
      ) : null}
      <Button title="Confirm & update profile" loading={busy} onClick={save} data-testid="resume-confirm" />
    </div>
  );
}

export function ResumeCard() {
  const { refresh } = useAuth();
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [reviewAgain, setReviewAgain] = useState(false);
  const { data, refetch } = useQuery({ queryKey: ["my-resume"], queryFn: () => api("/resume") });
  const cur = data?.current;
  const pending = cur && ["queued", "processing"].includes(cur.status);
  useEffect(() => {
    if (!pending) return undefined;
    const t = setInterval(refetch, 2000);
    return () => clearInterval(t);
  }, [pending, refetch]);
  if (!data) return null;

  const pick = async (file) => {
    if (!file) return;
    if (!/\.(pdf|docx)$/i.test(file.name)) return notify("Please choose a PDF or Word (.docx) file", "error");
    if (file.size > data.max_mb * 1024 * 1024) return notify(`File must be under ${data.max_mb} MB`, "error");
    setBusy(true);
    try {
      const res = await uploadForm("/resume/upload", file);
      notify(res.duplicate ? "That resume is already uploaded" : "Resume uploaded — reading it now", "success");
      await refetch();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  const view = async (rec) => {
    try {
      const url = URL.createObjectURL(await fetchBlob(`/resume/${rec.resume_id}/file`));
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const remove = async (rec, all) => {
    const msg = all ? "Permanently delete all your uploaded resumes? This can't be undone." : `Permanently delete ${rec.original_filename}? This can't be undone.`;
    if (!window.confirm(msg)) return;
    try {
      await api(all ? "/resume" : `/resume/${rec.resume_id}`, { method: "DELETE" });
      notify("Resume deleted", "success");
      await refetch();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const done = async () => {
    setReviewAgain(false);
    await refetch();
    await refresh();
  };
  const [label, color] = STATUS[cur?.status] || [];
  return (
    <Card className="space-y-5 p-8" data-testid="resume-card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="h-sec">My resume</p>
          <p className="muted">PDF or Word (.docx), up to {data.max_mb} MB. We read it to fill in your profile — you review everything first.</p>
        </div>
        {data.uploads_enabled ? (
          <>
            <input ref={input} type="file" accept=".pdf,.docx" className="hidden" onChange={(e) => pick(e.target.files?.[0])} data-testid="resume-input" />
            <Button title={cur ? "Replace resume" : "Upload resume"} icon={<Upload className="h-4 w-4" />} loading={busy}
              onClick={() => input.current?.click()} data-testid="resume-upload" />
          </>
        ) : null}
      </div>
      {!data.uploads_enabled ? <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800" data-testid="resume-disabled">Resume upload is coming soon.</p> : null}
      {cur ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-3">
              <FileText className="h-8 w-8 text-brand" />
              <div>
                <p className="text-sm font-bold" data-testid="resume-filename">{cur.original_filename}</p>
                <p className="text-xs text-gray-500">Uploaded {fmtDate(cur.uploaded_at)} · version {cur.version}</p>
              </div>
              <Badge label={label} color={color} data-testid="resume-status" />
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" title="View" onClick={() => view(cur)} data-testid="resume-view" />
              <Button size="sm" variant="outline" title="Download" onClick={() => downloadFile(`/resume/${cur.resume_id}/file`, { download: "1" }, cur.original_filename).catch((e) => notify(errMsg(e), "error"))} data-testid="resume-download" />
              <button onClick={() => remove(cur)} className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-600" title="Delete" data-testid="resume-delete"><Trash2 className="h-4 w-4" /></button>
            </div>
          </div>
          {cur.status === "failed" ? <p className="text-sm text-red-700">{cur.error || "We couldn't read this file."} Try exporting it again as PDF, or fill in your profile manually.</p> : null}
          {cur.status === "parsed" || (cur.status === "confirmed" && reviewAgain)
            ? <Review key={cur.resume_id + cur.status} rec={cur} confirmed={data.confirmed_fields} onDone={done} /> : null}
          {cur.status === "confirmed" ? (
            <button className="text-sm font-semibold text-brand" onClick={() => setReviewAgain((v) => !v)} data-testid="resume-review-again">
              {reviewAgain ? "Hide resume details" : "Review details from this resume again"}
            </button>
          ) : null}
        </div>
      ) : data.uploads_enabled ? <p className="text-sm text-gray-500" data-testid="resume-empty">No resume uploaded yet.</p> : null}
      {data.resumes.length > 1 ? (
        <div className="space-y-1" data-testid="resume-history">
          <p className="text-xs font-bold uppercase tracking-wide text-gray-500">Earlier versions</p>
          {data.resumes.filter((r) => !r.is_current).map((r) => (
            <div key={r.resume_id} className="flex items-center justify-between text-sm">
              <span>v{r.version} · {r.original_filename} · {fmtDate(r.uploaded_at)}</span>
              <span className="flex gap-3">
                <button className="font-semibold text-brand" onClick={() => view(r)}>View</button>
                <button className="font-semibold text-gray-500 hover:text-red-600" onClick={() => remove(r)}>Delete</button>
              </span>
            </div>
          ))}
        </div>
      ) : null}
      <ResumeConsent />
      {data.resumes.length ? <button onClick={() => remove(null, true)} className="text-xs font-semibold text-gray-500 underline hover:text-red-600" data-testid="resume-delete-all">Delete all my resumes</button> : null}
    </Card>
  );
}
