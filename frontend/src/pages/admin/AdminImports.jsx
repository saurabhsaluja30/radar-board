import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { api } from "@/lib/api";
import { formatDate, INDUSTRIES_WITH_OTHER as CATEGORIES } from "@/lib/constants";
import { Badge, Button, Card, EmptyState, errMsg, Input, Modal, notify, PageHeader, Spinner, Switch } from "@/components/kit";

const Th = ({ children }) => <th className="px-4 py-3 text-left text-xs font-bold uppercase tracking-wide text-gray-400">{children}</th>;
const Td = ({ children, className = "" }) => <td className={`px-4 py-3.5 align-top text-sm ${className}`}>{children}</td>;
const RUN_COLOR = { SUCCEEDED: "success", FAILED: "error", ABORTED: "error", "TIMED-OUT": "error", RUNNING: "warning", READY: "warning", STARTING: "warning" };
const PERM_COLOR = { Approved: "success", "Pending review": "warning", "Not permitted": "error" };
const FLAG_LABEL = { incomplete: "Incomplete", suspicious: "Suspicious", old_posting: "Old posting", possible_duplicate: "Possible duplicate",
  closed_at_source: "Closed at source", source_changed: "Changed at source" };
const REVIEW_TABS = [["new_import", "New imports"], ["pending_review", "Pending review"], ["approved", "Approved"], ["rejected", "Rejected"], ["archived", "Archived"], ["All", "All"]];
const usd = (n) => `$${Number(n || 0).toFixed(n < 1 ? 3 : 2)}`;
const toList = (s) => (Array.isArray(s) ? s : String(s || "").split(",").map((x) => x.trim()).filter(Boolean));
const EMPTY_SRC = { name: "", url: "", source_type: "Employer career page", permission_status: "Pending review", permission_note: "",
  enabled: false, frequency: "daily", category: "", keywords: "", locations: "" };

function Field({ label, children }) {
  return <label className="block"><span className="label">{label}</span><div className="mt-1.5">{children}</div></label>;
}

function SourceModal({ src, options, onClose, onSaved }) {
  const [f, setF] = useState(EMPTY_SRC);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (src) setF({ ...EMPTY_SRC, ...src, category: src.category || "", keywords: toList(src.keywords).join(", "), locations: toList(src.locations).join(", ") }); }, [src]);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e?.target ? e.target.value : e }));
  const save = async () => {
    setBusy(true);
    try {
      const body = { ...f, category: f.category || null, keywords: toList(f.keywords), locations: toList(f.locations) };
      ["source_id", "date_added", "last_checked_at", "last_success_at", "jobs_imported", "failed_attempts", "last_error", "added_by",
        "updated_at", "jobs_total", "jobs_awaiting", "jobs_published"].forEach((k) => delete body[k]);
      if (src?.source_id) await api(`/admin/sources/${src.source_id}`, { method: "PUT", body });
      else await api("/admin/sources", { method: "POST", body });
      notify("Source saved", "success");
      onSaved();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={!!src} onClose={onClose} wide>
      <div className="space-y-4" data-testid="source-modal">
        <p className="h-sec">{src?.source_id ? "Edit job source" : "Add approved job source"}</p>
        <div className="grid gap-3 md:grid-cols-2">
          <Input label="Source name" placeholder="e.g. Acme Careers" value={f.name} onChange={set("name")} data-testid="src-name" />
          <Input label="Source URL" placeholder="https://job-boards.greenhouse.io/acme" value={f.url} onChange={set("url")} data-testid="src-url" />
          <Field label="Source type"><select className="field" value={f.source_type} onChange={set("source_type")}>{options.source_types.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Permission status"><select className="field" value={f.permission_status} onChange={set("permission_status")} data-testid="src-permission">{options.permission.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Input className="md:col-span-2" label="Permission / authorisation note" placeholder="e.g. Public Greenhouse job board; terms allow reuse" value={f.permission_note} onChange={set("permission_note")} />
          <Field label="Collection frequency"><select className="field" value={f.frequency} onChange={set("frequency")}>{options.frequency.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="Job category for imports"><select className="field" value={f.category} onChange={set("category")}><option value="">Set during review</option>{CATEGORIES.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Input label="Job-title keywords (optional)" placeholder="Leave empty to use the defaults" value={f.keywords} onChange={set("keywords")} />
          <Input label="Locations (optional)" placeholder="e.g. India, Dubai" value={f.locations} onChange={set("locations")} />
        </div>
        <label className="flex items-center justify-between rounded-xl bg-brand-mist p-4 text-sm font-semibold">Enabled for collection
          <Switch checked={f.enabled} onChange={set("enabled")} data-testid="src-enabled" /></label>
        <p className="text-xs text-gray-500">Only add sources that permit automated collection: an employer's own careers page or job board, an authorised API or feed, or a licensed provider. LinkedIn, Naukri and similar portals can't be added without a licence.</p>
        <Button title="Save source" loading={busy} onClick={save} data-testid="src-save" />
      </div>
    </Modal>
  );
}

function SettingsCard({ ov, onSaved }) {
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => setS({ ...ov.settings, default_keywords: ov.settings.default_keywords.join(", "), default_locations: ov.settings.default_locations.join(", ") }), [ov.settings]);
  if (!s) return null;
  const set = (k) => (e) => setS((x) => ({ ...x, [k]: e?.target ? e.target.value : e }));
  const save = async () => {
    setBusy(true);
    try {
      await api("/admin/apify/settings", { method: "PUT", body: { ...s, default_keywords: toList(s.default_keywords), default_locations: toList(s.default_locations),
        max_items_per_run: Number(s.max_items_per_run), max_items_per_company: Number(s.max_items_per_company), posted_within_days: Number(s.posted_within_days),
        monthly_budget_usd: Number(s.monthly_budget_usd), per_run_cap_usd: Number(s.per_run_cap_usd) } });
      notify("Apify settings saved", "success");
      onSaved();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  const preset = ov.presets[s.actor_id];
  return (
    <Card className="space-y-4" data-testid="apify-settings">
      <p className="h-sec">Apify settings</p>
      <Field label="Actor">
        <select className="field" value={ov.presets[s.actor_id] ? s.actor_id : "custom"} onChange={(e) => e.target.value !== "custom" && set("actor_id")(e.target.value)}>
          {Object.entries(ov.presets).map(([k, v]) => <option key={k} value={k}>{v.label} — {k} (${v.price_per_item_usd}/job)</option>)}
          {!preset ? <option value="custom">{s.actor_id}</option> : null}
        </select>
      </Field>
      <div className="grid gap-3 md:grid-cols-2">
        <Input label="Default job-title keywords" value={s.default_keywords} onChange={set("default_keywords")} />
        <Input label="Default locations" value={s.default_locations} onChange={set("default_locations")} />
        <Input label="Max jobs per run" inputMode="numeric" value={String(s.max_items_per_run)} onChange={set("max_items_per_run")} />
        <Input label="Max jobs per company" inputMode="numeric" value={String(s.max_items_per_company)} onChange={set("max_items_per_company")} />
        <Input label="Only jobs posted in the last (days)" inputMode="numeric" value={String(s.posted_within_days)} onChange={set("posted_within_days")} />
        <Input label="Monthly budget (USD)" inputMode="decimal" value={String(s.monthly_budget_usd)} onChange={set("monthly_budget_usd")} data-testid="apify-budget" />
        <Input label="Cap per run (USD)" inputMode="decimal" value={String(s.per_run_cap_usd)} onChange={set("per_run_cap_usd")} />
      </div>
      <label className="flex items-center justify-between rounded-xl bg-brand-mist p-4 text-sm font-semibold">Run the daily collection automatically
        <Switch checked={s.auto_daily} onChange={set("auto_daily")} /></label>
      <label className="flex items-start justify-between gap-4 rounded-xl border-2 border-amber-200 bg-amber-50 p-4 text-sm">
        <span><b>Approve paid Apify runs</b><br /><span className="text-xs text-gray-600">This Actor charges per job returned. Nothing runs until this is on, and spending stops at the monthly budget.</span></span>
        <Switch checked={s.paid_runs_approved} onChange={set("paid_runs_approved")} data-testid="apify-approve" /></label>
      <Button title="Save settings" loading={busy} onClick={save} data-testid="apify-settings-save" />
    </Card>
  );
}

export function AdminJobSources() {
  const ov = useQuery({ queryKey: ["apify-overview"], queryFn: () => api("/admin/apify/overview") });
  const srcQ = useQuery({ queryKey: ["job-sources"], queryFn: () => api("/admin/sources") });
  const [edit, setEdit] = useState(null);
  const [running, setRunning] = useState(false);
  const reload = () => { ov.refetch(); srcQ.refetch(); };
  const run = async (ids) => {
    setRunning(true);
    try {
      const res = await api("/admin/sources/run", { method: "POST", body: { source_ids: ids } });
      notify(`Collection started (${res.runs.length} run${res.runs.length > 1 ? "s" : ""}). Results import automatically when it finishes.`, "success");
      reload();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setRunning(false);
    }
  };
  const refreshRun = async (r) => {
    try {
      const res = await api(`/admin/apify/runs/${r.run_id}/refresh`, { method: "POST" });
      notify(res.run.processed || res.run.summary ? "Run imported" : `Run is ${res.run.status}`, "success");
      reload();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const d = ov.data;
  if (!d || !srcQ.data) return <Spinner />;
  const budgetPct = d.settings.monthly_budget_usd ? Math.min(100, (d.month_spend_usd / d.settings.monthly_budget_usd) * 100) : 0;
  return (
    <>
      <PageHeader title="Job Sources (Apify)" subtitle="Approved sources JobRadar collects jobs from"
        right={<div className="flex gap-2">
          <Button variant="outline" title="Run all now" loading={running} onClick={() => run([])} data-testid="sources-run-all" />
          <Button title="Add source" onClick={() => setEdit({ ...EMPTY_SRC })} data-testid="sources-add" />
        </div>} />
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5" data-testid="apify-stats">
        {[["Spent this month", `${usd(d.month_spend_usd)} of ${usd(d.settings.monthly_budget_usd)}`], ["Apify reports this cycle", d.apify_usage?.month_usage_usd != null ? usd(d.apify_usage.month_usage_usd) : "—"],
          ["Runs (ok / failed)", `${d.totals.ok || 0} / ${d.totals.failed || 0}`], ["Jobs imported", d.totals.imported || 0], ["Duplicates detected", d.totals.duplicates || 0]].map(([l, v]) => (
          <div key={l} className="rounded-xl bg-brand-mist p-4"><p className="text-xl font-extrabold text-brand">{v}</p><p className="text-xs font-semibold text-gray-500">{l}</p></div>
        ))}
      </div>
      <div className="mb-6 h-2 overflow-hidden rounded-full bg-brand-soft"><div className={`h-full ${budgetPct > 85 ? "bg-red-500" : "bg-brand"}`} style={{ width: `${budgetPct}%` }} /></div>
      {!d.token_configured ? <p className="mb-4 rounded-xl bg-red-50 p-3 text-sm text-red-700" data-testid="apify-no-token">Apify isn't connected. Add APIFY_TOKEN to the server's secrets.</p> : null}
      {!d.settings.paid_runs_approved ? <p className="mb-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">Paid runs aren't approved yet — nothing will be collected until you approve them in the settings below.</p> : null}
      {!d.webhook_configured ? <p className="mb-4 text-xs text-gray-500">Instant import after each run is off (set APIFY_WEBHOOK_SECRET and PUBLIC_BACKEND_URL). Finished runs are still imported by the daily job or the Check button.</p> : null}
      <Card className="mb-6 overflow-x-auto p-0" data-testid="sources-table">
        {!srcQ.data.sources.length ? <EmptyState title="No sources yet" subtitle="Add an employer's careers page or job board to start." /> : (
          <table className="w-full">
            <thead className="border-b border-gray-100 bg-gray-50/60"><tr><Th>Source</Th><Th>Permission</Th><Th>Frequency</Th><Th>Last checked / success</Th><Th>Jobs</Th><Th>Status</Th><Th /></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {srcQ.data.sources.map((x) => (
                <tr key={x.source_id} data-testid={`source-${x.source_id}`}>
                  <Td><p className="font-bold">{x.name}</p><a href={x.url} target="_blank" rel="noreferrer" className="text-xs text-brand hover:underline">{x.url}</a><p className="text-xs text-gray-500">{x.source_type} · added {formatDate(x.date_added)}</p></Td>
                  <Td><Badge label={x.permission_status} color={PERM_COLOR[x.permission_status]} />{x.permission_note ? <p className="mt-1 max-w-[14rem] text-xs text-gray-500">{x.permission_note}</p> : null}</Td>
                  <Td>{x.frequency}{x.category ? <p className="text-xs text-gray-500">{x.category}</p> : null}</Td>
                  <Td className="text-xs">{x.last_checked_at ? formatDate(x.last_checked_at) : "Never"}<br /><span className="text-gray-500">{x.last_success_at ? formatDate(x.last_success_at) : "—"}</span></Td>
                  <Td className="text-xs">{x.jobs_imported || 0} imported<br /><span className="text-gray-500">{x.jobs_awaiting} awaiting · {x.jobs_published} live</span></Td>
                  <Td>{x.enabled ? <Badge label="Enabled" color="success" /> : <Badge label="Off" />}{x.failed_attempts ? <p className="mt-1 text-xs text-red-600">{x.failed_attempts} failed: {x.last_error}</p> : null}</Td>
                  <Td><div className="flex gap-2">
                    <Button size="sm" variant="outline" title="Edit" onClick={() => setEdit(x)} />
                    {x.enabled ? <Button size="sm" variant="ghost" title="Run" onClick={() => run([x.source_id])} /> : null}
                  </div></Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <SettingsCard ov={d} onSaved={reload} />
        <Card className="space-y-3" data-testid="apify-runs">
          <p className="h-sec">Collection runs</p>
          {!d.runs.length ? <p className="text-sm text-gray-500">No runs yet.</p> : d.runs.map((r) => (
            <div key={r.run_id} className="rounded-xl border border-gray-100 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span><Badge label={r.status} color={RUN_COLOR[r.status] || "info"} /> <span className="text-gray-500">{formatDate(r.started_at)} · {r.trigger}</span></span>
                <span className="font-semibold">{r.cost_usd != null ? usd(r.cost_usd) : `≤ ${usd(r.cost_cap_usd)}`}</span>
              </div>
              {r.summary ? <p className="mt-1 text-xs text-gray-600">{r.summary.items} returned · {r.summary.created} new · {r.summary.updated} updated · {r.summary.duplicates} possible duplicates · {r.summary.closed} closed · {r.summary.skipped} skipped</p> : null}
              {r.error ? <p className="mt-1 text-xs text-red-600">{r.error}</p> : null}
              {!r.processed ? <button className="mt-1 text-xs font-semibold text-brand" onClick={() => refreshRun(r)}>Check status / import now</button> : null}
            </div>
          ))}
        </Card>
      </div>
      {edit ? <SourceModal src={edit} options={d.options} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} /> : null}
    </>
  );
}

function ImportDetail({ id, onClose }) {
  const { data } = useQuery({ queryKey: ["import", id], queryFn: () => api(`/admin/imports/${id}`), enabled: !!id });
  const j = data?.job;
  return (
    <Modal open={!!id} onClose={onClose} wide>
      {!j ? <Spinner /> : (
        <div className="space-y-4" data-testid="import-detail">
          <div>
            <p className="h-page">{j.title}</p>
            <p className="text-sm text-gray-500">{j.company} · {j.location || "location not given"} · {j.work_mode || "work mode not given"} · {j.employment_type || "type not given"}</p>
            <a href={j.original_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm font-semibold text-brand">View original listing <ExternalLink className="h-3.5 w-3.5" /></a>
          </div>
          <div className="flex flex-wrap gap-1">{(j.flags || []).map((f) => <Badge key={f} label={FLAG_LABEL[f] || f} color="warning" />)}</div>
          {data.duplicate_of ? <p className="rounded-xl bg-amber-50 p-3 text-sm">Possible duplicate of <b>{data.duplicate_of.title}</b> at {data.duplicate_of.company} ({data.duplicate_of.status}).</p> : null}
          {j.source_snapshot ? <p className="rounded-xl bg-amber-50 p-3 text-sm">The source changed this listing on {formatDate(j.source_snapshot.seen_at)}. Accept the change to replace your reviewed version.</p> : null}
          <div className="grid gap-2 text-sm md:grid-cols-2">
            <p><b>Source:</b> {j.source_name}</p><p><b>Posted:</b> {j.original_posted_at || "—"} · imported {formatDate(j.imported_at)}</p>
            <p><b>Skills found:</b> {j.required_skills || "—"}</p><p><b>Experience:</b> {j.experience_min ?? "—"}–{j.experience_max ?? "—"} yrs</p>
            <p><b>Salary:</b> {j.salary_range || (j.salary_min ? `${j.currency || ""} ${j.salary_min}–${j.salary_max || ""}` : "—")}</p><p><b>Deadline:</b> {j.application_deadline || "—"}</p>
          </div>
          <div className="max-h-64 overflow-y-auto whitespace-pre-wrap rounded-xl bg-gray-50 p-3 text-sm text-gray-700">{j.description || "No description"}</div>
          <div>
            <p className="mb-1 text-sm font-bold">Collection history</p>
            {data.history.map((h, i) => <p key={i} className="text-xs text-gray-600">{formatDate(h.at)} · {h.action}{h.reason ? ` (${h.reason})` : ""} · run {h.run_id}</p>)}
          </div>
        </div>
      )}
    </Modal>
  );
}

export function AdminImportReview() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("new_import");
  const [f, setF] = useState({ q: "", flag: "", source_id: "", industry: "All", location: "" });
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState([]);
  const [cat, setCat] = useState("");
  const [open, setOpen] = useState(null);
  const srcQ = useQuery({ queryKey: ["job-sources"], queryFn: () => api("/admin/sources") });
  const { data, refetch } = useQuery({ queryKey: ["imports", tab, f, page], queryFn: () => api("/admin/imports", { query: { review_status: tab, ...f, page } }) });
  useEffect(() => setSel([]), [tab, f, page]);
  const act = async (action, ids = sel) => {
    if (!ids.length) return notify("Select at least one job", "error");
    try {
      const res = await api("/admin/imports/action", { method: "POST", body: { job_ids: ids, action, industry_category: cat || null } });
      notify(`${res.done.length} updated${res.skipped.length ? ` · ${res.skipped.length} skipped: ${res.skipped[0].reason}` : ""}`, res.skipped.length ? "error" : "success");
      setSel([]);
      refetch();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const jobs = data?.jobs || [];
  const toggle = (id) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  return (
    <>
      <PageHeader title="Import Review" subtitle="Imported jobs stay hidden from candidates until you approve and publish them" />
      <div className="mb-4 flex flex-wrap gap-2" data-testid="import-tabs">
        {REVIEW_TABS.map(([k, l]) => (
          <button key={k} onClick={() => { setTab(k); setPage(1); }} className={`rounded-full px-4 py-1.5 text-sm font-semibold ${tab === k ? "bg-brand text-white" : "bg-brand-mist text-gray-700"}`}>
            {l}{k !== "All" && data?.counts?.[k] ? ` (${data.counts[k]})` : ""}
          </button>
        ))}
      </div>
      <Card className="mb-4 grid gap-3 md:grid-cols-5">
        <Input label="Title or company" value={f.q} onChange={(e) => setF((x) => ({ ...x, q: e.target.value }))} data-testid="import-q" />
        <Field label="Source"><select className="field" value={f.source_id} onChange={(e) => setF((x) => ({ ...x, source_id: e.target.value }))}>
          <option value="">All</option>{(srcQ.data?.sources || []).map((x) => <option key={x.source_id} value={x.source_id}>{x.name}</option>)}</select></Field>
        <Field label="Flag"><select className="field" value={f.flag} onChange={(e) => setF((x) => ({ ...x, flag: e.target.value }))}>
          <option value="">Any</option>{Object.entries(FLAG_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Industry"><select className="field" value={f.industry} onChange={(e) => setF((x) => ({ ...x, industry: e.target.value }))}>
          <option>All</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Input label="Location" value={f.location} onChange={(e) => setF((x) => ({ ...x, location: e.target.value }))} />
      </Card>
      <div className="mb-4 flex flex-wrap items-end gap-2" data-testid="import-actions">
        <Field label="Industry for selected"><select className="field" value={cat} onChange={(e) => setCat(e.target.value)} data-testid="import-category">
          <option value="">Keep current</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Button title="Approve & publish" onClick={() => act("publish")} data-testid="import-publish" />
        <Button variant="outline" title="Approve only" onClick={() => act("approve")} />
        <Button variant="outline" title="Mark pending review" onClick={() => act("pending_review")} />
        <Button variant="danger" title="Reject" onClick={() => act("reject")} data-testid="import-reject" />
        <Button variant="ghost" title="Archive" onClick={() => act("archive")} />
        <span className="text-sm text-gray-500">{sel.length} selected</span>
      </div>
      {!data ? <Spinner /> : !jobs.length ? <EmptyState title="Nothing here" subtitle="New imports appear after each collection run." /> : (
        <div className="overflow-x-auto rounded-2xl border border-gray-200 bg-white">
          <table className="w-full" data-testid="import-table">
            <thead className="border-b border-gray-100 bg-gray-50/60"><tr>
              <Th><input type="checkbox" checked={sel.length === jobs.length} onChange={(e) => setSel(e.target.checked ? jobs.map((j) => j.job_id) : [])} /></Th>
              <Th>Job</Th><Th>Location / mode</Th><Th>Source</Th><Th>Posted</Th><Th>Flags</Th><Th>Status</Th><Th /></tr></thead>
            <tbody className="divide-y divide-gray-100">
              {jobs.map((j) => (
                <tr key={j.job_id} data-testid={`import-row-${j.job_id}`}>
                  <Td><input type="checkbox" checked={sel.includes(j.job_id)} onChange={() => toggle(j.job_id)} data-testid={`import-select-${j.job_id}`} /></Td>
                  <Td><button className="text-left font-bold text-gray-900 hover:text-brand" onClick={() => setOpen(j.job_id)}>{j.title}</button><p className="text-gray-500">{j.company}</p></Td>
                  <Td>{j.location || "—"}<p className="text-xs text-gray-500">{j.work_mode || "—"}</p></Td>
                  <Td className="text-xs">{j.source_name}<br /><a href={j.original_url} target="_blank" rel="noreferrer" className="text-brand">Original ↗</a></Td>
                  <Td className="text-xs">{j.original_posted_at || "—"}</Td>
                  <Td><div className="flex max-w-[12rem] flex-wrap gap-1">{(j.flags || []).map((x) => <Badge key={x} label={FLAG_LABEL[x] || x} color="warning" />)}</div></Td>
                  <Td className="text-xs">{j.review_status.replace("_", " ")}<br /><span className="text-gray-500">{j.status} · {j.industry_category || "no industry"}</span></Td>
                  <Td><div className="flex flex-col gap-1">
                    <Button size="sm" variant="ghost" title="Edit" onClick={() => navigate(`/admin/job-edit?id=${j.job_id}`)} />
                    {(j.flags || []).includes("source_changed") ? <Button size="sm" variant="ghost" title="Accept change" onClick={() => act("accept_source_change", [j.job_id])} /> : null}
                  </div></Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && data.total > 25 ? (
        <div className="mt-4 flex items-center justify-between text-sm">
          <span>Page {page} of {Math.ceil(data.total / 25)}</span>
          <span className="flex gap-2">
            <Button size="sm" variant="outline" title="Previous" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} />
            <Button size="sm" variant="outline" title="Next" disabled={page * 25 >= data.total} onClick={() => setPage((p) => p + 1)} />
          </span>
        </div>
      ) : null}
      <ImportDetail id={open} onClose={() => setOpen(null)} />
    </>
  );
}
