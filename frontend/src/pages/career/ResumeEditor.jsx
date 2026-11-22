import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { NEW_ROLE_BLOCK, STYLE_LOOK, STYLES } from "@/lib/resumeTemplates";
import { Badge, Button, Card, Chip, errMsg, Input, Modal, notify, Spinner } from "@/components/kit";
import { areaCls, BulletList, downloadResume, UsagePill, useCareerUsage, useInvalidateUsage } from "@/components/career";
import { Page } from "@/components/Layout";

const PERSONAL = [
  ["full_name", "Full name *"], ["email", "Email *"], ["phone", "Phone *"],
  ["location", "City"], ["preferred_location", "Preferred job location"], ["linkedin", "LinkedIn (optional)"],
];

export function ResumePaper({ personal, sections, template }) {
  const look = STYLE_LOOK[template] || STYLE_LOOK.classic;
  const serif = look.font ? { fontFamily: look.font } : undefined;
  const accent = look.accent;
  const contact = [personal.email, personal.phone, personal.location,
    personal.preferred_location ? `Preferred location: ${personal.preferred_location}` : "", personal.linkedin].filter(Boolean);
  const visible = sections.filter((s) => s.content?.trim());
  return (
    <div className="rounded-md border border-gray-300 bg-white p-8 shadow-sm" style={serif} data-testid="re-paper">
      <p className={`${look.name} font-extrabold`} style={{ color: accent }}>{personal.full_name || "Your Name"}</p>
      {contact.length ? <p className="mt-1 text-xs text-gray-600">{contact.join(" | ")}</p> : null}
      {visible.map((s, i) => (
        <div key={s.id || i} className="mt-5">
          <p className={`mb-1 pb-0.5 text-xs font-extrabold tracking-wider ${look.rule ? "border-b border-gray-400" : ""}`} style={{ color: accent }}>{s.title.toUpperCase()}</p>
          {s.content.split("\n").filter((l) => l.trim()).map((l, j) => {
            const b = /^\s*[-•*]\s/.test(l);
            return <p key={j} className={`text-[13px] leading-relaxed text-gray-800 ${b ? "pl-3" : ""}`}>{b ? "• " + l.replace(/^\s*[-•*]\s/, "") : l}</p>;
          })}
        </div>
      ))}
      {visible.length === 0 ? <p className="mt-4 text-sm text-gray-400">Your sections are empty — add your details to see them here.</p> : null}
    </div>
  );
}

function SectionEditor({ s, i, onChange, onMove, onRemove }) {
  return (
    <Card className="space-y-3" data-testid={`re-section-${i}`}>
      <div className="flex items-center gap-2">
        <input value={s.title} onChange={(e) => onChange({ title: e.target.value })} placeholder="SECTION HEADING"
          className="flex-1 border-b border-gray-100 bg-transparent py-1.5 text-sm font-extrabold tracking-wider outline-none focus:border-brand" data-testid={`re-section-title-${i}`} />
        <button onClick={() => onMove(-1)} className="rounded-lg bg-brand-mist p-2 hover:bg-brand-soft" data-testid={`re-up-${i}`}><ArrowUp className="h-4 w-4 text-brand" /></button>
        <button onClick={() => onMove(1)} className="rounded-lg bg-brand-mist p-2 hover:bg-brand-soft" data-testid={`re-down-${i}`}><ArrowDown className="h-4 w-4 text-brand" /></button>
        <button onClick={onRemove} className="rounded-lg bg-red-50 p-2 hover:bg-red-100" data-testid={`re-remove-${i}`}><Trash2 className="h-4 w-4 text-red-600" /></button>
      </div>
      <textarea value={s.content} onChange={(e) => onChange({ content: e.target.value })} placeholder={s.hint || "Write this section"}
        className={`${areaCls} min-h-[140px]`} data-testid={`re-section-content-${i}`} />
    </Card>
  );
}

function LineDiff({ text, other, tone }) {
  const others = new Set((other || "").split("\n").map((l) => l.trim()).filter(Boolean));
  const lines = (text || "").split("\n").filter((l) => l.trim());
  if (!lines.length) return <p className="text-sm italic text-gray-400">(empty)</p>;
  return lines.map((l, i) => {
    const changed = !others.has(l.trim());
    const cls = changed ? (tone === "after" ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-800 line-through decoration-red-300") : "text-gray-700";
    return <p key={i} className={`rounded px-1 text-[13px] leading-relaxed ${cls}`}>{l}</p>;
  });
}

// Before/after review of a tailoring proposal. Nothing is saved until the candidate keeps at least one change.
function TailorReview({ draft, onCancel, onSaved }) {
  const reviewable = draft.sections.filter((r) => r.status !== "unchanged");
  // Reworded sections start as kept; sections the AI added start as left out, so nothing new slips in unread.
  const [keep, setKeep] = useState(() => Object.fromEntries(reviewable.map((r) => [r.key, r.status !== "new"])));
  const [edits, setEdits] = useState({});
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const accepted = Object.keys(keep).filter((k) => keep[k]);
  const save = async () => {
    setSaving(true);
    try {
      const res = await api(`/career/tailor-drafts/${draft.draft_id}/apply`, { method: "POST", body: { accepted, edits } });
      onSaved(res.resume);
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setSaving(false);
    }
  };
  return (
    <Page>
      <div className="mb-6">
        <button onClick={onCancel} className="text-sm font-bold text-brand hover:underline" data-testid="tr-back">‹ Back to my resume (nothing saved)</button>
        <h1 className="h-page mt-2">Review suggested changes</h1>
        <p className="muted mt-1">For: {draft.jd_title}. Keep only changes that are true to your background. Your original resume stays unchanged; what you keep is saved as a new version.</p>
      </div>
      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          {reviewable.length === 0 ? <Card><p className="muted">No changes were suggested. Your resume already fits this job description well.</p></Card> : null}
          {reviewable.map((r) => (
            <Card key={r.key} className={`space-y-3 ${keep[r.key] ? "border-brand" : ""}`} data-testid={`tr-section-${r.key}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-extrabold tracking-wide">{r.title.toUpperCase()} {r.status === "new" ? <Badge label="New section" color="warning" /> : null}</p>
                <div className="flex gap-2">
                  <Chip label="Keep change" selected={!!keep[r.key]} onClick={() => setKeep((k) => ({ ...k, [r.key]: true }))} data-testid={`tr-keep-${r.key}`} />
                  <Chip label={r.status === "new" ? "Leave out" : "Keep original"} selected={!keep[r.key]} onClick={() => setKeep((k) => ({ ...k, [r.key]: false }))} data-testid={`tr-reject-${r.key}`} />
                </div>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div><p className="mb-1 text-xs font-bold uppercase text-gray-400">Before</p><LineDiff text={r.before} other={r.after} tone="before" /></div>
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <p className="text-xs font-bold uppercase text-gray-400">After</p>
                    <button className="text-xs font-semibold text-brand hover:underline" onClick={() => setEditing(editing === r.key ? null : r.key)} data-testid={`tr-edit-${r.key}`}>{editing === r.key ? "Done" : "Edit"}</button>
                  </div>
                  {editing === r.key ? (
                    <textarea value={edits[r.key] ?? r.after} onChange={(e) => { const v = e.target.value; setEdits((x) => ({ ...x, [r.key]: v })); setKeep((k) => ({ ...k, [r.key]: true })); }}
                      className={`${areaCls} min-h-[160px]`} data-testid={`tr-edit-area-${r.key}`} />
                  ) : <LineDiff text={edits[r.key] ?? r.after} other={r.before} tone="after" />}
                </div>
              </div>
            </Card>
          ))}
        </div>
        <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
          {draft.missing_keywords?.length ? (
            <Card className="space-y-2" data-testid="tr-missing-keywords">
              <p className="font-extrabold">Keywords in the job you don't show yet</p>
              <div className="flex flex-wrap gap-1.5">{draft.missing_keywords.map((k) => <Badge key={k} label={k} color="warning" />)}</div>
              <p className="text-xs text-gray-500">Add one only if you genuinely have that skill or experience. Never add something untrue.</p>
            </Card>
          ) : null}
          {draft.matched_keywords?.length ? (
            <Card className="space-y-2">
              <p className="font-extrabold">Keywords you already match</p>
              <div className="flex flex-wrap gap-1.5">{draft.matched_keywords.map((k) => <Badge key={k} label={k} color="success" />)}</div>
            </Card>
          ) : null}
          {draft.changes?.length ? <Card className="space-y-2"><p className="font-extrabold">Why these changes</p><BulletList items={draft.changes} /></Card> : null}
          <Card className="space-y-3">
            <p className="text-sm text-gray-600">{accepted.length} of {reviewable.length} change(s) kept.</p>
            <Button full title="Save as new version" loading={saving} disabled={!accepted.length} onClick={save} data-testid="tr-save" />
            <Button full variant="ghost" title="Discard all" onClick={onCancel} data-testid="tr-discard" />
          </Card>
        </aside>
      </div>
    </Page>
  );
}

export default function ResumeEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const invalidate = useInvalidateUsage();
  const { data: usage } = useCareerUsage();
  const { data, isLoading, refetch } = useQuery({ queryKey: ["resume", id], queryFn: () => api(`/career/resumes/${id}`) });
  const [title, setTitle] = useState("");
  const [personal, setPersonal] = useState({});
  const [sections, setSections] = useState([]);
  const [template, setTemplate] = useState("classic");
  const [missing, setMissing] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(null);
  const [jd, setJd] = useState("");
  const [showTailor, setShowTailor] = useState(false);
  const [showDownload, setShowDownload] = useState(false);
  const [draft, setDraft] = useState(null);
  const { data: savedJobs } = useQuery({ queryKey: ["saved-jobs"], queryFn: () => api("/saved-jobs"), enabled: showTailor });
  const pickJob = async (jobId) => {
    if (!jobId) return;
    try {
      const p = await api(`/career/job-prefill/${jobId}`);
      setJd(p.jd_text);
      if (!p.full_jd) notify("Only the job preview is available on the free plan. Paste the full description for better results.", "info");
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };

  useEffect(() => {
    const r = data?.resume;
    if (r) {
      setTitle(r.title);
      setPersonal(r.personal || {});
      setSections(r.sections || []);
      setTemplate(r.template || "classic");
      setMissing(r.missing_fields || []);
      setDirty(false);
    }
  }, [data]);

  const edit = (fn) => { fn(); setDirty(true); };
  const setSec = (i, patch) => edit(() => setSections((arr) => arr.map((x, j) => (j === i ? { ...x, ...patch } : x))));
  const move = (i, d) => edit(() => setSections((s) => {
    const n = [...s];
    const j = i + d;
    if (j < 0 || j >= n.length) return s;
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  }));
  const addExperience = () => edit(() => setSections((arr) => {
    const i = arr.findIndex((s) => /EXPERIENCE/i.test(s.title));
    if (i === -1) return [...arr, { title: "WORK EXPERIENCE", content: NEW_ROLE_BLOCK }];
    return arr.map((s, j) => (j === i ? { ...s, content: (s.content ? s.content.trimEnd() + "\n\n" : "") + NEW_ROLE_BLOCK } : s));
  }));

  const save = async (silent = false) => {
    setBusy("save");
    try {
      await api(`/career/resumes/${id}`, {
        method: "PUT",
        body: { title, resume_type: data.resume.resume_type, personal, sections, template, missing_fields: missing, target_job: data.resume.target_job || "" },
      });
      setDirty(false);
      await refetch();
      if (!silent) notify("Resume saved to your account", "success");
      return true;
    } catch (e) {
      notify(errMsg(e), "error");
      return false;
    } finally {
      setBusy(null);
    }
  };
  const step = async (key, fn) => {
    if (dirty && !(await save(true))) return;
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(null);
    }
  };
  const download = (fmt) => {
    if (!personal.full_name?.trim()) return notify("Please add your full name before downloading", "error");
    step(fmt, async () => { await downloadResume(id, fmt); setShowDownload(false); });
  };
  const duplicate = () => step("dup", async () => {
    const res = await api(`/career/resumes/${id}/duplicate`, { method: "POST" });
    notify("New version created", "success");
    navigate(`/career/resume/${res.resume.resume_id}`, { replace: true });
  });
  const tailor = () => step("tailor", async () => {
    const res = await api(`/career/resumes/${id}/tailor`, { method: "POST", body: { jd_text: jd } });
    await invalidate();
    setDraft(res.draft);
    window.scrollTo(0, 0);
  });

  if (isLoading || !data) return <Spinner />;
  if (draft) {
    return <TailorReview draft={draft} onCancel={() => setDraft(null)} onSaved={(r) => {
      setDraft(null);
      notify("Tailored version saved. Your original resume is unchanged.", "success");
      navigate(`/career/resume/${r.resume_id}`);
    }} />;
  }
  const notes = data.resume.notes || [];
  const pending = data.pending_tailoring;
  const openPending = () => step("pending", async () => {
    const res = await api(`/career/tailor-drafts/${pending.draft_id}`);
    setDraft(res.draft);
    window.scrollTo(0, 0);
  });

  return (
    <Page>
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <button onClick={() => navigate("/career/history")} className="text-sm font-bold text-brand hover:underline" data-testid="re-back">‹ My resumes</button>
          <h1 className="h-page mt-2">Review & Edit</h1>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" title={dirty ? "Save Resume" : "Saved ✓"} loading={busy === "save"} disabled={!dirty} onClick={() => save()} data-testid="re-save" />
          <Button title="Download Resume" onClick={() => setShowDownload(true)} data-testid="re-download" />
        </div>
      </div>
      <div className="grid gap-8 xl:grid-cols-[1fr_1fr]">
        <div className="space-y-5">
          {missing.length > 0 ? (
            <Card className="space-y-2 border-amber-400 bg-brand-mist" data-testid="re-missing">
              <p className="flex items-center gap-2 font-extrabold"><AlertCircle className="h-5 w-5 text-amber-600" />Please add these missing details</p>
              <p className="text-xs text-gray-500">Everything else was filled in for you. Add only what is true, then click ✕ when done.</p>
              {missing.map((m, i) => (
                <div key={m + i} className="flex items-center justify-between text-sm">
                  <span>• {m}</span>
                  <button onClick={() => edit(() => setMissing((a) => a.filter((_, j) => j !== i)))} data-testid={`re-missing-done-${i}`}><X className="h-4 w-4 text-gray-400" /></button>
                </div>
              ))}
            </Card>
          ) : null}
          {pending ? (
            <Card className="flex flex-wrap items-center justify-between gap-3 border-brand bg-brand-mist" data-testid="re-pending-tailoring">
              <p className="text-sm"><span className="font-extrabold">Suggested changes waiting for review</span><br />For: {pending.jd_title}</p>
              <Button size="sm" title="Review changes" loading={busy === "pending"} onClick={openPending} data-testid="re-pending-open" />
            </Card>
          ) : null}
          {notes.length > 0 ? (
            <Card className="space-y-2" data-testid="re-tailor-notes">
              <p className="font-extrabold">Suggested changes for this job</p>
              <BulletList items={notes} />
              <p className="text-xs text-gray-500">Review each change — remove anything that does not reflect your real background.</p>
            </Card>
          ) : null}
          <Card className="space-y-3">
            <p className="font-extrabold">Template</p>
            <div className="flex flex-wrap gap-2">
              {STYLES.map((s) => <Chip key={s.key} label={s.name} selected={template === s.key} onClick={() => edit(() => setTemplate(s.key))} data-testid={`re-style-${s.key}`} />)}
            </div>
            <p className="text-xs text-gray-500">All templates are single-column, ATS-friendly and use standard headings.</p>
          </Card>
          <Card className="grid gap-4 md:grid-cols-2">
            <Input className="md:col-span-2" label="Resume name (only you see this)" value={title} onChange={(e) => edit(() => setTitle(e.target.value))} data-testid="re-title" />
            {PERSONAL.map(([k, label]) => (
              <Input key={k} label={label} value={personal[k] || ""} type={k === "email" ? "email" : "text"}
                onChange={(e) => { const v = e.target.value; edit(() => setPersonal((p) => ({ ...p, [k]: v }))); }} data-testid={`re-${k}`} />
            ))}
          </Card>
          <p className="text-xs text-gray-500">Grey text in a box is guidance only and is never included in your resume. Start lines with “- ” for bullet points. Empty sections are left out of the download.</p>
          {sections.map((s, i) => (
            <SectionEditor key={s.id || i} s={s} i={i} onChange={(p) => setSec(i, p)} onMove={(d) => move(i, d)}
              onRemove={() => edit(() => setSections((arr) => arr.filter((_, j) => j !== i)))} />
          ))}
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" title="Add Section" icon={<Plus className="h-4 w-4" />}
              onClick={() => edit(() => setSections((arr) => [...arr, { title: "NEW SECTION", content: "" }]))} data-testid="re-add-section" />
            <Button variant="outline" size="sm" title="Add Work Experience" icon={<Plus className="h-4 w-4" />} onClick={addExperience} data-testid="re-add-experience" />
            <Button variant="ghost" size="sm" title="Save as New Version" loading={busy === "dup"} onClick={duplicate} data-testid="re-duplicate" />
          </div>
          <Card className="space-y-3">
            <p className="font-extrabold">Customise My Resume for a Job (optional)</p>
            <p className="text-sm text-gray-500">Pick a saved JobRadar job or paste a job description. JobRadar suggests changes to your summary, skills and experience wording — only where your real background supports it. You review every change before anything is saved; this version stays unchanged.</p>
            {showTailor ? (
              <>
                {savedJobs?.jobs?.length ? (
                  <select className="field" defaultValue="" onChange={(e) => pickJob(e.target.value)} data-testid="re-tailor-job">
                    <option value="">Use one of my saved jobs…</option>
                    {savedJobs.jobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.title} · {j.company}</option>)}
                  </select>
                ) : null}
                <textarea value={jd} onChange={(e) => setJd(e.target.value)} maxLength={12000} className={areaCls} placeholder="Paste the complete job description" data-testid="re-tailor-jd" />
                <UsagePill tool="resume_builder" usage={usage} />
                <Button title="Suggest Changes" loading={busy === "tailor"} onClick={tailor} data-testid="re-tailor-submit" />
              </>
            ) : (
              <Button variant="outline" title="Customise My Resume for a Job" onClick={() => setShowTailor(true)} data-testid="re-tailor-open" />
            )}
          </Card>
        </div>
        <div className="xl:sticky xl:top-24 xl:self-start" data-testid="re-preview">
          <p className="mb-3 text-xs font-bold uppercase tracking-wider text-gray-400">Live preview</p>
          <ResumePaper personal={personal} sections={sections} template={template} />
        </div>
      </div>
      <Modal open={showDownload} onClose={() => setShowDownload(false)}>
        <p className="text-xl font-extrabold">Download Resume</p>
        <p className="muted mt-1">Both formats contain selectable, ATS-readable text.</p>
        <div className="mt-5 space-y-2">
          <Button full title="Download PDF" loading={busy === "pdf"} onClick={() => download("pdf")} data-testid="re-download-pdf" />
          <Button full variant="secondary" title="Download Word (DOCX)" loading={busy === "docx"} onClick={() => download("docx")} data-testid="re-download-docx" />
          <Button full variant="ghost" title="Cancel" onClick={() => setShowDownload(false)} data-testid="re-download-cancel" />
        </div>
      </Modal>
    </Page>
  );
}
