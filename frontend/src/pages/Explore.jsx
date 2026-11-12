import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Search, SlidersHorizontal, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { INDUSTRIES, INDUSTRY_SHORT, REGIONS, WORK_MODES } from "@/lib/constants";
import { Chip, EmptyState, notify, Spinner } from "@/components/kit";
import { JobCard } from "@/components/JobCard";
import { Page } from "@/components/Layout";

function FilterGroup({ title, children }) {
  return (
    <div>
      <p className="mb-2.5 text-xs font-bold uppercase tracking-wider text-gray-400">{title}</p>
      <div className="flex flex-wrap gap-2">{children}</div>
    </div>
  );
}

export default function Explore() {
  const [params] = useSearchParams();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(params.get("industry_category") || params.get("function") || "All");
  const [region, setRegion] = useState(params.get("region") || "All");
  const [mode, setMode] = useState("All");
  const [sort, setSort] = useState("newest");

  const { data, isLoading } = useQuery({
    queryKey: ["jobs", q, cat, region, mode, sort, user?.user_id],
    queryFn: () => api("/jobs", { query: { q, industry_category: cat, region, work_mode: mode, sort, limit: 60 }, auth: !!user }),
  });
  const jobs = data?.jobs || [];
  const savedQ = useQuery({ queryKey: ["saved-searches", user?.user_id], queryFn: () => api("/saved-searches"), enabled: !!user });
  const savedSearches = savedQ.data?.searches || [];
  const hasFilters = !!q.trim() || cat !== "All" || region !== "All" || mode !== "All";

  const saveSearch = async () => {
    const name = [q.trim() && `“${q.trim()}”`, cat !== "All" && (INDUSTRY_SHORT[cat] || cat), region !== "All" && region, mode !== "All" && mode]
      .filter(Boolean).join(" · ") || "My search";
    try {
      await api("/saved-searches", { method: "POST", body: { name, filters: { q: q.trim(), industry_category: cat, region, work_mode: mode, sort } } });
      qc.invalidateQueries({ queryKey: ["saved-searches"] });
      notify("Search saved", "success");
    } catch (e) {
      notify(e.message || "Could not save search", "error");
    }
  };
  const applySearch = (f) => {
    setQ(f.q || "");
    setCat(f.industry_category || "All");
    setRegion(f.region || "All");
    setMode(f.work_mode || "All");
    setSort(f.sort || "newest");
  };
  const removeSearch = async (id) => {
    await api(`/saved-searches/${id}`, { method: "DELETE" }).catch(() => {});
    qc.invalidateQueries({ queryKey: ["saved-searches"] });
  };

  return (
    <Page>
      <h1 className="h-page">Explore Jobs</h1>
      <div className="mt-8 grid gap-8 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-6 lg:sticky lg:top-24 lg:self-start" data-testid="explore-filters">
          <FilterGroup title="Region">
            <Chip label="All regions" selected={region === "All"} onClick={() => setRegion("All")} data-testid="chip-region-all" />
            {REGIONS.map((r) => (
              <Chip key={r} label={r === "India" ? "India Jobs" : "International"} selected={region === r}
                onClick={() => setRegion(region === r ? "All" : r)} data-testid={`chip-region-${r}`} />
            ))}
          </FilterGroup>
          <FilterGroup title="Industry">
            <Chip label="All" selected={cat === "All"} onClick={() => setCat("All")} data-testid="chip-ind-all" />
            {INDUSTRIES.map((c) => (
              <Chip key={c} label={INDUSTRY_SHORT[c] || c} selected={cat === c} onClick={() => setCat(cat === c ? "All" : c)} data-testid={`chip-ind-${c}`} />
            ))}
          </FilterGroup>
          <FilterGroup title="Work mode">
            <Chip label="Any mode" selected={mode === "All"} onClick={() => setMode("All")} data-testid="chip-mode-all" />
            {WORK_MODES.map((m) => (
              <Chip key={m} label={m} selected={mode === m} onClick={() => setMode(mode === m ? "All" : m)} data-testid={`chip-mode-${m}`} />
            ))}
          </FilterGroup>
          {user && (savedSearches.length > 0 || hasFilters) ? (
            <FilterGroup title="Saved searches">
              <div className="flex flex-wrap gap-2" data-testid="saved-searches-row">
                {hasFilters ? (
                  <button onClick={saveSearch} className="chip border-dashed border-brand text-brand hover:bg-brand-mist" data-testid="save-search-btn">
                    <Bookmark className="mr-1 h-3.5 w-3.5" /> Save search
                  </button>
                ) : null}
                {savedSearches.map((s) => (
                  <span key={s.search_id} className="chip chip-off gap-1.5">
                    <button onClick={() => applySearch(s.filters)} data-testid={`saved-search-${s.search_id}`}>{s.name}</button>
                    <button onClick={() => removeSearch(s.search_id)} data-testid={`saved-search-del-${s.search_id}`}><X className="h-3 w-3" /></button>
                  </span>
                ))}
              </div>
            </FilterGroup>
          ) : null}
        </aside>
        <div>
          <div className="flex gap-3">
            <div className="flex flex-1 items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 focus-within:border-brand">
              <Search className="h-4 w-4 text-gray-400" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, company, skill..."
                className="h-12 flex-1 bg-transparent text-[15px] outline-none" data-testid="job-search-input" />
            </div>
            <button onClick={() => setSort(sort === "newest" ? "relevance" : "newest")} className="btn btn-md btn-outline" data-testid="sort-toggle">
              <SlidersHorizontal className="h-4 w-4" /> {sort === "newest" ? "Newest" : "Relevance"}
            </button>
          </div>
          <p className="muted mt-4" data-testid="jobs-count">{isLoading ? "" : `${jobs.length} curated job${jobs.length === 1 ? "" : "s"}`}</p>
          {isLoading ? <Spinner /> : jobs.length === 0 ? (
            <EmptyState title="No matching jobs found" subtitle="Try adjusting your search or filters." data-testid="jobs-empty" />
          ) : (
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" data-testid="jobs-grid">
              {jobs.map((j) => <JobCard key={j.job_id} job={j} />)}
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
