import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CheckSquare, Square } from "lucide-react";
import { api, uploadForm } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { EXPERIENCE_RANGES, INDUSTRIES, INDUSTRIES_WITH_OTHER, INDUSTRY_SHORT, PREF_WORK_MODES } from "@/lib/constants";
import { Button, Chip, ChipRow, Input, notify } from "@/components/kit";
import { BrandLogo } from "@/components/Layout";
import { OpportunityNotice } from "@/components/Membership";

const GoogleIcon = () => (
  <svg viewBox="0 0 24 24" className="h-4 w-4"><path fill="currentColor" d="M21.35 11.1H12v2.98h5.35c-.23 1.4-1.66 4.1-5.35 4.1-3.22 0-5.85-2.67-5.85-5.96S8.78 6.26 12 6.26c1.83 0 3.06.78 3.76 1.45l2.56-2.47C16.68 3.7 14.55 2.75 12 2.75 6.9 2.75 2.75 6.9 2.75 12s4.15 9.25 9.25 9.25c5.34 0 8.88-3.75 8.88-9.04 0-.6-.07-1.07-.15-1.53z" /></svg>
);

export function GoogleButton({ testId }) {
  const { googleLogin } = useAuth();
  return <Button full variant="secondary" title="Continue with Google" icon={<GoogleIcon />} onClick={googleLogin} data-testid={testId} />;
}

export const OrLine = () => (
  <div className="my-5 flex items-center gap-3 text-xs font-semibold text-gray-400"><span className="h-px flex-1 bg-gray-200" />or<span className="h-px flex-1 bg-gray-200" /></div>
);

function AuthFrame({ children, side }) {
  return (
    <div className="grid min-h-[calc(100vh-72px)] lg:grid-cols-[1fr_1.1fr]">
      <div className="radar-grid hidden flex-col justify-between bg-brand-ink p-14 lg:flex">
        <BrandLogo dark />
        <div>
          <p className="text-4xl font-extrabold leading-tight text-white">Stop Searching.<br />Start Discovering.</p>
          <p className="mt-4 max-w-sm text-violet-200">{side}</p>
        </div>
        <p className="text-xs text-violet-300">Membership does not guarantee an interview, job offer or employment.</p>
      </div>
      <div className="flex justify-center overflow-y-auto px-6 py-14">
        <div className="fade-up w-full max-w-md">{children}</div>
      </div>
    </div>
  );
}

export function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!email || !password) return notify("Enter email and password", "error");
    setLoading(true);
    try {
      await login(email.trim(), password);
      notify("Welcome back!", "success");
      navigate("/");
    } catch (e) {
      notify(e.message || "Login failed", "error");
    } finally {
      setLoading(false);
    }
  };
  return (
    <AuthFrame side="Login to access curated jobs and your membership.">
      <h1 className="h-page">Welcome back</h1>
      <p className="muted mt-2">Login to access curated jobs and your membership.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" data-testid="login-email" />
        <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Your password" data-testid="login-password" />
        <div className="text-right"><Link to="/auth/forgot" className="text-sm font-bold text-brand hover:underline" data-testid="forgot-link">Forgot password?</Link></div>
        <Button full type="submit" title="Login" loading={loading} data-testid="login-submit" />
      </form>
      <OrLine />
      <GoogleButton testId="login-google" />
      <p className="mt-6 text-center text-sm text-gray-500">
        New to JobRadar? <Link to="/auth/register" className="font-bold text-brand hover:underline" data-testid="go-register">Create an account</Link>
      </p>
      <p className="mt-3 text-center text-sm"><Link to="/admin" className="font-semibold text-gray-400 hover:text-brand" data-testid="login-admin-link">Admin login</Link></p>
    </AuthFrame>
  );
}

const EMPTY_REG = {
  full_name: "", email: "", mobile: "", password: "", confirm_password: "", industry: "", current_designation: "",
  current_salary: "", preferred_location: "", preferred_work_mode: "", preferred_designation: "", preferred_experience: "",
};

export function Register() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const [form, setForm] = useState(EMPTY_REG);
  const [pref, setPref] = useState([]);
  const [consent, setConsent] = useState(false);
  const [talent, setTalent] = useState(false);
  const [resume, setResume] = useState(null);
  const [resumeCfg, setResumeCfg] = useState(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => { api("/resume/config", { auth: false }).then(setResumeCfg).catch(() => {}); }, []);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const bind = (k) => ({ value: form[k], onChange: (e) => set(k, e.target.value) });
  const toggle = (i) => setPref((p) => (p.includes(i) ? p.filter((x) => x !== i) : [...p, i]));

  const submit = async () => {
    if (!form.full_name || !form.email || !form.mobile || !form.password) return notify("Please fill all required fields", "error");
    if (!form.industry || !form.current_designation || !form.current_salary || !form.preferred_location || !form.preferred_work_mode)
      return notify("Complete Industry, Designation, Salary, Preferred Location & Work Mode", "error");
    if (form.password !== form.confirm_password) return notify("Passwords do not match", "error");
    if (!consent) return notify("Please accept the Terms & Privacy Policy", "error");
    if (resume && !/\.(pdf|docx)$/i.test(resume.name)) return notify("Resume must be a PDF or Word (.docx) file", "error");
    if (resume && resumeCfg && resume.size > resumeCfg.max_mb * 1024 * 1024) return notify(`Resume must be under ${resumeCfg.max_mb} MB`, "error");
    setLoading(true);
    try {
      await register({ ...form, preferred_industries: pref, email: form.email.trim(), consent, talent_db_consent: talent });
      notify("Account created!", "success");
      // The resume uploads after the account exists, so a slow or failed upload never blocks registration.
      if (resume) {
        try {
          await uploadForm("/resume/upload", resume);
          notify("Resume uploaded — review the details on your profile", "success");
        } catch (e) {
          notify(`Account created, but the resume didn't upload: ${e.message}. You can upload it from your profile.`, "error");
        }
      }
      navigate(resume ? "/profile" : "/");
    } catch (e) {
      notify(e.message || "Registration failed", "error");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthFrame side="Create your account to discover curated opportunities.">
      <h1 className="h-page">Join JobRadar</h1>
      <p className="muted mt-2 mb-6">Create your account to discover curated opportunities.</p>
      <OpportunityNotice />
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Input className="sm:col-span-2" label="Full Name *" placeholder="Your name" {...bind("full_name")} data-testid="reg-name" />
        <Input label="Email *" type="email" placeholder="you@example.com" {...bind("email")} data-testid="reg-email" />
        <Input label="Mobile Number *" placeholder="10-digit mobile" {...bind("mobile")} data-testid="reg-mobile" />
        <Input label="Password *" type="password" placeholder="Min 6 characters" {...bind("password")} data-testid="reg-password" />
        <Input label="Confirm Password *" type="password" placeholder="Re-enter password" {...bind("confirm_password")} data-testid="reg-confirm" />
      </div>
      <div className="mt-5 space-y-5">
        <ChipRow label="Industry *">
          {INDUSTRIES_WITH_OTHER.map((c) => (
            <Chip key={c} label={INDUSTRY_SHORT[c] || c} selected={form.industry === c} onClick={() => set("industry", c)} data-testid={`reg-industry-${c}`} />
          ))}
        </ChipRow>
        <p className="-mt-3 text-xs text-gray-500">JobRadar currently focuses primarily on the five industries above.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Current Designation *" placeholder="e.g. Senior Accountant" {...bind("current_designation")} data-testid="reg-designation" />
          <Input label="Current Annual CTC *" placeholder="e.g. 8 LPA or USD 60,000" {...bind("current_salary")} data-testid="reg-salary" />
        </div>
        <h2 className="h-sec pt-2">Your Job Preferences</h2>
        <ChipRow label="Preferred Industry (select multiple)">
          {INDUSTRIES.map((c) => (
            <Chip key={c} label={INDUSTRY_SHORT[c] || c} selected={pref.includes(c)} onClick={() => toggle(c)} data-testid={`reg-pref-ind-${c}`} />
          ))}
        </ChipRow>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Preferred Designation / Job Title" placeholder="e.g. Finance Manager" {...bind("preferred_designation")} data-testid="reg-pref-designation" />
          <Input label="Preferred Job Location / Country *" placeholder="e.g. Bengaluru or Dubai" {...bind("preferred_location")} data-testid="reg-location" />
        </div>
        <ChipRow label="Preferred Work Mode *">
          {PREF_WORK_MODES.map((m) => (
            <Chip key={m} label={m} selected={form.preferred_work_mode === m} onClick={() => set("preferred_work_mode", m)} data-testid={`reg-wm-${m}`} />
          ))}
        </ChipRow>
        <ChipRow label="Preferred Experience">
          {EXPERIENCE_RANGES.map((e) => (
            <Chip key={e} label={e} selected={form.preferred_experience === e}
              onClick={() => set("preferred_experience", form.preferred_experience === e ? "" : e)} data-testid={`reg-exp-${e}`} />
          ))}
        </ChipRow>
        {resumeCfg?.uploads_enabled ? (
          <label className="block" data-testid="reg-resume">
            <span className="label">Resume (optional)</span>
            <input type="file" accept=".pdf,.docx" className="field mt-1.5" onChange={(e) => setResume(e.target.files?.[0] || null)} data-testid="reg-resume-input" />
            <span className="mt-1 block text-xs text-gray-500">PDF or Word (.docx), up to {resumeCfg.max_mb} MB. We'll read it and let you review the details before anything is saved.</span>
          </label>
        ) : null}
        <div className="flex items-start gap-3 text-sm text-gray-600">
          <button type="button" onClick={() => setTalent((c) => !c)} data-testid="reg-talent-consent">
            {talent ? <CheckSquare className="h-5 w-5 text-brand" /> : <Square className="h-5 w-5 text-gray-400" />}
          </button>
          <span>Optional: let JobRadar recruiters find my profile and resume for relevant roles. Not shared with employers without my permission; I can withdraw at any time.</span>
        </div>
        <div className="flex items-start gap-3 text-sm text-gray-600">
          <button type="button" onClick={() => setConsent((c) => !c)} data-testid="reg-consent">
            {consent ? <CheckSquare className="h-5 w-5 text-brand" /> : <Square className="h-5 w-5 text-gray-400" />}
          </button>
          <span>I agree to the <Link to="/legal/terms" className="font-bold text-brand">Terms</Link> and <Link to="/legal/privacy" className="font-bold text-brand">Privacy Policy</Link>.</span>
        </div>
        <Button full size="lg" title="Create Account" loading={loading} onClick={submit} data-testid="reg-submit" />
        <p className="text-center text-sm text-gray-500">
          Already have an account? <Link to="/auth/login" className="font-bold text-brand hover:underline" data-testid="go-login">Login</Link>
        </p>
      </div>
    </AuthFrame>
  );
}

export function Forgot() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const run = async (fn) => {
    setLoading(true);
    try {
      await fn();
    } catch (e) {
      notify(e.message || "Failed", "error");
    } finally {
      setLoading(false);
    }
  };
  const requestCode = () => {
    if (!email) return notify("Enter your email", "error");
    run(async () => {
      await api("/auth/forgot-password", { method: "POST", body: { email: email.trim() }, auth: false });
      notify("If the account exists, a reset code was sent", "success");
      setStep(2);
    });
  };
  const reset = () => {
    if (!token || !password) return notify("Enter code and new password", "error");
    run(async () => {
      await api("/auth/reset-password", { method: "POST", body: { email: email.trim(), token: token.trim().toUpperCase(), new_password: password }, auth: false });
      notify("Password reset! Please login", "success");
      navigate("/auth/login");
    });
  };
  return (
    <AuthFrame side="We'll email you a reset code to set a new password.">
      <h1 className="h-page">{step === 1 ? "Forgot your password?" : "Enter reset code"}</h1>
      <p className="muted mt-2">{step === 1 ? "We'll email you a reset code to set a new password." : "Check your email for the 8-character reset code."}</p>
      <div className="mt-8 space-y-4">
        {step === 1 ? (
          <>
            <Input label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" data-testid="forgot-email" />
            <Button full title="Send Reset Code" loading={loading} onClick={requestCode} data-testid="forgot-send" />
          </>
        ) : (
          <>
            <Input label="Reset Code" value={token} onChange={(e) => setToken(e.target.value)} placeholder="8-character code" data-testid="reset-code" />
            <Input label="New Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Min 6 characters" data-testid="reset-password" />
            <Button full title="Reset Password" loading={loading} onClick={reset} data-testid="reset-submit" />
          </>
        )}
      </div>
    </AuthFrame>
  );
}
