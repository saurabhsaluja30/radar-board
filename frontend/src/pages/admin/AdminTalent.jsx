import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, downloadFile, fetchBlob } from "@/lib/api";
import { formatDate, INDUSTRIES, NOTICE_PERIODS, PREF_WORK_MODES } from "@/lib/constants";
import { Badge, Button, Card, EmptyState, errMsg, Input, Modal, notify, PageHeader, Spinner, Switch } from "@/components/kit";

const Th = ({ children }) => <th className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-gray-400">{children}</th>;
const Td = ({ children, className = "" }) => <td className={`px-4 py-3.5 align-top text-sm ${className}`}>{children}</td>;
const EDUCATION = ["PhD", "MBA", "Master's", "Bachelor's", "Diploma", "12th / HSC"];
const EMPTY = {
  keyword: "", name: "", industry: "All", designation: "", preferred_designation: "", company: "", skills: "", tools: "",
  min_exp: "", max_exp: "", min_rel_exp: "", max_rel_exp: "", current_ctc: "", min_ectc: "", max_ectc: "", notice_period: "All",
  current_location: "", preferred_location: "", preferred_country: "", work_mode: "All", education: "All", certification: "",
  has_resume: "All", outdated: "", profile: "All", registered_from: "", registered_to: "",
};
const clean = (f) => Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "" && v !== "All"));
const list = (v) => (Array.isArray(v) ? v.join(", ") : v || "—");
const bytes = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.round((n || 0) / 1024)} KB`);

function Select({ label, value, onChange, options, testId }) {
  return (
    <label className="block"><span className="label">{label}</span>
      <select className="field mt-1.5" value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
        <option value="All">All</option>
        {options.map((o) => (Array.isArray(o) ? <option key={o[0]} value={o[0]}>{o[1]}</option> : <option key={o}>{o}</option>))}
      </select>
    </label>
  );
}

function CandidateModal({ id, onClose }) {
  const { data, error } = useQuery({ queryKey: ["admin-talent", id], queryFn: () => api(`/admin/talent/${id}`), enabled: !!id });
  const c = data?.candidate;
  const open = async (r, download) => {
    try {
      if (download) return await downloadFile(`/admin/talent/${id}/resume/${r.resume_id}`, { download: "1" }, r.original_filename);
      const url = URL.createObjectURL(await fetchBlob(`/admin/talent/${id}/resume/${r.resume_id}`));
      window.open(url, "_blank", "noopener");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  return (
    <Modal open={!!id} onClose={onClose} wide>
      {error ? <p className="text-red-600">{errMsg(error)}</p> : !c ? <Spinner /> : (
        <div className="space-y-5" data-testid="talent-detail">
          <div>
            <p className="h-page">{c.full_name}</p>
            <p className="text-sm text-gray-500">{c.email} · {c.mobile || "no mobile"} · joined {formatDate(c.created_at)}</p>
          </div>
          <div className="grid gap-2 text-sm text-gray-700 md:grid-cols-2">
            <p><b>Current:</b> {c.current_designation || "—"} at {c.current_company || "—"}</p>
            <p><b>Experience:</b> {c.total_experience ?? "—"} yrs total · {c.relevant_experience ?? "—"} yrs relevant</p>
            <p><b>Industry:</b> {c.industry || "—"} {c.industry_experience?.length ? `(resume: ${c.industry_experience.join(", ")})` : ""}</p>
            <p><b>Location:</b> {c.current_location || "—"} · prefers {list(c.preferred_locations?.length ? c.preferred_locations : c.preferred_location)}</p>
            <p><b>CTC:</b> {c.current_salary || "—"} now · expects {c.expected_ctc ? `${c.expected_ctc_currency || "INR"} ${c.expected_ctc.toLocaleString()}` : "—"}</p>
            <p><b>Notice:</b> {c.notice_period || "—"} · <b>Work mode:</b> {c.preferred_work_mode || "—"}</p>
            <p className="md:col-span-2"><b>Skills:</b> {list(c.primary_skills)}</p>
            <p className="md:col-span-2"><b>Tools:</b> {list(c.tools)}</p>
            <p><b>Education:</b> {c.highest_qualification || "—"} {c.institution ? `· ${c.institution}` : ""}</p>
            <p><b>Certifications:</b> {list(c.certifications)}</p>
            <p><b>Preferred titles:</b> {list(c.preferred_titles?.length ? c.preferred_titles : c.preferred_designation)}</p>
            <p><b>Languages:</b> {list(c.languages)}</p>
            <p className="md:col-span-2 break-all"><b>Links:</b> {c.links?.length ? c.links.map((l, i) => (
              <React.Fragment key={l}>{i ? ", " : ""}{/^https?:\/\//i.test(l) ? <a href={l} target="_blank" rel="noopener noreferrer nofollow" className="text-brand underline">{l}</a> : l}</React.Fragment>
            )) : "—"}</p>
            <p><b>Profile completion:</b> {c.completion}%{c.missing?.length ? ` (missing ${c.missing.slice(0, 4).join(", ")}${c.missing.length > 4 ? "…" : ""})` : ""}</p>
          </div>
          {c.education?.length ? (
            <div className="rounded-xl bg-gray-50 p-3 text-sm" data-testid="talent-education">
              <p className="mb-1 font-bold">Education</p>
              {c.education.map((e, i) => <p key={i}>{[e.degree, e.institution, e.year].filter(Boolean).join(" · ")}</p>)}
            </div>
          ) : null}
          {c.employment_history?.length ? (
            <div className="rounded-xl bg-gray-50 p-3 text-sm">
              <p className="mb-1 font-bold">Employment history</p>
              {c.employment_history.map((j, i) => <p key={i}>{[j.title, j.company].filter(Boolean).join(" · ")} — {j.start} to {j.end}</p>)}
            </div>
          ) : null}
          <div className="space-y-2">
            <p className="font-bold">Resumes</p>
            {!data.resumes.length ? <p className="text-sm text-gray-500">No resume uploaded.</p> : data.resumes.map((r) => (
              <div key={r.resume_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 p-3 text-sm">
                <span>v{r.version} · {r.original_filename} · {formatDate(r.uploaded_at)} {r.is_current ? <Badge label="Current" color="brand" /> : null}</span>
                {r.source === "paste" ? <span className="text-xs text-gray-500">Pasted as text</span> : (
                  <span className="flex gap-2">
                    <Button size="sm" variant="outline" title="View" onClick={() => open(r, false)} data-testid={`talent-view-${r.resume_id}`} />
                    <Button size="sm" variant="outline" title="Download" onClick={() => open(r, true)} />
                  </span>
                )}
              </div>
            ))}
            <p className="text-xs text-gray-400">Every resume view and download is recorded in the admin audit log.</p>
          </div>
          {data.raw_text ? (
            <div className="space-y-2" data-testid="talent-cv-text">
              <div className="flex items-center justify-between gap-2">
                <p className="font-bold">CV text</p>
                <Button size="sm" variant="outline" title="Copy" onClick={() => navigator.clipboard.writeText(data.raw_text).then(() => notify("CV text copied", "success"), () => notify("Couldn't copy", "error"))} />
              </div>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-xl bg-gray-50 p-3 font-sans text-xs text-gray-700">{data.raw_text}</pre>
            </div>
          ) : data.resumes.length && !data.can_view_cv_text ? <p className="text-xs text-gray-400">You need the "view resumes" permission to see the CV text.</p> : null}
        </div>
      )}
    </Modal>
  );
}

export function AdminTalent() {
  const [f, setF] = useState(EMPTY);
  const [applied, setApplied] = useState({});
  const [page, setPage] = useState(1);
  const [more, setMore] = useState(false);
  const [openId, setOpenId] = useState(null);
  const set = (k) => (v) => setF((x) => ({ ...x, [k]: typeof v === "string" ? v : v.target.value }));
  const { data, isFetching, error } = useQuery({ queryKey: ["admin-talent-list", applied, page], keepPreviousData: true,
    queryFn: () => api("/admin/talent", { query: { ...applied, page, page_size: 25 } }) });
  const search = () => { setApplied(clean(f)); setPage(1); };
  const reset = () => { setF(EMPTY); setApplied({}); setPage(1); };
  const exportCsv = () => downloadFile("/admin/talent/export", applied, "talent_database.csv").catch((e) => notify(errMsg(e), "error"));
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  return (
    <>
      <PageHeader title="Candidate Talent Database" subtitle={data ? `${data.total} matching · ${data.consented_total} candidates have opted in` : ""}
        right={<Button variant="outline" title="Export CSV" onClick={exportCsv} data-testid="talent-export" />} />
      <Card className="mb-6 space-y-4" data-testid="talent-filters">
        <div className="grid gap-3 md:grid-cols-4">
          <Input className="md:col-span-2" label="Resume keyword" placeholder="e.g. Sabre, Python, Payroll" value={f.keyword} onChange={set("keyword")}
            onKeyDown={(e) => e.key === "Enter" && search()} data-testid="talent-keyword" />
          <Input label="Name" value={f.name} onChange={set("name")} data-testid="talent-name" />
          <Select label="Industry" value={f.industry} onChange={set("industry")} options={INDUSTRIES} testId="talent-industry" />
          <Input label="Current designation" value={f.designation} onChange={set("designation")} />
          <Input label="Skills (comma separated)" value={f.skills} onChange={set("skills")} />
          <Input label="Tools" value={f.tools} onChange={set("tools")} />
          <Select label="Has resume" value={f.has_resume} onChange={set("has_resume")} options={[["yes", "Yes"], ["no", "No"]]} testId="talent-has-resume" />
        </div>
        {more ? (
          <div className="grid gap-3 md:grid-cols-4" data-testid="talent-more">
            <Input label="Preferred designation" value={f.preferred_designation} onChange={set("preferred_designation")} />
            <Input label="Current company" value={f.company} onChange={set("company")} />
            <Input label="Min experience (yrs)" value={f.min_exp} onChange={set("min_exp")} inputMode="decimal" />
            <Input label="Max experience (yrs)" value={f.max_exp} onChange={set("max_exp")} inputMode="decimal" />
            <Input label="Min relevant exp. (yrs)" value={f.min_rel_exp} onChange={set("min_rel_exp")} inputMode="decimal" />
            <Input label="Max relevant exp. (yrs)" value={f.max_rel_exp} onChange={set("max_rel_exp")} inputMode="decimal" />
            <Input label="Current CTC contains" placeholder="e.g. LPA" value={f.current_ctc} onChange={set("current_ctc")} />
            <Select label="Notice period" value={f.notice_period} onChange={set("notice_period")} options={NOTICE_PERIODS} />
            <Input label="Min expected CTC (full amount)" value={f.min_ectc} onChange={set("min_ectc")} inputMode="numeric" />
            <Input label="Max expected CTC (full amount)" value={f.max_ectc} onChange={set("max_ectc")} inputMode="numeric" />
            <Input label="Current location" value={f.current_location} onChange={set("current_location")} />
            <Input label="Preferred location" value={f.preferred_location} onChange={set("preferred_location")} />
            <Input label="Preferred country" value={f.preferred_country} onChange={set("preferred_country")} />
            <Select label="Work mode" value={f.work_mode} onChange={set("work_mode")} options={PREF_WORK_MODES} />
            <Select label="Education" value={f.education} onChange={set("education")} options={EDUCATION} />
            <Input label="Certification" value={f.certification} onChange={set("certification")} />
            <Select label="Profile" value={f.profile} onChange={set("profile")} options={[["complete", "Complete"], ["incomplete", "Incomplete"]]} />
            <label className="flex items-end gap-2 pb-3 text-sm font-semibold"><Switch checked={f.outdated === "yes"} onChange={(v) => set("outdated")(v ? "yes" : "")} /> Outdated resumes only</label>
            <Input label="Registered from" type="date" value={f.registered_from} onChange={set("registered_from")} />
            <Input label="Registered to" type="date" value={f.registered_to} onChange={set("registered_to")} />
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button title="Search" onClick={search} loading={isFetching} data-testid="talent-search" />
          <Button variant="ghost" title={more ? "Fewer filters" : "More filters"} onClick={() => setMore((m) => !m)} data-testid="talent-more-toggle" />
          <Button variant="ghost" title="Reset" onClick={reset} />
        </div>
        <p className="text-xs text-gray-400">Only candidates who opted in to recruiter search are listed. Withdrawn consent removes them immediately.</p>
      </Card>
      {error ? <p className="text-red-600">{errMsg(error)}</p> : !data ? <Spinner /> : !data.candidates.length ? <EmptyState title="No candidates match" subtitle="Try fewer filters." /> : (
        <>
          <div className="overflow-x-auto rounded-2xl border border-gray-200 bg-white">
            <table className="w-full" data-testid="talent-table">
              <thead className="border-b border-gray-100 bg-gray-50/60"><tr><Th>Candidate</Th><Th>Current role</Th><Th>Experience</Th><Th>Skills & tools</Th><Th>Location</Th><Th>Resume</Th></tr></thead>
              <tbody className="divide-y divide-gray-100">
                {data.candidates.map((c) => (
                  <tr key={c.user_id} className="cursor-pointer hover:bg-brand-mist/40" onClick={() => setOpenId(c.user_id)} data-testid={`talent-row-${c.user_id}`}>
                    <Td><p className="font-bold text-gray-900">{c.full_name}</p><p className="text-gray-500">{c.email}</p></Td>
                    <Td>{c.current_designation || "—"}<br /><span className="text-gray-500">{c.current_company || ""}</span></Td>
                    <Td>{c.total_experience ?? "—"} yrs<br /><span className="text-gray-500">{c.notice_period || ""}</span></Td>
                    <Td className="max-w-xs text-gray-600">{[...(c.primary_skills || []), ...(c.tools || [])].slice(0, 6).join(", ") || "—"}</Td>
                    <Td>{c.current_location || list(c.preferred_locations?.length ? c.preferred_locations : c.preferred_location)}</Td>
                    <Td>{c.has_resume ? <><Badge label={c.resume_outdated ? "Outdated" : "Yes"} color={c.resume_outdated ? "warning" : "success"} /><br /><span className="text-xs text-gray-500">{formatDate(c.resume_uploaded_at)}</span></> : <Badge label="No" />}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 flex items-center justify-between text-sm">
            <span>Page {page} of {pages}</span>
            <span className="flex gap-2">
              <Button size="sm" variant="outline" title="Previous" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} />
              <Button size="sm" variant="outline" title="Next" disabled={page >= pages} onClick={() => setPage((p) => p + 1)} />
            </span>
          </div>
        </>
      )}
      <CandidateModal id={openId} onClose={() => setOpenId(null)} />
    </>
  );
}

export function AdminResumeStorage() {
  const { data, refetch, isFetching } = useQuery({ queryKey: ["admin-storage"], queryFn: () => api("/admin/storage/status") });
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (data) setS({ uploads_enabled: data.uploads_enabled, max_mb: data.max_mb, outdated_months: data.outdated_months }); }, [data]);
  const save = async () => {
    setSaving(true);
    try {
      await api("/admin/resumes/settings", { method: "PUT", body: { ...s, max_mb: Number(s.max_mb), outdated_months: Number(s.outdated_months) } });
      await refetch();
      notify("Resume settings saved", "success");
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setSaving(false);
    }
  };
  if (!data || !s) return <Spinner />;
  return (
    <>
      <PageHeader title="Resume Uploads & Storage" right={<Button variant="outline" title="Re-check storage" loading={isFetching} onClick={() => refetch()} />} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="space-y-4" data-testid="storage-status">
          <p className="h-sec">Storage</p>
          <p className="text-sm">Provider: <b>{data.backend === "local" ? "Local folder (development only)" : "Emergent object storage"}</b> · {data.reachable
            ? <Badge label="Reachable" color="success" /> : <Badge label="Not reachable" color="error" />}</p>
          {data.error ? <p className="text-xs text-red-600">{data.error}</p> : null}
          <div className="grid grid-cols-2 gap-3">
            {[["Resume files", data.resume_files], ["Resume storage", bytes(data.resume_bytes)], ["Evidence files", data.evidence_files], ["Total stored", bytes(data.total_bytes)]].map(([l, v]) => (
              <div key={l} className="rounded-xl bg-brand-mist p-4"><p className="text-2xl font-extrabold text-brand">{v}</p><p className="text-xs font-semibold text-gray-500">{l}</p></div>
            ))}
          </div>
          <p className="text-xs text-gray-500">Processing: {Object.entries(data.by_status || {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "no resumes yet"}</p>
          <p className="text-xs text-gray-500">{data.note}</p>
          <p className="text-xs text-gray-500">Deleted resumes are made permanently unreadable: each file is encrypted with its own key, and deleting it destroys the key and overwrites the stored file.</p>
        </Card>
        <Card className="space-y-4" data-testid="resume-settings">
          <p className="h-sec">Resume upload settings</p>
          <label className="flex items-center justify-between gap-4 rounded-xl bg-brand-mist p-4 text-sm font-semibold">Resume uploads enabled
            <Switch checked={s.uploads_enabled} onChange={(v) => setS((x) => ({ ...x, uploads_enabled: v }))} data-testid="resume-uploads-switch" /></label>
          {!s.uploads_enabled ? <p className="text-xs text-amber-700">Turn on only after confirming the storage quota with Emergent.</p> : null}
          <Input label="Maximum file size (MB)" inputMode="decimal" value={String(s.max_mb)} onChange={(e) => setS((x) => ({ ...x, max_mb: e.target.value }))} data-testid="resume-max-mb" />
          <Input label="Mark resumes outdated after (months)" inputMode="numeric" value={String(s.outdated_months)} onChange={(e) => setS((x) => ({ ...x, outdated_months: e.target.value }))} />
          <Button title="Save settings" loading={saving} onClick={save} data-testid="resume-settings-save" />
        </Card>
      </div>
    </>
  );
}
