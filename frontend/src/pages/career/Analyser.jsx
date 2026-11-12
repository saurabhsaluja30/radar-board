import React, { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Badge, Button, Card, errMsg, notify, PageHeader } from "@/components/kit";
import { AiDisclaimer, areaCls, BulletList, ConsentGate, ScoreRing, UsagePill, useCareerUsage, useInvalidateUsage } from "@/components/career";
import { Page } from "@/components/Layout";

const ST = { ok: "success", warning: "warning", issue: "error" };
const H = ({ children }) => <p className="mb-3 font-extrabold text-gray-900">{children}</p>;

function AnalysisResult({ res }) {
  return (
    <div className="grid gap-5 lg:grid-cols-2" data-testid="an-result">
      <Card className="lg:col-span-2">
        <H>A. Resume–JD Match Score (estimate)</H>
        <div className="grid items-center gap-6 md:grid-cols-[160px_1fr_1fr]">
          <ScoreRing score={res.match_score ?? 0} />
          <p className="text-sm text-gray-600">{res.score_explanation}</p>
          <div className="space-y-1.5">
            {(res.score_breakdown || []).map((b) => (
              <div key={b.factor} className="flex justify-between text-sm"><span className="text-gray-600">{b.factor} ({b.weight}%)</span><span className="font-bold">{b.score}/100</span></div>
            ))}
          </div>
        </div>
        {res.limitations ? <p className="mt-4 text-xs text-gray-500">Limitations: {res.limitations}</p> : null}
      </Card>
      <Card>
        <H>B. Matching Skills</H>
        <div className="space-y-1.5 text-sm text-gray-700" data-testid="an-matching">
          {(res.matching_skills || []).map((m, i) => <p key={i}>✓ {m.item || m}{m.evidence ? ` — ${m.evidence}` : ""}</p>)}
        </div>
      </Card>
      <Card>
        <H>C. Missing or Unclear Skills</H>
        <p className="mb-3 text-xs text-gray-500">“Missing” = not mentioned at all. “Unclear” = you may have it, but your resume does not show evidence — add it only if it is true.</p>
        <div className="space-y-2" data-testid="an-missing">
          {(res.missing_skills || []).map((m, i) => (
            <div key={i} className="text-sm">
              <div className="flex items-center gap-2"><Badge label={m.status === "unclear" ? "Unclear" : "Missing"} color={m.status === "unclear" ? "warning" : "error"} /><span className="font-semibold">{m.item}</span></div>
              {m.note ? <p className="mt-0.5 text-xs text-gray-500">{m.note}</p> : null}
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <H>D. Experience & Qualification Match</H>
        {["summary", "experience", "education", "certifications"].map((k) => res.experience_match?.[k] ? (
          <p key={k} className="mb-2 text-sm text-gray-700"><b>{k[0].toUpperCase() + k.slice(1)}: </b>{res.experience_match[k]}</p>
        ) : null)}
      </Card>
      <Card>
        <H>E. Keyword Analysis</H>
        <p className="mb-1 text-xs font-bold uppercase text-gray-400">Missing from your resume</p>
        <BulletList items={res.keyword_analysis?.missing} data-testid="an-kw-missing" />
        <p className="mb-1 mt-3 text-xs font-bold uppercase text-gray-400">Already present</p>
        <BulletList items={res.keyword_analysis?.present} />
      </Card>
      <Card>
        <H>F. ATS Readiness Check</H>
        <div className="space-y-2.5">
          {(res.ats_check || []).map((a, i) => (
            <div key={i} className="text-sm">
              <div className="flex items-center gap-2"><Badge label={(a.status || "ok").toUpperCase()} color={ST[a.status] || "info"} /><span className="font-semibold">{a.area}</span></div>
              <p className="mt-0.5 text-xs text-gray-500">{a.note}</p>
            </div>
          ))}
        </div>
      </Card>
      <Card>
        <H>G. Improvement Suggestions</H>
        {[["summary", "Professional summary"], ["skills", "Skills section"], ["experience", "Experience descriptions"], ["achievements", "Achievements"]].map(([k, l]) => (
          <div key={k} className="mb-3"><p className="mb-1 text-xs font-bold uppercase text-gray-400">{l}</p><BulletList items={res.suggestions?.[k]} /></div>
        ))}
      </Card>
      <div className="lg:col-span-2">
        <AiDisclaimer text="The match score is an estimate based only on the text provided. Different companies use different ATS systems and criteria, so no tool can guarantee your resume will pass every ATS. Never add skills or experience you do not have." />
      </div>
    </div>
  );
}

export default function Analyser() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const id = params.get("id");
  const { data: usage } = useCareerUsage();
  const invalidate = useInvalidateUsage();
  const [resume, setResume] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(null);
  const [analysis, setAnalysis] = useState(null);

  useQuery({
    queryKey: ["analysis", id],
    enabled: !!id,
    queryFn: async () => {
      const r = await api(`/career/analyses/${id}`);
      setAnalysis(r.analysis);
      return r;
    },
  });
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
  const run = () => guard("run", async () => {
    const r = await api("/career/analyse", { method: "POST", body: { resume_text: resume, jd_text: jd } });
    setAnalysis(r.analysis);
    await invalidate();
    if (r.reused) notify("Showing your saved analysis for the same resume & JD");
  });
  const improve = () => guard("improve", async () => {
    const r = await api(`/career/analyses/${analysis.analysis_id}/improve`, { method: "POST" });
    await invalidate();
    navigate(`/career/resume/${r.resume.resume_id}`);
  });
  const res = analysis?.result;

  return (
    <Page>
      <PageHeader title="Resume Analyser" subtitle="Compare your resume against a job description and get a match score." />
      <ConsentGate>
        {!res ? (
          <div className="space-y-5">
            <div className="grid gap-5 lg:grid-cols-2">
              <Card>
                <p className="label">Box 1: Paste Your Resume</p>
                <textarea value={resume} onChange={(e) => setResume(e.target.value)} maxLength={15000} className={`${areaCls} min-h-[360px]`}
                  placeholder="Copy the full text of your resume and paste it here" data-testid="an-resume" />
              </Card>
              <Card>
                <p className="label">Box 2: Paste Job Description</p>
                <textarea value={jd} onChange={(e) => setJd(e.target.value)} maxLength={12000} className={`${areaCls} min-h-[360px]`}
                  placeholder="Paste the complete job description" data-testid="an-jd" />
              </Card>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <Button size="lg" title="Analyse Resume" loading={busy === "run"} onClick={run} data-testid="an-submit" />
              <UsagePill tool="resume_analyser" usage={usage} />
            </div>
            {busy === "run" ? <p className="muted">Analysing… this usually takes 20–40 seconds.</p> : null}
            <AiDisclaimer />
          </div>
        ) : (
          <div className="space-y-5">
            <AnalysisResult res={res} />
            <Card className="space-y-3">
              <H>H. Improved Resume</H>
              <p className="text-sm text-gray-600">Generate an improved, ATS-friendly version using only your genuine experience, skills and qualifications. You can edit it and download as PDF or DOCX.</p>
              <UsagePill tool="resume_builder" usage={usage} />
              <Button title={analysis.improved_resume_id ? "Open Improved Resume" : "Generate Improved Resume"} loading={busy === "improve"} onClick={improve} data-testid="an-improve" />
            </Card>
            <Button variant="outline" title="Analyse Another" data-testid="an-reset"
              onClick={() => { setAnalysis(null); if (id) setParams({}); }} />
          </div>
        )}
      </ConsentGate>
    </Page>
  );
}
