import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { NEW_ROLE_BLOCK, STYLES } from "@/lib/resumeTemplates";
import { Button, Card, Chip, errMsg, Input, Modal, notify, Spinner } from "@/components/kit";
import { areaCls, BulletList, downloadResume, UsagePill, useCareerUsage, useInvalidateUsage } from "@/components/career";
import { Page } from "@/components/Layout";

const PERSONAL = [
  ["full_name", "Full name *"], ["email", "Email *"], ["phone", "Phone *"],
  ["location", "City"], ["preferred_location", "Preferred job location"], ["linkedin", "LinkedIn (optional)"],
];

export function ResumePaper({ personal, sections, template }) {
  const serif = template === "compact" ? { fontFamily: "Georgia, serif" } : undefined;
  const accent = template === "modern" ? "#1F3A5F" : "#111111";
  const contact = [personal.email, personal.phone, personal.location,
    personal.preferred_location ? `Preferred location: ${personal.preferred_location}` : "", personal.linkedin].filter(Boolean);
  const visible = sections.filter((s) => s.content?.trim());
  return (
    <div className="rounded-md border border-gray-300 bg-white p-8 shadow-sm" style={serif} data-testid="re-paper">
      <p className="text-2xl font-extrabold" style={{ color: accent }}>{personal.full_name || "Your Name"}</p>
      {contact.length ? <p className="mt-1 text-xs text-gray-600">{contact.join(" | ")}</p> : null}
      {visible.map((s, i) => (
        <div key={s.id || i} className="mt-5">
          <p className="mb-1 border-b border-gray-400 pb-0.5 text-xs font-extrabold tracking-wider" style={{ color: accent }}>{s.title.toUpperCase()}</p>
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
    notify("Customised version saved — review the suggested changes", "success");
    navigate(`/career/resume/${res.resume.resume_id}`, { replace: true });
  });

  if (isLoading || !data) return <Spinner />;
  const notes = data.resume.notes || [];

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
          {notes.length > 0 ? (
            <Card className="space-y-2" data-testid="re-tailor-notes">
              <p className="font-extrabold">Suggested changes for this job</p>
              <BulletList items={notes} />
              <p className="text-xs text-gray-500">Review each change — remove anything that does not reflect your real background.</p>
            </Card>
          ) : null}
          <Card className="space-y-3">
            <p className="font-extrabold">Template</p>
            <div className="flex gap-2">
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
            <p className="text-sm text-gray-500">Paste a job description and JobRadar will adjust your summary, skills and experience wording — only where your real background supports it. A new version is saved; this one stays unchanged.</p>
            {showTailor ? (
              <>
                <textarea value={jd} onChange={(e) => setJd(e.target.value)} maxLength={12000} className={areaCls} placeholder="Paste the complete job description" data-testid="re-tailor-jd" />
                <UsagePill tool="resume_builder" usage={usage} />
                <Button title="Customise My Resume" loading={busy === "tailor"} onClick={tailor} data-testid="re-tailor-submit" />
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
