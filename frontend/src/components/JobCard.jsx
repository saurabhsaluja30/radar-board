import React from "react";
import { useNavigate } from "react-router-dom";
import { Briefcase, Building2, Lock, MapPin, Star } from "lucide-react";
import { timeAgo } from "@/lib/constants";

const Tag = ({ children }) => (
  <span className="inline-flex items-center gap-1 rounded-full bg-brand-mist px-2.5 py-1 text-xs font-semibold text-brand-ink">{children}</span>
);

export function JobCard({ job }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(`/job/${job.job_id}`)}
      data-testid={`job-card-${job.job_id}`}
      className="group flex h-full w-full flex-col rounded-2xl border border-gray-200 bg-white p-5 text-left transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-brand/50 hover:shadow-[0_12px_30px_-14px_rgba(124,58,237,0.35)]"
    >
      <div className="flex gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-soft">
          <Briefcase className="h-5 w-5 text-brand" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <h3 className="line-clamp-2 flex-1 text-[15px] font-bold text-gray-900 group-hover:text-brand">{job.title}</h3>
            {job.featured ? <Star className="h-4 w-4 shrink-0 fill-amber-500 text-amber-500" /> : null}
          </div>
          <p className="mt-1 flex items-center gap-1 truncate text-sm text-gray-500">
            <Building2 className="h-3.5 w-3.5" /> {job.company}
          </p>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-1.5">
        {job.region === "International" && job.country ? <Tag>Intl · {job.country}</Tag> : null}
        {job.location ? <Tag><MapPin className="h-3 w-3" />{job.location}</Tag> : null}
        {job.work_mode ? <Tag>{job.work_mode}</Tag> : null}
        {job.experience_required ? <Tag>{job.experience_required}</Tag> : null}
      </div>
      <div className="mt-auto flex items-center justify-between pt-4 text-xs">
        <span className="text-gray-400">{timeAgo(job.date_added)}</span>
        {job.locked ? (
          <span className="flex items-center gap-1 font-bold text-brand"><Lock className="h-3 w-3" /> Members only</span>
        ) : (
          <span className="font-bold text-emerald-600">Full access</span>
        )}
      </div>
    </button>
  );
}
