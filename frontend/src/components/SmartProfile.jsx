import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ALERT_FREQUENCIES, CURRENCIES, EMPLOYMENT_TYPES, INDUSTRIES_WITH_OTHER, INDUSTRY_SHORT, NOTICE_PERIODS } from "@/lib/constants";
import { Button, Card, Chip, ChipRow, errMsg, Input, notify, Switch } from "@/components/kit";

export const ALERT_NOTICE = "JobRadar uses your profile to recommend relevant opportunities. You can change your notification preferences at any time.";

const toList = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
const fromList = (v) => (Array.isArray(v) ? v.join(", ") : v || "");

export function ProfileCompletion({ compact }) {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data } = useQuery({ queryKey: ["profile-status", user?.user_id, user?.updated_at], queryFn: () => api("/smartmatch/profile-status"), enabled: user?.role === "candidate" });
  if (!data) return null;
  return (
    <Card className="space-y-3" data-testid="profile-completion">
      <div className="flex items-center justify-between gap-4">
        <p className="h-sec">Profile completion</p>
        <b className="text-2xl text-brand" data-testid="profile-completion-pct">{data.completion}%</b>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-brand-soft"><div className="h-full rounded-full bg-brand" style={{ width: `${data.completion}%` }} /></div>
      {data.missing.length ? (
        <p className="text-sm text-gray-500">Add {data.missing.slice(0, compact ? 3 : 20).join(", ")}{compact && data.missing.length > 3 ? ` and ${data.missing.length - 3} more` : ""} to get more accurate job matches.</p>
      ) : <p className="text-sm text-emerald-700">Your profile is complete — your matches are as accurate as possible.</p>}
      {compact && data.missing.length ? <Button size="sm" title="Complete Profile" onClick={() => navigate("/profile")} data-testid="profile-completion-cta" /> : null}
    </Card>
  );
}

export function SmartProfileForm() {
  const { user, refresh } = useAuth();
  const [f, setF] = useState(() => ({
    total_experience: user.total_experience ?? "", current_company: user.current_company || "", expected_ctc: user.expected_ctc ?? "",
    expected_ctc_currency: user.expected_ctc_currency || "INR", primary_skills: fromList(user.primary_skills),
    secondary_skills: fromList(user.secondary_skills), preferred_titles: fromList(user.preferred_titles || user.preferred_designation),
    preferred_locations: fromList(user.preferred_locations || user.preferred_location), preferred_country: user.preferred_country || "",
    notice_period: user.notice_period || "", willing_to_relocate: !!user.willing_to_relocate, employment_type_pref: user.employment_type_pref || "",
    profile_status: user.profile_status || "Active", job_alert_consent: user.job_alert_consent ?? null, job_alert_frequency: user.job_alert_frequency || "Instant",
    current_location: user.current_location || "", relevant_experience: user.relevant_experience ?? "", tools: fromList(user.tools),
    certifications: fromList(user.certifications), highest_qualification: user.highest_qualification || "", institution: user.institution || "",
    alert_muted_industries: user.alert_muted_industries || [],
  }));
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));
  const bind = (k) => ({ value: f[k], onChange: (e) => set(k, e.target.value) });
  const save = async () => {
    const exp = f.total_experience === "" ? null : Number(f.total_experience);
    const rel = f.relevant_experience === "" ? null : Number(f.relevant_experience);
    const ctc = f.expected_ctc === "" ? null : Number(String(f.expected_ctc).replace(/,/g, ""));
    if (Number.isNaN(exp) || Number.isNaN(rel) || Number.isNaN(ctc)) return notify("Experience and expected CTC must be numbers", "error");
    setBusy(true);
    try {
      const body = { ...f, total_experience: exp, relevant_experience: rel, expected_ctc: ctc, tools: toList(f.tools), certifications: toList(f.certifications),
        primary_skills: toList(f.primary_skills), secondary_skills: toList(f.secondary_skills),
        preferred_titles: toList(f.preferred_titles), preferred_locations: toList(f.preferred_locations) };
      Object.keys(body).forEach((k) => (body[k] === "" || body[k] === null) && delete body[k]);
      if (f.job_alert_consent === (user.job_alert_consent ?? null)) delete body.job_alert_consent;
      await api("/auth/profile", { method: "PUT", body });
      await refresh();
      notify("Professional preferences saved", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const deleteData = async () => {
    if (!window.confirm("Delete your SmartMatch data (matches, alerts and activity) and turn off job alerts? Your account stays.")) return;
    try {
      await api("/smartmatch/my-data", { method: "DELETE" });
      await refresh();
      set("job_alert_consent", false);
      notify("SmartMatch data deleted", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  return (
    <Card className="space-y-5 p-8" data-testid="smart-profile">
      <div>
        <p className="h-sec">Professional preferences (SmartMatch)</p>
        <p className="muted">Used to match you with relevant jobs. Separate multiple values with commas.</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Input label="Total work experience (years)" inputMode="decimal" {...bind("total_experience")} data-testid="sp-experience" />
        <Input label="Relevant experience (years)" inputMode="decimal" {...bind("relevant_experience")} data-testid="sp-rel-experience" />
        <Input label="Current company" {...bind("current_company")} data-testid="sp-company" />
        <Input label="Current location" {...bind("current_location")} data-testid="sp-current-location" />
        <div className="grid grid-cols-[1fr_110px] gap-2">
          <Input label="Expected CTC (annual, full amount)" placeholder="e.g. 1200000" inputMode="numeric" {...bind("expected_ctc")} data-testid="sp-expected-ctc" />
          <label className="block"><span className="label">Currency</span>
            <select className="field mt-1.5" value={f.expected_ctc_currency} onChange={(e) => set("expected_ctc_currency", e.target.value)} data-testid="sp-currency">
              {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
        </div>
        <Input label="Preferred country" {...bind("preferred_country")} data-testid="sp-country" />
        <Input label="Primary skills" placeholder="e.g. Recruiting, Excel, SAP" {...bind("primary_skills")} data-testid="sp-primary-skills" />
        <Input label="Secondary skills" {...bind("secondary_skills")} data-testid="sp-secondary-skills" />
        <Input label="Software & tools" placeholder="e.g. Sabre, Amadeus, Tally" {...bind("tools")} data-testid="sp-tools" />
        <Input label="Certifications" {...bind("certifications")} data-testid="sp-certifications" />
        <Input label="Highest qualification" placeholder="e.g. Bachelor's, MBA" {...bind("highest_qualification")} data-testid="sp-qualification" />
        <Input label="Institution" {...bind("institution")} data-testid="sp-institution" />
        <Input label="Preferred job titles" placeholder="e.g. HR Executive, Talent Acquisition" {...bind("preferred_titles")} data-testid="sp-titles" />
        <Input label="Preferred locations" placeholder="e.g. Mumbai, Pune, Dubai" {...bind("preferred_locations")} data-testid="sp-locations" />
      </div>
      <ChipRow label="Notice period">
        {NOTICE_PERIODS.map((n) => <Chip key={n} label={n} selected={f.notice_period === n} onClick={() => set("notice_period", n)} data-testid={`sp-notice-${n}`} />)}
      </ChipRow>
      <ChipRow label="Employment type preference">
        {EMPLOYMENT_TYPES.map((n) => <Chip key={n} label={n} selected={f.employment_type_pref === n} onClick={() => set("employment_type_pref", n)} data-testid={`sp-emp-${n}`} />)}
      </ChipRow>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex items-center justify-between gap-4 rounded-xl bg-brand-mist p-4 text-sm font-semibold">Willing to relocate
          <Switch checked={f.willing_to_relocate} onChange={(v) => set("willing_to_relocate", v)} data-testid="sp-relocate" /></label>
        <label className="flex items-center justify-between gap-4 rounded-xl bg-brand-mist p-4 text-sm font-semibold">Profile active (visible for matching)
          <Switch checked={f.profile_status === "Active"} onChange={(v) => set("profile_status", v ? "Active" : "Inactive")} data-testid="sp-active" /></label>
      </div>
      <div className="space-y-3 rounded-xl border border-gray-200 p-4" data-testid="sp-alerts">
        <p className="text-sm font-bold">Job alerts</p>
        <p className="text-xs text-gray-500">JobRadar uses your profile to recommend relevant opportunities on your dashboard. You can change this at any time.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {[[true, "Receive relevant job alerts", "In-app and email alerts for jobs JobRadar approves for you"], [false, "Turn off job alerts", "No job notifications. You can still browse and see matches yourself"]].map(([v, l, d]) => (
            <button key={String(v)} type="button" onClick={() => set("job_alert_consent", v)} data-testid={`sp-alert-${v ? "on" : "off"}`}
              className={`rounded-xl border-2 p-3 text-left transition-colors ${f.job_alert_consent === v ? "border-brand bg-brand-mist" : "border-gray-200 hover:border-brand/50"}`}>
              <p className="text-sm font-bold">{l}</p><p className="text-xs text-gray-500">{d}</p>
            </button>
          ))}
        </div>
        {f.job_alert_consent === null ? <p className="text-xs text-brand" data-testid="sp-alert-none">Not selected yet — you'll still see relevant opportunities in-app.</p> : null}
        {f.job_alert_consent !== false ? (
          <div data-testid="sp-muted">
            <ChipRow label="Don't alert me about jobs in">
              {INDUSTRIES_WITH_OTHER.map((n) => (
                <Chip key={n} label={INDUSTRY_SHORT[n] || n} selected={f.alert_muted_industries.includes(n)} data-testid={`sp-mute-${n}`}
                  onClick={() => set("alert_muted_industries", f.alert_muted_industries.includes(n) ? f.alert_muted_industries.filter((x) => x !== n) : [...f.alert_muted_industries, n])} />
              ))}
            </ChipRow>
            <p className="mt-1 text-xs text-gray-500">Muted categories still appear in your matches; you just won't get alerts for them.</p>
          </div>
        ) : null}
        {f.job_alert_consent === true ? (
          <ChipRow label="Email alert frequency">
            {ALERT_FREQUENCIES.map((n) => <Chip key={n} label={n} selected={f.job_alert_frequency === n} onClick={() => set("job_alert_frequency", n)} data-testid={`sp-freq-${n}`} />)}
          </ChipRow>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button title="Save Preferences" loading={busy} onClick={save} data-testid="sp-save" />
        <button onClick={deleteData} className="text-xs font-semibold text-gray-500 underline hover:text-red-600" data-testid="sp-delete-data">Delete my SmartMatch data</button>
      </div>
    </Card>
  );
}
