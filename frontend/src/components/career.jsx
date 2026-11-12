import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileText, MessagesSquare, ShieldCheck, Target } from "lucide-react";
import { api, BACKEND_URL } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button, Card } from "@/components/kit";

export const TOOL_KIND = { resume_builder: "resume_generation", resume_analyser: "resume_analysis", interview_coach: "interview_sessions" };
const KIND_LABEL = { resume_generation: "AI resume generations", resume_analysis: "resume analyses", interview_sessions: "interview sessions" };

export function useCareerUsage() {
  const { user } = useAuth();
  return useQuery({ queryKey: ["career-usage", user?.user_id], queryFn: () => api("/career/usage"), enabled: !!user && user.role === "candidate" });
}

export function useInvalidateUsage() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["career-usage"] });
}

export function UsagePill({ tool, usage }) {
  if (!usage) return null;
  const u = usage.usage?.[TOOL_KIND[tool]];
  const t = usage.tools?.[tool];
  if (t && !t.accessible) return <p className="text-xs font-semibold text-red-600" data-testid={`usage-${tool}`}>{t.reason}</p>;
  return (
    <p className="text-xs font-semibold text-brand-ink" data-testid={`usage-${tool}`}>
      {u?.remaining ?? 0} of {u?.limit ?? 0} {KIND_LABEL[TOOL_KIND[tool]]} left · {usage.period_label || `resets every ${usage.period_days} days`}
    </p>
  );
}

export function ConsentGate({ children }) {
  const { data, isLoading } = useCareerUsage();
  const invalidate = useInvalidateUsage();
  const [saving, setSaving] = React.useState(false);
  if (isLoading || !data) return <>{children}</>;
  if (!data.ai_configured) {
    return (
      <Card data-testid="ai-not-configured">
        <p className="font-extrabold">AI service not configured</p>
        <p className="muted mt-1">The AI provider is not configured on the server, so Career Tools cannot run right now. Please contact support.</p>
      </Card>
    );
  }
  if (data.ai_consent) return <>{children}</>;
  return (
    <Card className="mx-auto max-w-2xl space-y-4 p-8" data-testid="ai-consent-card">
      <ShieldCheck className="h-8 w-8 text-brand" />
      <p className="text-xl font-extrabold">Before you start: AI processing & privacy</p>
      <p className="text-sm leading-relaxed text-gray-600">
        Career Tools send the text you enter (resume details, job descriptions and interview answers) securely from our server to an AI provider to generate results. Your resumes, reports and answers are private to your account — never shown to other candidates — and you can delete them at any time.
      </p>
      <p className="text-sm leading-relaxed text-gray-600">
        AI results are estimates for guidance only and never guarantee shortlisting, interviews or employment. Only enter information that is true about you.
      </p>
      <Button title="I Agree — Continue" loading={saving} data-testid="ai-consent-accept"
        onClick={async () => {
          setSaving(true);
          try {
            await api("/career/consent", { method: "POST" });
            await invalidate();
          } finally {
            setSaving(false);
          }
        }} />
    </Card>
  );
}

export const AiDisclaimer = ({ text }) => (
  <p className="rounded-xl bg-gray-50 p-4 text-xs leading-relaxed text-gray-500" data-testid="ai-disclaimer">
    {text || "AI-generated scores and suggestions are estimates for practice and guidance only. They are not an official employer assessment and do not guarantee ATS success, interviews or employment."}
  </p>
);

const TOOLS = [
  { key: "resume_builder", title: "ATS Resume Builder", desc: "Create a professional, ATS-friendly resume for fresher or experienced roles.", to: "/career/resume-builder", Icon: FileText },
  { key: "resume_analyser", title: "Resume Analyser", desc: "Compare your resume against a job description and get a match score.", to: "/career/analyser", Icon: Target },
  { key: "interview_coach", title: "AI Interview Coach", desc: "Practise role-specific interviews and receive instant feedback.", to: "/career/interview", Icon: MessagesSquare },
];

export function CareerToolsCards({ showHub = true }) {
  const navigate = useNavigate();
  const { data } = useCareerUsage();
  return (
    <div data-testid="career-tools-cards">
      <div className="grid gap-4 md:grid-cols-3">
        {TOOLS.map(({ key, title, desc, to, Icon }) => (
          <Card key={key} className="flex flex-col gap-3" data-testid={`career-card-${key}`}>
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft"><Icon className="h-5 w-5 text-brand" /></span>
            <p className="font-extrabold text-gray-900">{title}</p>
            <p className="flex-1 text-sm text-gray-500">{desc}</p>
            <UsagePill tool={key} usage={data} />
            <Button size="sm" title="Start Now" onClick={() => navigate(to)} data-testid={`career-start-${key}`} />
          </Card>
        ))}
      </div>
      {showHub ? (
        <button onClick={() => navigate("/career/history")} className="mt-4 flex items-center gap-1 text-sm font-bold text-brand hover:underline" data-testid="career-history-link">
          My saved resumes, reports & interviews <ChevronRight className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}

export function BulletList({ items, ...rest }) {
  if (!items || items.length === 0) return <p className="text-sm text-gray-400">—</p>;
  return (
    <ul className="space-y-1.5 text-sm text-gray-700" {...rest}>
      {items.map((it, i) => <li key={i}>• {typeof it === "string" ? it : it?.item || JSON.stringify(it)}</li>)}
    </ul>
  );
}

export function ScoreRing({ score, label }) {
  const c = score >= 70 ? "#059669" : score >= 45 ? "#D97706" : "#DC2626";
  return (
    <div className="flex flex-col items-center" data-testid="score-ring">
      <div className="flex h-28 w-28 flex-col items-center justify-center rounded-full border-[8px]" style={{ borderColor: c }}>
        <span className="text-3xl font-extrabold" style={{ color: c }}>{score}</span>
        <span className="text-xs text-gray-400">/100</span>
      </div>
      {label ? <p className="mt-2 text-sm font-semibold text-gray-600">{label}</p> : null}
    </div>
  );
}

export async function downloadResume(resumeId, format) {
  const res = await api(`/career/resumes/${resumeId}/download-link`, { method: "POST", body: { format } });
  window.open(`${BACKEND_URL}${res.path}`, "_blank");
}

export const areaCls = "field min-h-[200px] resize-y text-sm";
