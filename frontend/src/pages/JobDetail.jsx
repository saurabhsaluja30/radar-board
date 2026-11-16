import React, { useEffect } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Briefcase, Building2, Link2, Lock, Mail, MapPin, Send, Star, User } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { formatDate } from "@/lib/constants";
import { Button, Card, notify, Spinner } from "@/components/kit";
import { useLaunchOffer } from "@/components/Membership";
import { Page } from "@/components/Layout";
import { TrackButton } from "@/pages/Tracker";

const KV = ({ label, value }) => (
  <div className="flex justify-between gap-4 border-b border-gray-100 py-2.5 text-sm last:border-0">
    <span className="text-gray-500">{label}</span>
    <span className="text-right font-semibold text-gray-800">{value || "—"}</span>
  </div>
);

const Block = ({ title, children }) => (
  <div className="mb-6">
    <h3 className="mb-2 font-extrabold text-gray-900">{title}</h3>
    <div className="whitespace-pre-line text-[15px] leading-relaxed text-gray-600">{children}</div>
  </div>
);

function Premium({ job }) {
  return (
    <Card className="p-8" data-testid="job-premium-details">
      <Block title="Job Description">{job.description}</Block>
      <Block title="Key Responsibilities">{job.key_responsibilities}</Block>
      <Block title="Required Skills">{job.required_skills}</Block>
      <Block title="Preferred Skills">{job.preferred_skills}</Block>
      <Block title="Salary Range">{job.salary_range || "Not disclosed"}</Block>
      {job.recruiter_name || job.recruiter_email ? (
        <div className="mb-6 rounded-xl bg-brand-mist p-4">
          <h3 className="mb-2 font-extrabold text-gray-900">Recruiter Information</h3>
          {job.recruiter_name ? <p className="flex items-center gap-2 text-sm"><User className="h-4 w-4 text-brand" />{job.recruiter_name}</p> : null}
          {job.recruiter_email ? <p className="mt-1 flex items-center gap-2 text-sm"><Mail className="h-4 w-4 text-brand" />{job.recruiter_email}</p> : null}
        </div>
      ) : null}
      {job.source_link ? (
        <a href={job.source_link} target="_blank" rel="noreferrer" className="flex items-center gap-2 text-sm font-bold text-brand hover:underline">
          <Link2 className="h-4 w-4" /> View source
        </a>
      ) : null}
      <p className="mt-6 text-xs text-gray-400">{job.disclaimer}</p>
    </Card>
  );
}

function Locked({ job, cta }) {
  return (
    <Card className="relative overflow-hidden p-8" data-testid="job-locked">
      <h3 className="mb-2 font-extrabold text-gray-900">Full Details</h3>
      <p className="line-clamp-2 text-gray-600">{job.preview}</p>
      <div className="mt-4 space-y-3">
        {[...Array(6)].map((_, i) => <div key={i} className="h-3 rounded bg-gray-200" style={{ width: `${90 - i * 8}%` }} />)}
      </div>
      <div className="absolute inset-0 top-20 flex flex-col items-center justify-center bg-white/60 px-8 text-center backdrop-blur-md">
        <Lock className="h-7 w-7 text-brand" />
        <p className="mt-3 text-lg font-extrabold text-gray-900">Premium Details Locked</p>
        <p className="mt-1 max-w-md text-sm text-gray-600">
          Full description, recruiter contact and direct application link are available to active members.
        </p>
        <Button className="mt-5" title={cta.full} onClick={cta.go} data-testid="job-unlock-btn" />
      </div>
    </Card>
  );
}

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, isMember } = useAuth();
  const { data: launch } = useLaunchOffer();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["job", id, user?.user_id], queryFn: () => api(`/jobs/${id}`, { auth: !!user }) });
  useEffect(() => {
    if (user?.role === "candidate" && data?.job) api("/smartmatch/activity", { method: "POST", body: { job_id: id } }).catch(() => {});
  }, [user?.role, data?.job, id]);
  const job = data?.job;
  if (isLoading || !job) return <Spinner />;
  const unlocked = isMember && !job.locked;
  const hidden = launch?.plans_hidden;
  const cta = {
    full: hidden ? (user ? "See My Access" : "Claim Free Access to View Full Details") : "Become a Member to View Full Details",
    short: hidden ? (user ? "See My Access" : "Claim Free Access") : "View Membership Plans",
    go: () => navigate(hidden ? (user ? "/membership" : "/auth/register") : "/plans"),
  };

  const toggleSave = async () => {
    if (!user) return navigate("/auth/login");
    try {
      if (job.is_saved) {
        await api(`/jobs/${id}/save`, { method: "DELETE" });
        notify("Removed from saved");
      } else {
        await api(`/jobs/${id}/save`, { method: "POST" });
        notify("Saved!", "success");
      }
      ["job", "saved-jobs", "jobs"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    } catch {
      notify("Something went wrong", "error");
    }
  };
  const apply = async () => {
    try {
      const res = await api(`/jobs/${id}/apply-click`, { method: "POST" });
      const link = res.application_link || job.application_link;
      if (link) window.open(link, "_blank", "noopener");
      else notify("No application link available");
    } catch {
      notify("Active membership required", "error");
    }
  };

  return (
    <Page>
      <button onClick={() => navigate(-1)} className="mb-6 text-sm font-bold text-brand hover:underline" data-testid="header-back">‹ Back</button>
      <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
        <div className="space-y-6">
          <div className="flex gap-5">
            <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-brand-soft"><Briefcase className="h-8 w-8 text-brand" /></span>
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight text-gray-900" data-testid="job-title">{job.title}</h1>
              <p className="mt-2 flex items-center gap-2 text-gray-500">
                <Building2 className="h-4 w-4" /> {job.company}
                {job.featured ? <Star className="h-4 w-4 fill-amber-500 text-amber-500" /> : null}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {[job.location, job.work_mode, job.experience_required, job.employment_type].filter(Boolean).map((c, i) => (
                  <span key={i} className="inline-flex items-center gap-1 rounded-full bg-brand-mist px-3 py-1 text-xs font-semibold text-brand-ink">
                    {i === 0 ? <MapPin className="h-3 w-3" /> : null}{c}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {job.visa_info ? (
            <Card><h3 className="font-extrabold text-gray-900">Work Authorization / Visa</h3><p className="mt-1 text-sm text-gray-600">{job.visa_info}</p></Card>
          ) : null}
          {unlocked ? <Premium job={job} /> : <Locked job={job} cta={cta} />}
        </div>
        <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
          <Card>
            {unlocked ? (
              <Button full size="lg" title="Apply Now" icon={<Send className="h-4 w-4" />} onClick={apply} data-testid="job-apply-btn" />
            ) : (
              <Button full size="lg" title={cta.short} onClick={cta.go} data-testid="job-plans-btn" />
            )}
            <div className="mt-3"><TrackButton jobId={id} /></div>
            <p className="mt-2 text-center text-[11px] text-gray-400">Tracking helps you follow up. It is not an application.</p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button variant="outline" size="sm" title={job.is_saved ? "Saved" : "Save"} onClick={toggleSave}
                icon={<Bookmark className={`h-4 w-4 ${job.is_saved ? "fill-brand" : ""}`} />} data-testid="job-save-btn" />
              <Button variant="ghost" size="sm" title="Prepare for Interview"
                onClick={() => navigate(user ? `/career/interview?jobId=${id}` : "/auth/login")} data-testid="job-prepare-interview-btn" />
            </div>
          </Card>
          <Card>
            <h3 className="mb-2 font-extrabold text-gray-900">Overview</h3>
            <KV label="Function" value={job.function} />
            <KV label="Industry" value={job.industry_category || job.function} />
            <KV label="Region" value={job.region} />
            <KV label="City" value={job.city || job.location} />
            <KV label="Country" value={job.country} />
            <KV label="Posted" value={formatDate(job.date_added)} />
            <KV label="Deadline" value={formatDate(job.application_deadline)} />
          </Card>
        </aside>
      </div>
    </Page>
  );
}
