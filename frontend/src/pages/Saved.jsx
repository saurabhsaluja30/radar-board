import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Button, EmptyState, PageHeader } from "@/components/kit";
import { JobCard } from "@/components/JobCard";
import { Page } from "@/components/Layout";

export default function Saved() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data } = useQuery({ queryKey: ["saved-jobs", user?.user_id], queryFn: () => api("/saved-jobs"), enabled: !!user });
  const jobs = data?.jobs || [];
  if (!user) {
    return (
      <Page narrow>
        <h1 className="h-page">Saved Jobs</h1>
        <EmptyState title="Sign in to save jobs" subtitle="Keep track of opportunities you love." />
        <div className="flex justify-center"><Button title="Login / Register" onClick={() => navigate("/auth/login")} data-testid="saved-login-btn" /></div>
      </Page>
    );
  }
  return (
    <Page>
      <PageHeader title="Saved Jobs" subtitle={`${jobs.length} saved opportunit${jobs.length === 1 ? "y" : "ies"}`} />
      {jobs.length === 0 ? (
        <EmptyState title="No saved jobs yet" subtitle="Use the bookmark on any job to save it here." data-testid="saved-empty" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3" data-testid="saved-grid">
          {jobs.map((j) => <JobCard key={j.job_id} job={j} />)}
        </div>
      )}
    </Page>
  );
}
