import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Briefcase, CheckCircle2, GraduationCap, Upload } from "lucide-react";
import { api, uploadForm } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { EXPERIENCED_BLANK, FRESHER_TEMPLATES } from "@/lib/resumeTemplates";
import { Badge, Button, Card, errMsg, notify, PageHeader } from "@/components/kit";
import { AiDisclaimer, areaCls, CareerToolsCards, ConsentGate, UsagePill, useCareerUsage, useInvalidateUsage } from "@/components/career";
import { Page } from "@/components/Layout";

export function CareerHub() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data } = useCareerUsage();
  return (
    <Page>
      <PageHeader title="Build, check & practise" subtitle="Create ATS-friendly resumes, check your fit for a job and prepare for interviews — all in one place." />
      {!user ? (
        <Button title="Login to use Career Tools" onClick={() => navigate("/auth/login")} data-testid="career-login" />
      ) : (
        <div className="space-y-4">
          {data?.tier ? (
            <p className="text-sm font-semibold text-brand-ink" data-testid="career-tier">
              Your access level: {data.tier === "free" ? "Free" : `Member (${data.tier.replace("_", "-")})`}
            </p>
          ) : null}
          <CareerToolsCards />
        </div>
      )}
      <div className="mt-8"><AiDisclaimer /></div>
    </Page>
  );
}

function SamplePreview({ t }) {
  return (
    <div className="mt-4 rounded-lg border border-gray-300 bg-white p-4" data-testid={`rb-sample-${t.key}`}>
      <Badge label="SAMPLE — placeholder content" color="warning" />
      <p className="mt-2 text-lg font-extrabold">{t.sample.name}</p>
      <p className="text-xs text-gray-500">{t.sample.contact}</p>
      {t.sample.sections.map((s) => (
        <div key={s.title} className="mt-3">
          <p className="border-b border-gray-100 pb-0.5 text-[11px] font-extrabold tracking-wider">{s.title}</p>
          <p className="mt-1 whitespace-pre-line text-xs text-gray-600">{s.content}</p>
        </div>
      ))}
    </div>
  );
}

function TypeCard({ Icon, title, desc, button, onClick, testId }) {
  return (
    <Card className="flex flex-col gap-4 p-8" data-testid={testId}>
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-soft"><Icon className="h-7 w-7 text-brand" /></span>
      <p className="text-xl font-extrabold">{title}</p>
      <p className="flex-1 text-sm text-gray-600">{desc}</p>
      <Button size="lg" title={button} onClick={onClick} data-testid={`${testId}-btn`} />
    </Card>
  );
}

export function ResumeBuilder() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: usage } = useCareerUsage();
  const invalidate = useInvalidateUsage();
  const [step, setStep] = useState("choose");
  const [preview, setPreview] = useState("general");
  const [pasted, setPasted] = useState("");
  const [busy, setBusy] = useState(null);
  const fileRef = React.useRef(null);

  const ownPersonal = {
    full_name: user?.full_name || "", email: user?.email || "", phone: user?.mobile || "",
    location: "", preferred_location: user?.preferred_location || "", linkedin: "",
  };
  const guard = async (key, fn) => {
    if (busy) return;
    setBusy(key);
    try {
      await fn();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(null);
    }
  };
  const createFromTemplate = (key, rtype, sections) => guard(key, async () => {
    const res = await api("/career/resumes", {
      method: "POST",
      body: {
        title: key,
        resume_type: rtype,
        personal: ownPersonal,
        sections: sections.map((s) => ({ title: s.title, content: "", hint: s.hint + (s.optional ? "\n(Optional — remove if not needed)" : "") })),
      },
    });
    navigate(`/career/resume/${res.resume.resume_id}`, { replace: true });
  });
  const onFile = (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 5 * 1024 * 1024) return notify("Please choose a file under 5 MB", "error");
    guard("upload", async () => {
      const res = await uploadForm("/career/resumes/extract-file", f);
      await invalidate();
      notify("Resume auto-filled — please review every section", "success");
      navigate(`/career/resume/${res.resume.resume_id}`, { replace: true });
    });
  };
  const extract = () => {
    if (pasted.trim().length < 150) return notify("Please paste your complete resume text", "error");
    guard("extract", async () => {
      const res = await api("/career/resumes/extract", { method: "POST", body: { resume_text: pasted } });
      await invalidate();
      notify("Resume auto-filled — please review every section", "success");
      navigate(`/career/resume/${res.resume.resume_id}`, { replace: true });
    });
  };

  return (
    <Page>
      <PageHeader title="ATS Resume Builder" right={step !== "choose" ? (
        <Button variant="ghost" size="sm" title="Change type" onClick={() => setStep("choose")} data-testid="rb-change-type" />
      ) : null} />
      {step === "choose" ? (
        <>
          <h2 className="h-sec mb-4">Choose your resume type</h2>
          <div className="grid gap-6 md:grid-cols-2">
            <TypeCard Icon={GraduationCap} title="Fresher Resume" button="Create Fresher Resume" onClick={() => setStep("fresher")} testId="rb-type-fresher"
              desc="For students, recent graduates and candidates with no full-time work experience. Start from a ready-made template." />
            <TypeCard Icon={Briefcase} title="Experienced Resume" button="Create Experienced Resume" onClick={() => setStep("experienced")} testId="rb-type-experienced"
              desc="For candidates who have worked previously or are currently employed. Paste your existing resume and we auto-fill it." />
          </div>
        </>
      ) : null}
      {step === "fresher" ? (
        <>
          <h2 className="h-sec">Pick a template to start</h2>
          <p className="muted mb-6 mt-1">All templates are single-column and ATS-friendly. Sample text is a placeholder only — it is never added to your resume.</p>
          <div className="grid gap-5 lg:grid-cols-3">
            {FRESHER_TEMPLATES.map((t) => (
              <Card key={t.key} className={`flex flex-col ${preview === t.key ? "border-2 border-brand" : ""}`} data-testid={`rb-template-${t.key}`}>
                <button className="text-left" onClick={() => setPreview(t.key)}>
                  <div className="flex items-center justify-between">
                    <p className="font-extrabold">{t.name}</p>
                    {preview === t.key ? <CheckCircle2 className="h-5 w-5 text-brand" /> : null}
                  </div>
                  <p className="mt-1 text-sm text-gray-500">{t.desc}</p>
                </button>
                {preview === t.key ? <SamplePreview t={t} /> : (
                  <Button className="mt-3" variant="ghost" size="sm" title="Preview" onClick={() => setPreview(t.key)} data-testid={`rb-preview-${t.key}`} />
                )}
                <div className="flex-1" />
                {preview === t.key ? (
                  <Button className="mt-4" title="Use This Template" loading={busy === t.name}
                    onClick={() => createFromTemplate(t.name, "fresher", t.sections)} data-testid={`rb-use-${t.key}`} />
                ) : null}
              </Card>
            ))}
          </div>
        </>
      ) : null}
      {step === "experienced" ? (
        <ConsentGate>
          <h2 className="h-sec">Create Your Resume in Minutes</h2>
          <p className="muted mb-6 mt-1">Upload your existing resume, or copy and paste it below. JobRadar will extract the information and organise it into a professional, ATS-friendly format.</p>
          <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
            <Card className="h-fit space-y-3" data-testid="rb-upload-card">
              <p className="font-extrabold">Upload Your Resume</p>
              <p className="text-sm text-gray-500">PDF or Word (.doc or .docx), up to 5 MB. Scanned images can't be read — paste the text instead.</p>
              <input ref={fileRef} type="file" accept=".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                className="hidden" onChange={onFile} data-testid="rb-upload-input" />
              <Button full title="Upload PDF or Word File" icon={<Upload className="h-4 w-4" />} loading={busy === "upload"}
                disabled={!!busy && busy !== "upload"} onClick={() => fileRef.current?.click()} data-testid="rb-upload" />
              {busy === "upload" ? <p className="text-xs text-gray-500">Reading your file and organising sections… about 20–40 seconds.</p> : null}
            </Card>
            <Card className="space-y-3">
              <p className="font-extrabold">Paste Your Existing Resume</p>
              <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} maxLength={15000} className={`${areaCls} min-h-[280px]`}
                placeholder="Copy your current resume from Word, PDF text or another document and paste it here..." data-testid="rb-paste" />
              <p className="text-right text-xs text-gray-400">{pasted.length.toLocaleString()} / 15,000 characters</p>
              <UsagePill tool="resume_builder" usage={usage} />
              <Button title="Analyse & Auto-Fill Resume" loading={busy === "extract"} onClick={extract} data-testid="rb-extract" />
              {busy === "extract" ? <p className="text-xs text-gray-500">Reading your resume and organising sections… this takes about 20–40 seconds.</p> : null}
              <p className="text-xs text-gray-500">We only use what you paste. Nothing is invented — anything missing or unclear will be listed for you to fill in.</p>
              <Button variant="ghost" size="sm" title="No resume to paste? Start from a blank template" loading={busy === "Experienced Resume"}
                onClick={() => createFromTemplate("Experienced Resume", "experienced", EXPERIENCED_BLANK)} data-testid="rb-exp-blank" />
            </Card>
          </div>
        </ConsentGate>
      ) : null}
    </Page>
  );
}
