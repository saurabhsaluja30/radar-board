import React, { useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic, Square, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/constants";
import { Badge, Button, Card, Chip, ChipRow, EmptyState, errMsg, Input, notify, PageHeader, Spinner } from "@/components/kit";
import { AiDisclaimer, areaCls, BulletList, ConsentGate, ScoreRing, UsagePill, useCareerUsage, useInvalidateUsage } from "@/components/career";
import { Page } from "@/components/Layout";

const LEVELS = ["Fresher", "0-2 years", "3-5 years", "6-10 years", "10+ years"];
const TYPES = ["HR Interview", "Technical Interview", "Functional/Role-Specific Interview", "Managerial Interview", "Behavioural Interview", "Complete Mock Interview"];
const DIFFS = ["Beginner", "Intermediate", "Advanced"];

export function InterviewSetup() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const jobId = params.get("jobId");
  const { data: usage } = useCareerUsage();
  const invalidate = useInvalidateUsage();
  const [form, setForm] = useState({
    job_title: "", company: "", jd_text: "", industry: "", experience_level: "", interview_type: "",
    difficulty: "Intermediate", num_questions: 5, feedback_mode: "each",
  });
  const [prefillNote, setPrefillNote] = useState("");
  const [loading, setLoading] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  useEffect(() => {
    if (!jobId) return;
    api(`/career/job-prefill/${jobId}`).then((p) => {
      setForm((f) => ({ ...f, job_title: p.job_title || "", company: p.company || "", industry: p.industry || "", jd_text: p.jd_text || "" }));
      setPrefillNote(p.full_jd
        ? `Pre-filled from JobRadar listing${p.experience_required ? ` · Experience: ${p.experience_required}` : ""}. Now choose the interview type.`
        : "Pre-filled with the public job preview. Members get the full job description — you can also paste it below.");
    }).catch(() => {});
  }, [jobId]);

  const start = async () => {
    if (loading) return;
    if (!form.experience_level || !form.interview_type) return notify("Select experience level and interview type", "error");
    setLoading(true);
    try {
      const r = await api("/career/interviews", { method: "POST", body: { ...form, job_id: jobId || null } });
      await invalidate();
      navigate(`/career/interview/${r.session.session_id}`, { replace: true });
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setLoading(false);
    }
  };
  const Group = ({ k, options, label }) => (
    <ChipRow label={label}>
      {options.map((o) => <Chip key={String(o)} label={String(o)} selected={form[k] === o} onClick={() => set(k, o)} data-testid={`iv-${k}-${o}`} />)}
    </ChipRow>
  );

  return (
    <Page>
      <PageHeader title="AI Interview Coach" subtitle="Practise role-specific interviews and receive instant feedback."
        right={<Button variant="ghost" title="View Past Sessions" onClick={() => navigate("/career/history?tab=interviews")} data-testid="iv-history" />} />
      <ConsentGate>
        {prefillNote ? <Card className="mb-5 bg-brand-mist" data-testid="iv-prefill-note"><p className="text-sm text-brand-ink">{prefillNote}</p></Card> : null}
        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="space-y-4">
            <p className="h-sec">Interview setup</p>
            <Input label="Target job title / designation *" value={form.job_title} onChange={(e) => set("job_title", e.target.value)} data-testid="iv-title" />
            <Input label="Company name (optional)" value={form.company} onChange={(e) => set("company", e.target.value)} data-testid="iv-company" />
            <div>
              <span className="label">Job description *</span>
              <textarea value={form.jd_text} onChange={(e) => set("jd_text", e.target.value)} maxLength={12000} className={areaCls} placeholder="Paste the job description" data-testid="iv-jd" />
            </div>
          </Card>
          <Card className="space-y-5">
            <Group k="experience_level" options={LEVELS} label="Experience level *" />
            <Group k="interview_type" options={TYPES} label="Interview type *" />
            <Group k="difficulty" options={DIFFS} label="Difficulty" />
            <Group k="num_questions" options={[5, 10, 15]} label="Number of questions" />
            <ChipRow label="Feedback">
              <Chip label="After every answer" selected={form.feedback_mode === "each"} onClick={() => set("feedback_mode", "each")} data-testid="iv-fb-each" />
              <Chip label="Full report at the end" selected={form.feedback_mode === "end"} onClick={() => set("feedback_mode", "end")} data-testid="iv-fb-end" />
            </ChipRow>
          </Card>
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-4">
          <Button size="lg" title="Start Interview Practice" loading={loading} onClick={start} data-testid="iv-start" />
          <UsagePill tool="interview_coach" usage={usage} />
          {loading ? <p className="muted">Preparing role-specific questions…</p> : null}
        </div>
        <div className="mt-6"><AiDisclaimer /></div>
      </ConsentGate>
    </Page>
  );
}

const DIMS = [["relevance", "Relevance"], ["role_knowledge", "Role knowledge"], ["structure_clarity", "Structure & clarity"],
  ["specific_examples", "Specific examples"], ["communication", "Communication"], ["completeness", "Completeness"]];

function FeedbackCard({ q, index }) {
  const f = q.feedback;
  return (
    <Card className="space-y-4" data-testid="iv-feedback">
      <p className="h-sec">Feedback on Q{index + 1}</p>
      <div className="grid items-center gap-6 md:grid-cols-[140px_1fr]">
        <ScoreRing score={f.score ?? 0} />
        {f.dimensions ? (
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
            {DIMS.map(([k, l]) => <p key={k} className="flex justify-between"><span className="text-gray-500">{l}</span><b>{f.dimensions[k] ?? "—"}/10</b></p>)}
          </div>
        ) : null}
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div><p className="label">What you did well</p><BulletList items={f.did_well} /></div>
        {f.missing ? <div><p className="label">What was missing</p><BulletList items={f.missing} /></div> : null}
        <div><p className="label">How to improve</p><BulletList items={f.how_to_improve} /></div>
      </div>
      {f.star_tip ? <p className="text-sm text-gray-700">⭐ STAR tip: {f.star_tip}</p> : null}
      {f.stronger_structure ? (
        <div className="rounded-xl bg-gray-50 p-4">
          <p className="text-xs font-bold uppercase text-gray-400">EXAMPLE — stronger answer structure (template only)</p>
          <p className="mt-1 whitespace-pre-line text-sm text-gray-700">{f.stronger_structure}</p>
        </div>
      ) : null}
      {f.follow_up ? <p className="text-sm font-semibold text-brand-ink">Follow-up question: {f.follow_up}</p> : null}
    </Card>
  );
}

const REPORT_LIST = [["strengths", "Strengths"], ["areas_for_improvement", "Areas for improvement"], ["knowledge_gaps", "Knowledge gaps identified"],
  ["answered_well", "Questions answered well"], ["needs_preparation", "Questions requiring more preparation"], ["topics_to_study", "Suggested topics to study"],
  ["practice_questions", "Recommended practice questions"], ["preparation_plan", "Your personalised preparation plan"]];

function Report({ session }) {
  const r = session.report || {};
  if (r.empty) return <Card><p>{r.summary}</p></Card>;
  return (
    <div className="space-y-5" data-testid="iv-report">
      <Card className="grid items-center gap-6 md:grid-cols-[200px_1fr]">
        <ScoreRing score={r.overall_score ?? 0} label="Overall performance (estimate)" />
        {r.summary ? <p className="text-gray-700">{r.summary}</p> : null}
      </Card>
      <Card>
        <p className="h-sec mb-3">Individual question scores</p>
        {session.questions.map((q, i) => (
          <div key={i} className="flex justify-between gap-4 border-b border-gray-100 py-2 text-sm last:border-0">
            <span className="line-clamp-2 text-gray-700">Q{i + 1}. {q.question}</span>
            <b>{q.status === "answered" ? `${q.feedback?.score ?? "—"}` : "Skipped"}</b>
          </div>
        ))}
      </Card>
      {r.communication_feedback ? <Card><p className="h-sec mb-2">Communication & answer structure</p><p className="text-sm text-gray-700">{r.communication_feedback}</p></Card> : null}
      <div className="grid gap-5 md:grid-cols-2">
        {REPORT_LIST.map(([k, l]) => (r[k]?.length ? <Card key={k}><p className="h-sec mb-2">{l}</p><BulletList items={r[k]} /></Card> : null))}
      </div>
      <AiDisclaimer text={r.disclaimer} />
    </div>
  );
}

const Recognition = typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

// Speak an answer: the browser turns speech into text in the answer box (Chrome and Edge). No audio is sent to JobRadar.
function VoiceButton({ onText, disabled }) {
  const rec = useRef(null);
  const [on, setOn] = useState(false);
  useEffect(() => () => rec.current?.abort(), []);
  if (!Recognition) return <p className="text-xs text-gray-400" data-testid="iv-voice-unsupported">Voice answers work in Chrome and Edge.</p>;
  const start = () => {
    const r = new Recognition();
    r.lang = "en-IN";
    r.continuous = true;
    r.interimResults = false;
    r.onresult = (e) => {
      const text = Array.from(e.results).slice(e.resultIndex).filter((x) => x.isFinal).map((x) => x[0].transcript).join(" ");
      if (text.trim()) onText(text.trim());
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed") notify("Allow microphone access in your browser to answer by voice.", "error");
      else if (e.error !== "no-speech" && e.error !== "aborted") notify("Voice input stopped. You can type instead.", "error");
    };
    r.onend = () => setOn(false);
    rec.current = r;
    r.start();
    setOn(true);
  };
  const stop = () => rec.current?.stop();
  return (
    <Button variant={on ? "danger" : "outline"} size="sm" disabled={disabled && !on} icon={on ? <Square className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
      title={on ? "Stop speaking" : "Answer by voice"} onClick={on ? stop : start} data-testid="iv-voice" />
  );
}

const READY_COLOR = { "Interview ready": "success", "Nearly ready": "warning", "Keep practising": "error" };

export function ReadinessReport() {
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["readiness"], queryFn: () => api("/career/readiness") });
  if (!data) return <Spinner />;
  if (!data.sessions) {
    return <Card data-testid="readiness-empty"><p className="h-sec">Interview readiness</p><p className="muted mt-1">Complete a mock interview to see your readiness report.</p>
      <Button className="mt-3" size="sm" title="Start Practising" onClick={() => navigate("/career/interview")} /></Card>;
  }
  const Bar = ({ label, score, sub }) => (
    <div>
      <div className="flex justify-between text-sm"><span className="font-semibold">{label}</span><b className="text-brand">{score}</b></div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-brand-soft"><div className="h-full bg-brand" style={{ width: `${score}%` }} /></div>
      {sub ? <p className="mt-0.5 text-[11px] text-gray-400">{sub}</p> : null}
    </div>
  );
  return (
    <Card className="space-y-5" data-testid="readiness-report">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="h-sec">Interview readiness</p>
          <p className="muted text-sm">From your last {Math.min(data.sessions, 5)} completed practice session{data.sessions === 1 ? "" : "s"}, with recent ones counting more.</p>
        </div>
        <div className="text-right">
          <p className="text-3xl font-extrabold text-brand" data-testid="readiness-score">{data.score}<span className="text-base text-gray-400">/100</span></p>
          <Badge label={data.level} color={READY_COLOR[data.level] || "info"} />
        </div>
      </div>
      {data.trend.length > 1 ? (
        <div className="flex h-24 items-end gap-3" data-testid="readiness-trend">
          {data.trend.map((t) => (
            <div key={t.session_id} className="flex h-full flex-1 flex-col items-center justify-end gap-1" title={`${t.job_title} · ${t.interview_type} · ${formatDate(t.at)}`}>
              <span className="text-[11px] font-bold">{t.score}</span>
              <div className="w-full rounded-t-md bg-brand" style={{ height: `${Math.max(4, t.score) * 0.8}%` }} />
            </div>
          ))}
        </div>
      ) : null}
      <div className="grid gap-6 md:grid-cols-2">
        {data.dimensions.length ? <div className="space-y-3"><p className="text-xs font-bold uppercase text-gray-400">By skill</p>{data.dimensions.map((d) => <Bar key={d.key} label={d.label} score={d.score} />)}</div> : null}
        {data.by_category.length ? <div className="space-y-3"><p className="text-xs font-bold uppercase text-gray-400">By question type</p>{data.by_category.map((c) => <Bar key={c.category} label={c.category} score={c.score} sub={`${c.answers} answer${c.answers === 1 ? "" : "s"}`} />)}</div> : null}
      </div>
      {data.focus.length ? <div><p className="font-bold">What to improve next</p><BulletList items={data.focus} /></div> : null}
      {data.strengths.length ? <div><p className="font-bold">Your strengths</p><BulletList items={data.strengths} /></div> : null}
      <p className="text-[11px] text-gray-400">{data.confidence_note} {data.disclaimer}</p>
    </Card>
  );
}

export function InterviewSession() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, refetch } = useQuery({ queryKey: ["interview", id], queryFn: () => api(`/career/interviews/${id}`) });
  const [session, setSession] = useState(null);
  const [idx, setIdx] = useState(0);
  const [answer, setAnswer] = useState("");
  const [hint, setHint] = useState(null);
  const [busy, setBusy] = useState(null);
  const [fbFor, setFbFor] = useState(null);
  const [spoken, setSpoken] = useState(false);

  useEffect(() => {
    if (data?.session) {
      setSession(data.session);
      const next = data.session.questions.findIndex((q) => q.status === "pending");
      setIdx(next === -1 ? data.session.questions.length : next);
    }
  }, [data]);
  if (!session) return <Spinner />;

  const total = session.questions.length;
  const done = session.status !== "in_progress";
  const call = async (key, fn) => {
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
  const goNext = (s) => {
    setSession(s);
    setAnswer("");
    setSpoken(false);
    setHint(null);
    const next = s.questions.findIndex((q) => q.status === "pending");
    setFbFor(s.feedback_mode === "each" && s.questions[idx]?.feedback && s.questions[idx].status === "answered" ? idx : null);
    setIdx(next === -1 ? total : next);
  };
  const submit = () => call("submit", async () => goNext((await api(`/career/interviews/${id}/answer`, { method: "POST", body: { index: idx, answer, mode: spoken ? "voice" : "typed" } })).session));
  const skip = () => call("skip", async () => goNext((await api(`/career/interviews/${id}/skip`, { method: "POST", body: { index: idx } })).session));
  const getHint = () => call("hint", async () => setHint((await api(`/career/interviews/${id}/hint`, { method: "POST", body: { index: idx } })).hint));
  const endNow = () => call("end", async () => {
    const r = await api(`/career/interviews/${id}/end`, { method: "POST" });
    setSession(r.session);
    setFbFor(null);
    await refetch();
  });
  const q = session.questions[idx];
  const fbQ = fbFor !== null ? session.questions[fbFor] : null;

  return (
    <Page>
      <PageHeader title={done ? "Interview Report" : `Question ${Math.min(idx + 1, total)} of ${total}`}
        subtitle={`${session.job_title}${session.company ? ` · ${session.company}` : ""} · ${session.interview_type} · ${session.difficulty}`} />
      {!done ? (
        <div className="mb-6 h-2 overflow-hidden rounded-full bg-brand-soft">
          <div className="h-full bg-brand transition-[width] duration-500" style={{ width: `${(Math.min(idx, total) / total) * 100}%` }} />
        </div>
      ) : null}
      <div className="space-y-5">
        {fbQ?.feedback ? <FeedbackCard q={fbQ} index={fbFor} /> : null}
        {done ? <Report session={session} /> : q ? (
          <Card className="space-y-4 p-8" data-testid="iv-question-card">
            <Badge label={q.category || "Question"} color="brand" />
            <p className="text-xl font-bold leading-snug text-gray-900" data-testid="iv-question-text">{q.question}</p>
            {hint ? <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800" data-testid="iv-hint">💡 {hint}</p> : null}
            <textarea value={answer} onChange={(e) => setAnswer(e.target.value)} maxLength={5000} className={areaCls}
              placeholder="Type or speak your answer. Use real examples from your own experience." data-testid="iv-answer" />
            <div className="flex flex-wrap items-center gap-2">
              <VoiceButton disabled={!!busy} onText={(t) => { setSpoken(true); setAnswer((a) => (a.trim() ? `${a.trimEnd()} ${t}` : t)); }} />
              <span className="text-xs text-gray-400">Check the text before submitting: speech recognition can mishear words.</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button title="Submit Answer" loading={busy === "submit"} disabled={!!busy || answer.trim().length < 5} onClick={submit} data-testid="iv-submit" />
              <Button variant="outline" size="sm" title="Get Hint" loading={busy === "hint"} disabled={!!busy} onClick={getHint} data-testid="iv-hint-btn" />
              <Button variant="outline" size="sm" title="Skip Question" loading={busy === "skip"} disabled={!!busy} onClick={skip} data-testid="iv-skip" />
              <div className="flex-1" />
              <Button variant="ghost" title="End Interview" loading={busy === "end"} disabled={!!busy} onClick={endNow} data-testid="iv-end" />
            </div>
            {busy === "submit" && session.feedback_mode === "each" ? <p className="muted">Evaluating your answer…</p> : null}
          </Card>
        ) : (
          <Card className="space-y-3 p-8 text-center">
            <p className="text-xl font-extrabold">All questions completed 🎉</p>
            <p className="muted">Generate your personalised interview report.</p>
            <Button title="View Final Report" loading={busy === "end"} onClick={endNow} data-testid="iv-finish" />
            {busy === "end" ? <p className="muted">Preparing your report…</p> : null}
          </Card>
        )}
        {done ? <Button variant="outline" title="Start a New Practice Session" onClick={() => navigate("/career/interview", { replace: true })} data-testid="iv-new" /> : null}
      </div>
    </Page>
  );
}

function Row({ title, sub, right, onClick, onDelete, testId }) {
  return (
    <Card className="flex items-center gap-4 py-4" data-testid={testId}>
      <button onClick={onClick} className="min-w-0 flex-1 text-left">
        <p className="truncate font-bold text-gray-900 hover:text-brand">{title}</p>
        <p className="text-sm text-gray-500">{sub}</p>
      </button>
      {right}
      <button onClick={onDelete} className="rounded-lg p-2 hover:bg-red-50" data-testid={`${testId}-delete`}><Trash2 className="h-4 w-4 text-red-600" /></button>
    </Card>
  );
}

export function CareerHistory() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const [tab, setTab] = useState(params.get("tab") || "resumes");
  const resumes = useQuery({ queryKey: ["career", "resumes"], queryFn: () => api("/career/resumes") });
  const analyses = useQuery({ queryKey: ["career", "analyses"], queryFn: () => api("/career/analyses") });
  const sessions = useQuery({ queryKey: ["career", "interviews"], queryFn: () => api("/career/interviews") });
  const del = async (path, label) => {
    if (!window.confirm(`Delete this ${label}? This cannot be undone.`)) return;
    try {
      await api(path, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: ["career"] });
      notify("Deleted", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const rs = resumes.data?.resumes || [];
  const an = analyses.data?.analyses || [];
  const ss = sessions.data?.sessions || [];
  const scored = ss.filter((s) => s.overall_score != null).slice(0, 6).reverse();

  return (
    <Page>
      <PageHeader title="My Career Data" />
      <div className="mb-6 flex gap-2">
        <Chip label="Resumes" selected={tab === "resumes"} onClick={() => setTab("resumes")} data-testid="hist-tab-resumes" />
        <Chip label="Analysis Reports" selected={tab === "analyses"} onClick={() => setTab("analyses")} data-testid="hist-tab-analyses" />
        <Chip label="Interviews" selected={tab === "interviews"} onClick={() => setTab("interviews")} data-testid="hist-tab-interviews" />
      </div>
      <div className="max-w-4xl space-y-3">
        {tab === "resumes" ? (
          <>
            <Button size="sm" title="Create New Resume" onClick={() => navigate("/career/resume-builder")} data-testid="hist-new-resume" />
            {rs.length === 0 ? <EmptyState title="No saved resumes yet" data-testid="hist-resumes-empty" /> : null}
            {rs.map((r) => (
              <Row key={r.resume_id} testId={`hist-resume-${r.resume_id}`} title={r.title}
                sub={`${r.resume_type === "fresher" ? "Fresher" : "Experienced"} · updated ${formatDate(r.updated_at)}`}
                onClick={() => navigate(`/career/resume/${r.resume_id}`)} onDelete={() => del(`/career/resumes/${r.resume_id}`, "resume")} />
            ))}
          </>
        ) : null}
        {tab === "analyses" ? (
          <>
            <Button size="sm" title="New Analysis" onClick={() => navigate("/career/analyser")} data-testid="hist-new-analysis" />
            {an.length === 0 ? <EmptyState title="No analysis reports yet" data-testid="hist-analyses-empty" /> : null}
            {an.map((a) => (
              <Row key={a.analysis_id} testId={`hist-analysis-${a.analysis_id}`} title={a.job_label} sub={formatDate(a.created_at)}
                right={<Badge label={`${a.match_score ?? "—"}/100`} color="brand" />}
                onClick={() => navigate(`/career/analyser?id=${a.analysis_id}`)} onDelete={() => del(`/career/analyses/${a.analysis_id}`, "report")} />
            ))}
          </>
        ) : null}
        {tab === "interviews" ? (
          <>
            <Button size="sm" title="New Practice Session" onClick={() => navigate("/career/interview")} data-testid="hist-new-interview" />
            {scored.length ? <ReadinessReport /> : null}
            {ss.length === 0 ? <EmptyState title="No interview sessions yet" data-testid="hist-interviews-empty" /> : null}
            {ss.map((s) => (
              <Row key={s.session_id} testId={`hist-interview-${s.session_id}`} title={s.job_title} sub={`${s.interview_type} · ${formatDate(s.created_at)}`}
                right={s.overall_score != null ? <Badge label={`${s.overall_score}/100`} color="brand" /> : <Badge label={s.status === "in_progress" ? "In progress" : "Ended"} color="warning" />}
                onClick={() => navigate(`/career/interview/${s.session_id}`)} onDelete={() => del(`/career/interviews/${s.session_id}`, "interview session")} />
            ))}
          </>
        ) : null}
        <div className="pt-6">
          <Button variant="ghost" title="Delete All My Career Tools Data" data-testid="hist-delete-all"
            onClick={() => del("/career/data", "Career Tools data (all resumes, reports and interviews)")} />
        </div>
      </div>
    </Page>
  );
}
