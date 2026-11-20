import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronUp, Download, History } from "lucide-react";
import { api, downloadFile } from "@/lib/api";
import { formatDate, MATCH_STATUS_LABEL, scoreColor } from "@/lib/constants";
import { Badge, Button, Card, EmptyState, errMsg, Input, Modal, notify, Spinner } from "@/components/kit";

const COMP_LABEL = { skills: "Skills & tools", designation: "Designation", experience: "Experience", industry: "Industry",
  location: "Location", salary: "Salary", work_mode: "Work mode" };

export function ScoreBreakdown({ m }) {
  return (
    <div className="grid gap-4 rounded-xl bg-brand-mist/60 p-4 text-sm lg:grid-cols-[1fr_1fr]" data-testid={`breakdown-${m.match_id}`}>
      <div className="space-y-1.5">
        {Object.entries(m.components).map(([k, c]) => (
          <div key={k} className="flex items-center gap-3" data-testid={`comp-${k}-${m.match_id}`}>
            <span className="w-28 shrink-0 font-semibold text-gray-700">{COMP_LABEL[k]}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-white"><div className="h-full bg-brand" style={{ width: `${(c.score / c.max) * 100}%` }} /></div>
            <span className="w-14 shrink-0 text-right font-bold">{c.score}/{c.max}</span>
            <span className={`w-52 shrink-0 truncate text-xs ${c.assessed ? "text-gray-500" : "text-amber-700"}`} title={c.detail}>{c.assessed ? c.detail : `Not assessed: ${c.detail}`}</span>
          </div>
        ))}
      </div>
      <div className="space-y-2">
        <p className="font-bold">Why it matches</p>
        {m.explanation.length ? <ul className="list-disc pl-5 text-gray-600">{m.explanation.map((x) => <li key={x}>{x}</li>)}</ul> : <p className="text-gray-500">No strong match reasons.</p>}
        {m.flags.length ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs text-red-700">
            <p className="mb-1 flex items-center gap-1 font-bold"><AlertTriangle className="h-3.5 w-3.5" />Mandatory checks (not overridden by score)</p>
            {m.flags.map((f) => <p key={f}>• {f}</p>)}
          </div>
        ) : null}
        {m.missing_preferred_skills?.length ? <p className="text-xs text-gray-500">Missing preferred skills: {m.missing_preferred_skills.join(", ")}</p> : null}
        {m.provisional ? <p className="text-xs text-amber-700">Provisional score — missing data: {m.missing_data.join(", ")}</p> : null}
        <p className="text-[11px] text-gray-400">Advisory compatibility indicator, not a probability of selection.</p>
      </div>
    </div>
  );
}

function HistoryModal({ m, onClose }) {
  const { data } = useQuery({ queryKey: ["match-history", m.match_id], queryFn: () => api(`/admin/smartmatch/matches/${m.match_id}/history`) });
  return (
    <Modal open onClose={onClose} wide>
      <div className="flex items-center justify-between"><p className="text-xl font-extrabold">Match history</p>
        <button onClick={onClose} className="text-sm font-bold text-gray-500 hover:text-brand" data-testid="history-close">Close</button></div>
      <p className="muted">{m.candidate?.full_name} · {m.job_title} at {m.company}</p>
      {!data ? <Spinner /> : (
        <div className="mt-4 grid gap-6 md:grid-cols-2 text-sm">
          <div>
            <p className="label mb-2">Review trail</p>
            {data.reviews.length === 0 ? <p className="text-gray-500">No actions yet.</p> : data.reviews.map((r) => (
              <p key={r.review_id} className="border-b border-gray-100 py-1.5">
                <b>{MATCH_STATUS_LABEL[r.to_status]}</b> · {r.by_role === "admin" ? "admin" : "candidate"} · {new Date(r.at).toLocaleString("en-IN")}
                {r.note ? <span className="block text-xs text-gray-500">{r.note}</span> : null}
              </p>
            ))}
          </div>
          <div>
            <p className="label mb-2">Previous scores</p>
            {data.score_history.length === 0 ? <p className="text-gray-500">Score unchanged since first match.</p> : data.score_history.map((h, i) => (
              <p key={i} className="py-1">{h.match_score} · {formatDate(h.scored_at)}</p>
            ))}
            <p className="label mb-2 mt-4">Notifications</p>
            {data.notifications.length === 0 ? <p className="text-gray-500">None sent.</p> : data.notifications.map((n) => (
              <p key={n.notification_id} className="py-1">{n.channel === "email" ? "Email" : "In-app"} · {n.status}{n.sent_at ? ` · ${formatDate(n.sent_at)}` : ""}</p>
            ))}
          </div>
        </div>
      )}
    </Modal>
  );
}

function ReasonModal({ title, needReason, onSubmit, onClose }) {
  const [text, setText] = useState("");
  return (
    <Modal open onClose={onClose}>
      <p className="text-xl font-extrabold">{title}</p>
      <Input className="mt-4" multiline rows={3} label={needReason ? "Reason (required)" : "Internal comment"} value={text} onChange={(e) => setText(e.target.value)} data-testid="reason-input" />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="ghost" title="Cancel" onClick={onClose} data-testid="reason-cancel" />
        <Button title="Save" disabled={needReason && !text.trim()} onClick={() => onSubmit(text)} data-testid="reason-submit" />
      </div>
    </Modal>
  );
}

function ShareModal({ ids, onClose, onDone, defaultChannels }) {
  const [channels, setChannels] = useState(defaultChannels || ["in_app", "email"]);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState(null);
  const toggle = (c) => setChannels((x) => (x.includes(c) ? x.filter((y) => y !== c) : [...x, c]));
  const send = async () => {
    setBusy(true);
    try {
      const res = await api("/admin/smartmatch/matches/share", { method: "POST", body: { match_ids: ids, channels } });
      setResults(res.results);
      onDone();
    } catch (e) {
      notify(errMsg(e), "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={onClose}>
      <p className="text-xl font-extrabold">Send job alert</p>
      <p className="muted mt-1">{ids.length} approved match{ids.length === 1 ? "" : "es"}. Opted-out candidates and low-relevance matches (score under 50) are skipped; email goes only to candidates who turned alerts on; duplicates are skipped automatically.</p>
      <div className="mt-4 space-y-2 text-sm">
        {[["in_app", "In-app notification"], ["email", "Email"]].map(([k, l]) => (
          <label key={k} className="flex items-center gap-3"><input type="checkbox" checked={channels.includes(k)} onChange={() => toggle(k)} className="h-4 w-4 accent-[#7C3AED]" data-testid={`share-channel-${k}`} />{l}</label>
        ))}
        <p className="text-xs text-gray-400">WhatsApp is not available — no approved WhatsApp Business provider is configured.</p>
      </div>
      {results ? (
        <div className="mt-4 max-h-48 space-y-1 overflow-auto rounded-lg bg-gray-50 p-3 text-xs" data-testid="share-results">
          {results.map((r, i) => <p key={i}><b className={r.result === "sent" ? "text-emerald-700" : r.result === "failed" ? "text-red-600" : "text-amber-700"}>{r.result}</b> {r.channel ? `(${r.channel})` : ""} {r.reason || ""}</p>)}
        </div>
      ) : null}
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="ghost" title={results ? "Close" : "Cancel"} onClick={onClose} data-testid="share-close" />
        {!results ? <Button title="Send" loading={busy} disabled={!channels.length} onClick={send} data-testid="share-send" /> : null}
      </div>
    </Modal>
  );
}

export function MatchTable({ filters, mode = "job", title, defaultChannels, readOnly }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState(null);
  const [sel, setSel] = useState([]);
  const [dialog, setDialog] = useState(null);
  const query = { ...filters, page, page_size: 25 };
  const { data, isLoading } = useQuery({ queryKey: ["sm-matches", query], queryFn: () => api("/admin/smartmatch/matches", { query }) });
  const rows = data?.matches || [];
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const refresh = () => ["sm-matches", "sm-analytics", "am-jobs", "am-recipients"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const review = async (ids, action, extra = {}) => {
    try {
      const res = await api("/admin/smartmatch/matches/review", { method: "POST", body: { match_ids: ids, action, ...extra } });
      notify(`${res.updated} updated${res.skipped.length ? ` · ${res.skipped.length} skipped (${res.skipped[0].reason})` : ""}`, res.skipped.length ? "info" : "success");
      setSel([]);
      setDialog(null);
      refresh();
    } catch (e) {
      notify(errMsg(e), "error");
    }
  };
  const toggle = (id) => setSel((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const approvedSel = rows.filter((m) => sel.includes(m.match_id) && ["approved", "shared"].includes(m.status)).map((m) => m.match_id);
  return (
    <Card className="p-0" data-testid="match-table">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 p-5">
        <p className="h-sec">{title || "Matches"} {data ? <span className="text-sm font-semibold text-gray-400">({data.total})</span> : null}</p>
        <div className={`flex flex-wrap gap-2 ${readOnly ? "hidden" : ""}`}>
          <Button size="sm" variant="secondary" title={`Approve selected (${sel.length})`} disabled={!sel.length} onClick={() => review(sel, "approve")} data-testid="bulk-approve" />
          <Button size="sm" variant="outline" title={`Send alert (${approvedSel.length})`} disabled={!approvedSel.length} onClick={() => setDialog({ type: "share", ids: approvedSel })} data-testid="bulk-share" />
          <Button size="sm" variant="ghost" title="Export CSV" icon={<Download className="h-4 w-4" />} data-testid="matches-export"
            onClick={() => downloadFile("/admin/smartmatch/matches/export", filters, "smartmatch-matches.csv").catch((e) => notify(errMsg(e), "error"))} />
        </div>
      </div>
      {isLoading ? <Spinner /> : rows.length === 0 ? <div className="p-6"><EmptyState title="No matches yet" subtitle={mode === "review" ? "Run Find Matching Candidates on a job first." : "Click the Find button above to calculate matches."} /></div> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50/70 text-left text-xs uppercase tracking-wider text-gray-400">
              <tr>
                <th className="w-10 px-4 py-3"><input type="checkbox" checked={sel.length === rows.length} onChange={() => setSel(sel.length === rows.length ? [] : rows.map((m) => m.match_id))} className="accent-[#7C3AED]" data-testid="select-all" /></th>
                <th className="px-3">{mode === "candidate" ? "Job" : "Candidate"}</th>
                {mode === "review" ? <th className="px-3">Job</th> : null}
                <th className="px-3">Experience · CTC</th>
                <th className="px-3">Skills · Location · Notice</th>
                <th className="px-3">Score</th>
                <th className="px-3">Review status</th>
                <th className="px-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rows.map((m) => {
                const c = m.candidate || {};
                const jobCell = (
                  <button onClick={() => navigate(`/admin/smartmatch/job/${m.job_id}`)} className="text-left">
                    <p className="font-bold hover:text-brand">{m.job_title}</p><p className="text-xs text-gray-500">{m.company} · {m.job_location} · {m.job_id}</p>
                  </button>
                );
                const candCell = (
                  <button onClick={() => navigate(`/admin/smartmatch/candidate/${m.candidate_id}`)} className="text-left">
                    <p className="font-bold hover:text-brand">{c.full_name || "—"}</p>
                    <p className="text-xs text-gray-500">{m.candidate_id} · {c.current_designation || "No designation"}</p>
                    <p className={`text-[11px] font-semibold ${c.alert_pref === "opted_out" ? "text-red-600" : c.alert_pref === "enabled" ? "text-emerald-700" : "text-gray-400"}`}>
                      {{ enabled: "Job alerts on", none: "No preference (in-app only)", opted_out: "Opted out" }[c.alert_pref]} · {c.completion}% profile</p>
                  </button>
                );
                return (
                  <React.Fragment key={m.match_id}>
                    <tr className="align-top" data-testid={`match-row-${m.match_id}`}>
                      <td className="px-4 py-3"><input type="checkbox" checked={sel.includes(m.match_id)} onChange={() => toggle(m.match_id)} className="accent-[#7C3AED]" data-testid={`select-${m.match_id}`} /></td>
                      <td className="px-3 py-3">{mode === "candidate" ? jobCell : candCell}</td>
                      {mode === "review" ? <td className="px-3 py-3">{jobCell}</td> : null}
                      <td className="px-3 py-3 text-xs text-gray-600">{c.total_experience ?? "—"} yrs<br />Now: {c.current_salary || "—"}<br />Expects: {c.expected_ctc ? `${c.expected_ctc_currency} ${Number(c.expected_ctc).toLocaleString("en-IN")}` : "—"}</td>
                      <td className="max-w-[220px] px-3 py-3 text-xs text-gray-600">
                        <p className="truncate" title={(c.primary_skills || []).join(", ")}>{(c.primary_skills || []).join(", ") || "No skills"}</p>
                        <p className="truncate">{(c.preferred_locations || []).join(", ") || "—"}</p><p>{c.notice_period || "Notice —"}</p>
                      </td>
                      <td className="px-3 py-3">
                        <p className="text-2xl font-extrabold text-brand" data-testid={`score-${m.match_id}`}>{m.match_score}</p>
                        <Badge label={m.category} color={scoreColor(m.match_score)} />
                        {m.provisional ? <p className="mt-1 text-[11px] font-semibold text-amber-700">Provisional</p> : null}
                        {m.mandatory_gap ? <p className="text-[11px] font-semibold text-red-600">Mandatory skill gap</p> : null}
                      </td>
                      <td className="px-3 py-3">
                        <Badge label={m.status_label} color={m.status === "rejected" ? "error" : ["approved", "shared"].includes(m.status) ? "success" : "info"} data-testid={`status-${m.match_id}`} />
                        {!m.job_eligible ? <p className="mt-1 text-[11px] text-red-600">Job no longer eligible</p> : null}
                        {m.rejection_reason ? <p className="mt-1 text-[11px] text-gray-500">Reason: {m.rejection_reason}</p> : null}
                        {m.admin_comment ? <p className="mt-1 text-[11px] text-gray-500">Note: {m.admin_comment}</p> : null}
                        <div className="mt-1 flex flex-wrap gap-1">
                          {m.contacted_at ? <Badge label="Contacted" color="brand" data-testid={`contacted-${m.match_id}`} /> : null}
                          {m.shortlisted_at ? <Badge label="Shortlisted" color="success" data-testid={`shortlisted-${m.match_id}`} /> : null}
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex flex-wrap gap-1">
                          {readOnly ? <span className="w-full text-[11px] font-semibold text-red-600">Opted out — view only</span> : null}
                          <Button size="sm" variant="ghost" title="Why" icon={open === m.match_id ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />} onClick={() => setOpen(open === m.match_id ? null : m.match_id)} data-testid={`why-${m.match_id}`} />
                          {!readOnly && ["suggested", "pending_review", "rejected"].includes(m.status) ? <Button size="sm" variant="secondary" title="Approve" onClick={() => review([m.match_id], "approve")} data-testid={`approve-${m.match_id}`} /> : null}
                          {!readOnly && ["suggested", "pending_review", "approved"].includes(m.status) ? <Button size="sm" variant="ghost" title="Reject" className="!text-red-600" onClick={() => setDialog({ type: "reject", ids: [m.match_id] })} data-testid={`reject-${m.match_id}`} /> : null}
                          {!readOnly && m.status === "suggested" ? <Button size="sm" variant="ghost" title="Mark pending review" onClick={() => review([m.match_id], "pending_review")} data-testid={`pending-${m.match_id}`} /> : null}
                          {!readOnly && ["approved", "shared"].includes(m.status) ? <Button size="sm" variant="outline" title="Send alert" onClick={() => setDialog({ type: "share", ids: [m.match_id] })} data-testid={`share-${m.match_id}`} /> : null}
                          {readOnly ? null : <Button size="sm" variant="ghost" title="Comment" onClick={() => setDialog({ type: "comment", ids: [m.match_id] })} data-testid={`comment-${m.match_id}`} />}
                          {readOnly ? null : <Button size="sm" variant="ghost" title={m.contacted_at ? "Unmark contacted" : "Mark contacted"} onClick={() => review([m.match_id], m.contacted_at ? "unmark_contacted" : "mark_contacted")} data-testid={`mark-contacted-${m.match_id}`} />}
                          {readOnly ? null : <Button size="sm" variant="ghost" title={m.shortlisted_at ? "Unshortlist" : "Shortlist"} onClick={() => review([m.match_id], m.shortlisted_at ? "unmark_shortlisted" : "mark_shortlisted")} data-testid={`mark-shortlisted-${m.match_id}`} />}
                          <Button size="sm" variant="ghost" title="" icon={<History className="h-3.5 w-3.5" />} onClick={() => setDialog({ type: "history", m })} data-testid={`history-${m.match_id}`} />
                        </div>
                      </td>
                    </tr>
                    {open === m.match_id ? <tr><td colSpan={8} className="px-4 pb-4"><ScoreBreakdown m={m} /></td></tr> : null}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 ? (
        <div className="flex items-center justify-end gap-3 border-t border-gray-100 p-4 text-sm">
          <Button size="sm" variant="ghost" title="‹ Prev" disabled={page <= 1} onClick={() => setPage(page - 1)} data-testid="page-prev" />
          <span data-testid="page-info">Page {page} of {pages}</span>
          <Button size="sm" variant="ghost" title="Next ›" disabled={page >= pages} onClick={() => setPage(page + 1)} data-testid="page-next" />
        </div>
      ) : null}
      {dialog?.type === "reject" ? <ReasonModal title="Reject match" needReason onClose={() => setDialog(null)} onSubmit={(t) => review(dialog.ids, "reject", { rejection_reason: t })} /> : null}
      {dialog?.type === "comment" ? <ReasonModal title="Internal comment" onClose={() => setDialog(null)} onSubmit={(t) => review(dialog.ids, "comment", { comment: t })} /> : null}
      {dialog?.type === "share" ? <ShareModal ids={dialog.ids} defaultChannels={defaultChannels} onClose={() => setDialog(null)} onDone={refresh} /> : null}
      {dialog?.type === "history" ? <HistoryModal m={dialog.m} onClose={() => setDialog(null)} /> : null}
    </Card>
  );
}
