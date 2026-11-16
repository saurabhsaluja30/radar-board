import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { api } from "@/lib/api";
import { CATEGORIES, CURRENCIES, EMPLOYMENT_TYPES, formatDate, INDUSTRIES, INDUSTRIES_WITH_OTHER, INDUSTRY_SHORT, JOB_SOURCES, JOB_STATUS_LABEL, JOB_STATUSES, money, NOTICE_PERIODS, REGIONS, VERIFICATION_STATUSES, WORK_MODES } from "@/lib/constants";
import { Badge, Button, Card, Chip, ChipRow, Input, notify, PageHeader, Switch } from "@/components/kit";

const SearchBox = ({ value, onChange, placeholder, testId }) => (
  <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 focus-within:border-brand">
    <Search className="h-4 w-4 text-gray-400" />
    <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="h-11 flex-1 bg-transparent outline-none" data-testid={testId} />
  </div>
);

const Th = ({ children }) => <th className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wider text-gray-400">{children}</th>;
const Td = ({ children, className = "" }) => <td className={`px-4 py-3.5 align-top text-sm ${className}`}>{children}</td>;
const Table = ({ head, children }) => (
  <div className="overflow-x-auto rounded-2xl border border-gray-200 bg-white">
    <table className="w-full"><thead className="border-b border-gray-100 bg-gray-50/60"><tr>{head.map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
      <tbody className="divide-y divide-gray-100">{children}</tbody></table>
  </div>
);

function useAct(keys) {
  const qc = useQueryClient();
  return async (fn, msg) => {
    try {
      await fn();
      notify(msg, "success");
      keys.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch (e) {
      notify(e.message || "Failed", "error");
    }
  };
}

export function AdminJobs() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("All");
  const [region, setRegion] = useState("All");
  const [ind, setInd] = useState("All");
  const [ver, setVer] = useState("All");
  const [src, setSrc] = useState("All");
  const [loc, setLoc] = useState("");
  const { data } = useQuery({ queryKey: ["admin-jobs", q, status, region, ind, ver, src, loc],
    queryFn: () => api("/admin/jobs", { query: { q, status, region, industry_category: ind, verification_status: ver, job_source: src, location: loc } }) });
  const jobs = data?.jobs || [];
  const act = useAct(["admin-jobs", "jobs", "job"]);
  const post = (id, path, body) => () => api(`/admin/jobs/${id}${path}`, { method: "POST", body });
  return (
    <>
      <PageHeader title="Job Management" right={<Button title="Add Job" icon={<Plus className="h-4 w-4" />} onClick={() => navigate("/admin/job-edit")} data-testid="admin-add-job" />} />
      <div className="mb-6 space-y-3">
        <SearchBox value={q} onChange={setQ} placeholder="Search jobs..." testId="admin-job-search" />
        <div className="flex flex-wrap gap-2">
          <Chip label="All statuses" selected={status === "All"} onClick={() => setStatus("All")} data-testid="admin-status-all" />
          {JOB_STATUSES.map((s) => <Chip key={s} label={JOB_STATUS_LABEL[s]} selected={status === s} onClick={() => setStatus(s)} data-testid={`admin-status-${s}`} />)}
          <span className="mx-2 w-px bg-gray-200" />
          <Chip label="Any verification" selected={ver === "All"} onClick={() => setVer("All")} data-testid="admin-ver-all" />
          {VERIFICATION_STATUSES.map((v) => <Chip key={v} label={v} selected={ver === v} onClick={() => setVer(v)} data-testid={`admin-ver-${v}`} />)}
          <span className="mx-2 w-px bg-gray-200" />
          <Chip label="All regions" selected={region === "All"} onClick={() => setRegion("All")} data-testid="admin-region-all" />
          {REGIONS.map((r) => <Chip key={r} label={r} selected={region === r} onClick={() => setRegion(region === r ? "All" : r)} data-testid={`admin-region-${r}`} />)}
          <span className="mx-2 w-px bg-gray-200" />
          <Chip label="All industries" selected={ind === "All"} onClick={() => setInd("All")} data-testid="admin-ind-all" />
          {INDUSTRIES.map((c) => <Chip key={c} label={INDUSTRY_SHORT[c]} selected={ind === c} onClick={() => setInd(ind === c ? "All" : c)} data-testid={`admin-ind-${c}`} />)}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Chip label="All sources" selected={src === "All"} onClick={() => setSrc("All")} data-testid="admin-src-all" />
          {JOB_SOURCES.map((c) => <Chip key={c} label={c} selected={src === c} onClick={() => setSrc(src === c ? "All" : c)} data-testid={`admin-src-${c}`} />)}
          <input value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="Location..." className="field ml-auto w-48 py-2" data-testid="admin-job-location" />
        </div>
      </div>
      <Table head={["Job", "Status", "Stats", "Actions"]}>
        {jobs.map((j) => (
          <tr key={j.job_id} data-testid={`admin-job-${j.job_id}`}>
            <Td>
              <button onClick={() => navigate(`/admin/job-edit?id=${j.job_id}`)} className="text-left font-bold text-gray-900 hover:text-brand">{j.title}</button>
              <p className="text-gray-500">{j.company} · {j.location || j.city || j.country}</p>
            </Td>
            <Td><div className="flex flex-wrap gap-1"><Badge label={JOB_STATUS_LABEL[j.status] || j.status} color={j.status === "Published" ? "success" : j.status === "Draft" ? "warning" : "info"} />
              <Badge label={j.verification_status || "Pending Verification"} color={j.verification_status === "Verified" ? "success" : j.verification_status === "Rejected" ? "error" : "warning"} />
              {j.featured ? <Badge label="Featured" color="brand" /> : null}</div>
              <p className="mt-1 text-xs text-gray-400">{j.job_source || "Source not set"}{j.expiry_date ? ` · expires ${formatDate(j.expiry_date)}` : ""}</p></Td>
            <Td className="whitespace-nowrap text-gray-500">{j.views || 0} views · {j.saves || 0} saves</Td>
            <Td>
              <div className="flex flex-wrap gap-1">
                <Button size="sm" variant="ghost" title="Edit" onClick={() => navigate(`/admin/job-edit?id=${j.job_id}`)} data-testid={`admin-job-edit-${j.job_id}`} />
                {j.verification_status !== "Verified" ? (
                  <Button size="sm" variant="secondary" title="Verify" data-testid={`admin-job-verify-${j.job_id}`}
                    onClick={() => act(() => api(`/admin/smartmatch/jobs/${j.job_id}/verify`, { method: "POST", body: { verification_status: "Verified" } }), "Job verified")} />
                ) : null}
                <Button size="sm" variant="ghost" title={j.status === "Published" ? "Pause" : "Publish (Open)"} data-testid={`admin-job-publish-${j.job_id}`}
                  onClick={() => act(post(j.job_id, "/status", { status: j.status === "Published" ? "Unpublished" : "Published" }), "Status updated")} />
                <Button size="sm" variant="ghost" title="Close" onClick={() => act(post(j.job_id, "/status", { status: "Closed" }), "Job closed")} data-testid={`admin-job-close-${j.job_id}`} />
                <Button size="sm" variant="outline" title="Find Matching Candidates" onClick={() => navigate(`/admin/smartmatch/job/${j.job_id}`)} data-testid={`admin-job-match-${j.job_id}`} />
                <Button size="sm" variant="ghost" title="Mark Expired" onClick={() => act(post(j.job_id, "/status", { status: "Expired" }), "Marked expired")} data-testid={`admin-job-expire-${j.job_id}`} />
                <Button size="sm" variant="ghost" title={j.featured ? "Unfeature" : "Feature"} onClick={() => act(post(j.job_id, "/feature", { featured: !j.featured }), "Updated")} data-testid={`admin-job-feature-${j.job_id}`} />
                <Button size="sm" variant="ghost" title="Duplicate" onClick={() => act(post(j.job_id, "/duplicate"), "Duplicated")} data-testid={`admin-job-duplicate-${j.job_id}`} />
                <Button size="sm" variant="ghost" title="Delete" className="!text-red-600" data-testid={`admin-job-delete-${j.job_id}`}
                  onClick={() => window.confirm("Delete this job?") && act(() => api(`/admin/jobs/${j.job_id}`, { method: "DELETE" }), "Deleted")} />
              </div>
            </Td>
          </tr>
        ))}
      </Table>
      {jobs.length === 0 ? <p className="muted mt-6 text-center">No jobs found.</p> : null}
    </>
  );
}

const EMPTY_JOB = {
  title: "", company: "", function: "", industry_category: "", sub_function: "", industry: "", designation: "", region: "India",
  location: "", city: "", country: "India", currency: "INR", visa_info: "", work_mode: "Work From Office", experience_required: "",
  salary_range: "", employment_type: "Full-time", description: "", key_responsibilities: "", required_skills: "", preferred_skills: "",
  recruiter_name: "", recruiter_email: "", application_link: "", source_link: "", application_deadline: "", status: "Published",
  featured: false, verification_score: 80, admin_notes: "", verification_status: "Pending Verification", experience_min: "",
  experience_max: "", salary_min: "", salary_max: "", qualifications: "", mandatory_requirements: "", notice_period_pref: "",
  job_source: "", date_received: "", expiry_date: "",
};
const NUM_FIELDS = ["experience_min", "experience_max", "salary_min", "salary_max"];
const SHORT_FIELDS = [["sub_function", "Sub-function"], ["industry", "Industry (sector, e.g. IT Services)"], ["designation", "Designation"],
  ["location", "Location / Area"], ["city", "City"], ["country", "Country"], ["experience_required", "Experience Required"],
  ["salary_range", "Salary Range (as shown to candidates)"], ["recruiter_name", "Recruiter Name"],
  ["recruiter_email", "Recruiter Email"], ["application_link", "External Application URL"], ["source_link", "Source Reference / Original URL"],
  ["experience_min", "Min Experience (years)"], ["experience_max", "Max Experience (years)"],
  ["salary_min", "Salary Min (annual, full amount)"], ["salary_max", "Salary Max (annual, full amount)"],
  ["date_received", "Date Received (YYYY-MM-DD)"], ["expiry_date", "Expiry Date (YYYY-MM-DD)"]];
const LONG_FIELDS = [["visa_info", "Work Authorization / Visa Info"], ["description", "Job Description"], ["key_responsibilities", "Key Responsibilities"],
  ["required_skills", "Required Skills"], ["preferred_skills", "Preferred Skills"], ["qualifications", "Required Qualifications (if any)"],
  ["mandatory_requirements", "Mandatory Licence / Language / Other (checked manually)"], ["admin_notes", "Internal Admin Notes (never shown to candidates)"]];

export function AdminJobEdit() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const id = params.get("id");
  const qc = useQueryClient();
  const [form, setForm] = useState(EMPTY_JOB);
  const [loading, setLoading] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  useEffect(() => {
    if (id) api(`/admin/jobs/${id}`).then((res) => setForm({ ...EMPTY_JOB, ...Object.fromEntries(Object.entries(res.job).map(([k, v]) => [k, v ?? ""])) })).catch(() => {});
  }, [id]);
  const save = async () => {
    if (!form.title || !form.company) return notify("Title and company are required", "error");
    const body = { ...form };
    for (const k of NUM_FIELDS) {
      if (body[k] === "" || body[k] === null) body[k] = null;
      else if (Number.isNaN(Number(body[k]))) return notify("Experience and salary must be numbers", "error");
      else body[k] = Number(body[k]);
    }
    setLoading(true);
    try {
      const dup = await api("/admin/smartmatch/duplicates", { query: { company: form.company, title: form.title, location: form.location, source_link: form.source_link, exclude: id || "" } });
      if (dup.duplicates.length && !window.confirm(`Possible duplicate: ${dup.duplicates.map((d) => `${d.title} at ${d.company} (${d.job_id})`).join(", ")}. Save anyway?`)) return;
      if (id) await api(`/admin/jobs/${id}`, { method: "PUT", body });
      else await api("/admin/jobs", { method: "POST", body });
      notify(id ? "Job updated" : "Job created", "success");
      ["admin-jobs", "jobs", "job", "saved-jobs", "dashboard"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      navigate("/admin/jobs");
    } catch (e) {
      notify(e.message || "Failed", "error");
    } finally {
      setLoading(false);
    }
  };
  const chips = (label, k, opts, short = (x) => x, tid) => (
    <ChipRow label={label}>
      {opts.map((o) => <Chip key={o} label={short(o)} selected={form[k] === o} onClick={() => set(k, o)} data-testid={`jobedit-${tid || k}-${o}`} />)}
    </ChipRow>
  );
  return (
    <>
      <PageHeader title={id ? "Edit Job" : "Add Job"} right={<Button variant="ghost" title="‹ Back to jobs" onClick={() => navigate("/admin/jobs")} data-testid="jobedit-back" />} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-4">
          <Input label="Job Title *" value={form.title} onChange={(e) => set("title", e.target.value)} data-testid="jobedit-title" />
          <Input label="Company Name *" value={form.company} onChange={(e) => set("company", e.target.value)} data-testid="jobedit-company" />
          <div className="grid gap-4 md:grid-cols-2">
            {SHORT_FIELDS.map(([k, label]) => <Input key={k} label={label} value={String(form[k] ?? "")} onChange={(e) => set(k, e.target.value)} data-testid={`jobedit-${k}`} />)}
          </div>
        </Card>
        <Card className="space-y-5">
          {chips("Function", "function", CATEGORIES, (c) => c.split(" & ")[0], "fn")}
          {chips("Industry", "industry_category", INDUSTRIES_WITH_OTHER, (c) => INDUSTRY_SHORT[c] || c, "ind")}
          {chips("Region", "region", REGIONS)}
          {chips("Currency", "currency", CURRENCIES, undefined, "cur")}
          {chips("Work Mode", "work_mode", WORK_MODES, undefined, "wm")}
          {chips("Status", "status", JOB_STATUSES, (x) => JOB_STATUS_LABEL[x])}
          {chips("Verification", "verification_status", VERIFICATION_STATUSES, undefined, "ver")}
          {chips("Job Source", "job_source", JOB_SOURCES, undefined, "src")}
          {chips("Notice Period Preference", "notice_period_pref", NOTICE_PERIODS, undefined, "notice")}
          {chips("Employment Type", "employment_type", EMPLOYMENT_TYPES.filter((x) => x !== "Any"), undefined, "emp")}
          <div className="flex items-center justify-between rounded-xl bg-brand-mist p-4">
            <span className="font-bold">Featured Job</span>
            <Switch checked={!!form.featured} onChange={(v) => set("featured", v)} data-testid="jobedit-featured" />
          </div>
        </Card>
        <Card className="space-y-4 lg:col-span-2">
          <div className="grid gap-4 md:grid-cols-2">
            {LONG_FIELDS.map(([k, label]) => <Input key={k} multiline label={label} value={String(form[k] ?? "")} onChange={(e) => set(k, e.target.value)} data-testid={`jobedit-${k}`} />)}
          </div>
          <Button title={id ? "Save Changes" : "Create Job"} loading={loading} onClick={save} data-testid="jobedit-save" />
        </Card>
      </div>
    </>
  );
}

const statusColor = (s) => (s === "active" || s === "expiring_soon" ? "success" : s === "no_membership" ? "info" : "error");

export function AdminCandidates() {
  const [q, setQ] = useState("");
  const [ind, setInd] = useState("All");
  const [open, setOpen] = useState(null);
  const { data } = useQuery({ queryKey: ["admin-candidates", q, ind], queryFn: () => api("/admin/candidates", { query: { q, industry: ind } }) });
  const candidates = data?.candidates || [];
  const act = useAct(["admin-candidates"]);
  return (
    <>
      <PageHeader title="Candidates" subtitle={`${candidates.length} candidates`} />
      <div className="mb-6 space-y-3">
        <SearchBox value={q} onChange={setQ} placeholder="Search name, email, designation..." testId="admin-cand-search" />
        <div className="flex flex-wrap gap-2">
          <Chip label="All" selected={ind === "All"} onClick={() => setInd("All")} data-testid="cand-ind-all" />
          {INDUSTRIES.map((c) => <Chip key={c} label={INDUSTRY_SHORT[c]} selected={ind === c} onClick={() => setInd(ind === c ? "All" : c)} data-testid={`cand-ind-${c}`} />)}
        </div>
      </div>
      <Table head={["Candidate", "Membership", "Plan / Expiry", "Actions"]}>
        {candidates.map((c) => (
          <React.Fragment key={c.user_id}>
            <tr data-testid={`admin-cand-${c.email}`}>
              <Td>
                <button onClick={() => setOpen(open === c.user_id ? null : c.user_id)} className="text-left" data-testid={`cand-toggle-${c.email}`}>
                  <p className="font-bold text-gray-900 hover:text-brand">{c.full_name || "—"}</p>
                  <p className="text-gray-500">{c.email}</p>
                </button>
              </Td>
              <Td><Badge label={(c.membership_status || "").replace("_", " ")} color={statusColor(c.membership_status)} />{c.suspended ? <span className="ml-1"><Badge label="Suspended" color="error" /></span> : null}</Td>
              <Td className="text-gray-600">{c.plan_name || "—"}<br /><span className="text-gray-400">{formatDate(c.expiry_date)}</span></Td>
              <Td>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" title="Extend 30 days" data-testid={`cand-extend-${c.email}`}
                    onClick={() => act(() => api(`/admin/candidates/${c.user_id}/extend`, { method: "POST", body: { days: 30 } }), "Extended 30 days")} />
                  <Button size="sm" variant={c.suspended ? "secondary" : "danger"} title={c.suspended ? "Reactivate" : "Suspend"} data-testid={`cand-suspend-${c.email}`}
                    onClick={() => act(() => api(`/admin/candidates/${c.user_id}/suspend`, { method: "POST", body: { suspended: !c.suspended } }), c.suspended ? "Reactivated" : "Suspended")} />
                </div>
              </Td>
            </tr>
            {open === c.user_id ? (
              <tr className="bg-brand-mist/50" data-testid={`cand-details-${c.email}`}>
                <td colSpan={4} className="grid gap-1 px-4 py-4 text-sm text-gray-700 md:grid-cols-2">
                  <p>Mobile: {c.mobile || "—"}</p>
                  <p>Joined: {formatDate(c.created_at)} · {c.suspended ? "Suspended" : "Active"}</p>
                  <p>Industry: {c.industry || "Not Provided"}</p>
                  <p>Current: {c.current_designation || "Not Provided"} · {c.current_salary || "Not Provided"}</p>
                  <p>Prefers: {(c.preferred_industries || []).join(", ") || "Not Provided"}</p>
                  <p>Target: {c.preferred_designation || "Not Provided"} · {c.preferred_location || "Not Provided"} · {c.preferred_work_mode || "Any"}</p>
                </td>
              </tr>
            ) : null}
          </React.Fragment>
        ))}
      </Table>
    </>
  );
}

const SUB_FILTERS = ["All", "active", "expiring_soon", "expired", "cancelled", "payment_failed"];

export function AdminSubscriptions() {
  const [filter, setFilter] = useState("All");
  const { data } = useQuery({ queryKey: ["admin-subs", filter], queryFn: () => api("/admin/subscriptions", { query: { status: filter } }) });
  const subs = data?.subscriptions || [];
  const act = useAct(["admin-subs"]);
  const color = (s) => (s === "active" || s === "expiring_soon" ? "success" : ["cancelled", "expired", "payment_failed"].includes(s) ? "error" : "info");
  return (
    <>
      <PageHeader title="Subscriptions" />
      <div className="mb-6 flex flex-wrap gap-2">
        {SUB_FILTERS.map((f) => <Chip key={f} label={f.replace("_", " ")} selected={filter === f} onClick={() => setFilter(f)} data-testid={`sub-filter-${f}`} />)}
      </div>
      <Table head={["Candidate", "Plan", "Status", "Dates", ""]}>
        {subs.map((s) => (
          <tr key={s.subscription_id} data-testid={`admin-sub-${s.subscription_id}`}>
            <Td className="font-bold">{s.candidate_name || s.candidate_email}</Td>
            <Td>{s.plan_name} {s.is_demo ? <Badge label="DEMO" color="warning" /> : null}</Td>
            <Td><Badge label={(s.effective_status || "").replace("_", " ")} color={color(s.effective_status)} /></Td>
            <Td className="text-gray-500">Start: {formatDate(s.start_date)}<br />Expiry: {formatDate(s.expiry_date)}</Td>
            <Td>{s.effective_status !== "cancelled" ? (
              <Button size="sm" variant="danger" title="Cancel Subscription" data-testid={`sub-cancel-${s.subscription_id}`}
                onClick={() => act(() => api(`/admin/subscriptions/${s.subscription_id}/cancel`, { method: "POST" }), "Subscription cancelled")} />
            ) : null}</Td>
          </tr>
        ))}
      </Table>
      {subs.length === 0 ? <p className="muted mt-6 text-center">No subscriptions.</p> : null}
    </>
  );
}

export function AdminPayments() {
  const [demo, setDemo] = useState("all");
  const { data } = useQuery({ queryKey: ["admin-payments", demo], queryFn: () => api("/admin/payments", { query: { demo } }) });
  const payments = data?.payments || [];
  const sum = (isDemo) => payments.filter((p) => !!p.is_demo === isDemo && p.status === "successful").reduce((s, p) => s + p.amount, 0);
  const color = (s) => (s === "successful" ? "success" : s === "failed" ? "error" : "info");
  return (
    <>
      <PageHeader title="Payments" />
      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <Card><p className="text-sm font-semibold text-gray-500">Real Revenue</p><p className="text-3xl font-extrabold text-emerald-600" data-testid="pay-real-revenue">{money(sum(false))}</p></Card>
        <Card><p className="text-sm font-semibold text-gray-500">Demo Revenue</p><p className="text-3xl font-extrabold text-amber-600" data-testid="pay-demo-revenue">{money(sum(true))}</p></Card>
      </div>
      <div className="mb-6 flex gap-2">
        {[["all", "All"], ["real", "Real"], ["demo", "Demo"]].map(([v, l]) => <Chip key={v} label={l} selected={demo === v} onClick={() => setDemo(v)} data-testid={`pay-filter-${v}`} />)}
      </div>
      <Table head={["Plan", "Candidate", "Date / Txn", "Amount", "Status"]}>
        {payments.map((p) => (
          <tr key={p.payment_id} data-testid={`admin-pay-${p.payment_id}`}>
            <Td className="font-bold">{p.plan_name} {p.is_demo ? <Badge label="DEMO" color="warning" /> : null}</Td>
            <Td>{p.candidate_email}</Td>
            <Td className="text-gray-500">{formatDate(p.payment_date)}<br /><span className="text-xs">{p.transaction_id}</span></Td>
            <Td className="font-extrabold">{money(p.amount, p.currency)}</Td>
            <Td><Badge label={p.status} color={color(p.status)} /></Td>
          </tr>
        ))}
      </Table>
      {payments.length === 0 ? <p className="muted mt-6 text-center">No payments.</p> : null}
    </>
  );
}
