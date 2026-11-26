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
  ["preferred_titles", "Preferred job titles", "list"], ["preferred_locations", "Preferred cities", "list"],
  ["languages", "Languages", "list"], ["links", "Links (LinkedIn, GitHub, portfolio)", "list"],
];
// Shown even when the CV doesn't mention them: they drive the personalised daily job search.
const ALWAYS = ["preferred_titles", "preferred_locations", "languages", "links"];
const PASTE_MIN = 200;
const PASTE_MAX = 50000;
const blankEdu = () => ({ degree: "", institution: "", year: "" });
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
  const has = (k) => ex[k] !== undefined && ex[k] !== null && toText(ex[k]) !== "";
  const keys = FIELDS.filter(([k]) => has(k) || ALWAYS.includes(k));
  const found = FIELDS.some(([k]) => has(k)) || ex.education?.length;
  const isConfirmed = (k) => confirmed.includes(PROFILE_KEY[k] || k);
  const [vals, setVals] = useState(() => Object.fromEntries(keys.map(([k]) => [k, toText(ex[k])])));
  // Fields already confirmed earlier stay unticked, so a new resume never silently replaces them.
  const [use, setUse] = useState(() => Object.fromEntries(keys.map(([k]) => [k, has(k) && !isConfirmed(k)])));
  const [edu, setEdu] = useState(() => (ex.education?.length ? ex.education.map((e) => ({ ...blankEdu(), ...Object.fromEntries(Object.entries(e).map(([a, b]) => [a, b ?? ""])) })) : []));
  const [useEdu, setUseEdu] = useState(() => !!ex.education?.length && !isConfirmed("education"));
  const [busy, setBusy] = useState(false);
  const setVal = (k, v) => {
    setVals((x) => ({ ...x, [k]: v }));
    if (ALWAYS.includes(k)) setUse((u) => ({ ...u, [k]: v.trim() !== "" }));
  };
  const setEduRow = (i, k, v) => {
    setEdu((rows) => rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
    setUseEdu(true);
  };
  const save = async () => {
    const fields = {};
    keys.forEach(([k, , kind]) => {
      if (!use[k]) return;
      fields[k] = kind === "list" ? vals[k].split(",").map((x) => x.trim()).filter(Boolean) : vals[k];
    });
    const eduRows = edu.map((r) => ({ degree: r.degree.trim(), institution: r.institution.trim(), year: String(r.year).trim() })).filter((r) => r.degree || r.institution);
    if (useEdu && eduRows.length) fields.education = eduRows;
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
        {!found ? <p className="mt-2 text-sm text-gray-500" data-testid="resume-nothing-found">We couldn't find profile details in this CV. You can still add your preferred job titles and cities below, or fill in your profile.</p> : null}
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
                <Input label={label} value={vals[k]} onChange={(e) => setVal(k, e.target.value)} data-testid={`resume-field-${k}`}
                  hint={kind === "list" ? "Separate with commas" : undefined} />
              )}
              {isConfirmed(k) ? <p className="mt-1 text-xs text-amber-700">You confirmed this before — tick to replace it.</p> : null}
            </div>
          </div>
        ))}
      </div>
      <div className="space-y-2 rounded-xl border border-gray-200 p-3" data-testid="resume-education">
        <label className="flex items-center gap-2 text-sm font-bold">
          <input type="checkbox" className="h-4 w-4 accent-[var(--brand,#6D28D9)]" checked={useEdu} onChange={(e) => setUseEdu(e.target.checked)} data-testid="resume-use-education" />
          Education
        </label>
        {isConfirmed("education") ? <p className="text-xs text-amber-700">You confirmed this before — tick to replace it.</p> : null}
        {edu.map((r, i) => (
          <div key={i} className="grid items-end gap-2 md:grid-cols-[1fr_1.5fr_6rem_auto]">
            <Input label="Degree" value={r.degree} onChange={(e) => setEduRow(i, "degree", e.target.value)} data-testid={`resume-edu-degree-${i}`} />
            <Input label="Institution" value={r.institution} onChange={(e) => setEduRow(i, "institution", e.target.value)} data-testid={`resume-edu-institution-${i}`} />
            <Input label="Year" inputMode="numeric" maxLength={4} value={r.year} onChange={(e) => setEduRow(i, "year", e.target.value.replace(/\D/g, ""))} data-testid={`resume-edu-year-${i}`} />
            <button type="button" className="mb-2 rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-600" title="Remove" onClick={() => setEdu((rows) => rows.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
        <button type="button" className="text-sm font-semibold text-brand" onClick={() => setEdu((rows) => [...rows, blankEdu()])} data-testid="resume-edu-add">+ Add education</button>
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
  const [tab, setTab] = useState(null);
  const [text, setText] = useState("");
  const { data, refetch } = useQuery({ queryKey: ["my-resume"], queryFn: () => api("/resume") });
  const cur = data?.current;
  const pending = cur && ["queued", "processing"].includes(cur.status);
  useEffect(() => {
    if (!pending) return undefined;
    const t = setInterval(refetch, 2000);
    return () => clearInterval(t);
  }, [pending, refetch]);
  if (!data) return null;
  const mode = tab || (data.uploads_enabled ? "upload" : "paste");
  const isPaste = (r) => r?.source === "paste";

  const pick = async (file) => {
    if (!file) return;
    if (!/\.(pdf|docx?)$/i.test(file.name)) return notify("Please choose a PDF or Word (.doc or .docx) file", "error");
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
  const submitPaste = async () => {
    const t = text.trim();
    if (t.length < PASTE_MIN) return notify(`Please paste your full CV — at least ${PASTE_MIN} characters`, "error");
    if (t.length > PASTE_MAX) return notify(`Please paste at most ${PASTE_MAX.toLocaleString()} characters`, "error");
    setBusy(true);
    try {
      const res = await api("/resume/paste", { method: "POST", body: { text: t } });
      notify(res.duplicate ? "You've pasted this CV before — it's your current CV again" : "CV read — check the details below", "success");
      setText("");
      setReviewAgain(res.resume?.status === "confirmed");
      await refetch();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
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
          <p className="muted">Upload a PDF or Word file (up to {data.max_mb} MB) or paste your CV as text. We read it to fill in your profile and personalise your daily job search — you review everything first.</p>
        </div>
        {mode === "upload" && data.uploads_enabled ? (
          <>
            <input ref={input} type="file" accept=".pdf,.doc,.docx" className="hidden" onChange={(e) => pick(e.target.files?.[0])} data-testid="resume-input" />
            <Button title={cur ? "Replace resume" : "Upload resume"} icon={<Upload className="h-4 w-4" />} loading={busy}
              onClick={() => input.current?.click()} data-testid="resume-upload" />
          </>
        ) : null}
      </div>
      <div className="inline-flex rounded-xl bg-gray-100 p-1 text-sm font-semibold" role="tablist">
        {[["upload", "Upload file"], ["paste", "Paste text"]].map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={mode === k} onClick={() => setTab(k)} data-testid={`resume-tab-${k}`}
            className={`rounded-lg px-4 py-1.5 ${mode === k ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-800"}`}>{l}</button>
        ))}
      </div>
      {mode === "upload" && !data.uploads_enabled ? <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800" data-testid="resume-disabled">File upload is coming soon. You can paste your CV as text instead.</p> : null}
      {mode === "paste" ? (
        <div className="space-y-3" data-testid="resume-paste">
          <Input multiline rows={10} label="Paste your CV" value={text} maxLength={PASTE_MAX} onChange={(e) => setText(e.target.value)}
            placeholder="Copy everything from your CV (Ctrl+A, Ctrl+C) and paste it here" data-testid="resume-paste-text"
            hint={`${text.trim().length.toLocaleString()} / ${PASTE_MAX.toLocaleString()} characters${text.trim().length && text.trim().length < PASTE_MIN ? ` · at least ${PASTE_MIN} needed` : ""}`} />
          <Button title={cur ? "Use this CV instead" : "Read my CV"} loading={busy} disabled={text.trim().length < PASTE_MIN} onClick={submitPaste} data-testid="resume-paste-submit" />
        </div>
      ) : null}
      {cur ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-gray-200 p-4">
            <div className="flex items-center gap-3">
              <FileText className="h-8 w-8 text-brand" />
              <div>
                <p className="text-sm font-bold" data-testid="resume-filename">{cur.original_filename}</p>
                <p className="text-xs text-gray-500">{isPaste(cur) ? "Pasted" : "Uploaded"} {fmtDate(cur.uploaded_at)} · version {cur.version}</p>
              </div>
              <Badge label={label} color={color} data-testid="resume-status" />
            </div>
            <div className="flex gap-2">
              {!isPaste(cur) ? (
                <>
                  <Button size="sm" variant="outline" title="View" onClick={() => view(cur)} data-testid="resume-view" />
                  <Button size="sm" variant="outline" title="Download" onClick={() => downloadFile(`/resume/${cur.resume_id}/file`, { download: "1" }, cur.original_filename).catch((e) => notify(errMsg(e), "error"))} data-testid="resume-download" />
                </>
              ) : null}
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
      ) : <p className="text-sm text-gray-500" data-testid="resume-empty">No CV added yet.</p>}
      {data.resumes.length > 1 ? (
        <div className="space-y-1" data-testid="resume-history">
          <p className="text-xs font-bold uppercase tracking-wide text-gray-500">Earlier versions</p>
          {data.resumes.filter((r) => !r.is_current).map((r) => (
            <div key={r.resume_id} className="flex items-center justify-between text-sm">
              <span>v{r.version} · {r.original_filename} · {fmtDate(r.uploaded_at)}</span>
              <span className="flex gap-3">
                {!isPaste(r) ? <button className="font-semibold text-brand" onClick={() => view(r)}>View</button> : null}
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
