import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Briefcase, CheckCircle2, Code2, CreditCard, Headphones, Plane, Send, Sparkles, UserPlus, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { INDUSTRIES, INDUSTRY_SHORT, money } from "@/lib/constants";
import { Button, Card } from "@/components/kit";
import { LaunchOfferCard, useLaunchOffer } from "@/components/Membership";

const HERO = "https://images.unsplash.com/photo-1768101225267-c6fc5678c113?crop=entropy&cs=srgb&fm=jpg&q=85&w=1600";
const CAT_ICON = {
  "HR & Recruitment": Users,
  "Finance & Accounting": BarChart3,
  "IT & Technology": Code2,
  "Travel & Hospitality": Plane,
  "BPO / Customer Experience": Headphones,
};
const STEPS = [
  { icon: UserPlus, title: "Register", desc: "Create your free JobRadar account in seconds." },
  { icon: CreditCard, title: "Choose a membership", desc: "Pick a plan that fits your job search." },
  { icon: Sparkles, title: "Discover curated jobs", desc: "Browse hand-picked, relevant opportunities." },
  { icon: Send, title: "Apply directly", desc: "Apply to employers using direct links." },
];
const WHY = [
  "Curated opportunities, not endless listings",
  "Saves hours of job-search time",
  "Direct application links to employers",
  "Regularly updated fresh listings",
  "Premium member-only access",
  "No false employment promises",
];

function Hero({ hidden, user }) {
  const navigate = useNavigate();
  return (
    <section className="relative overflow-hidden bg-brand-ink">
      <img src={HERO} alt="" className="absolute inset-0 h-full w-full object-cover opacity-30" />
      <div className="radar-grid absolute inset-0 bg-gradient-to-r from-brand-ink via-brand-ink/90 to-brand-ink/50" />
      <div className="container-x relative grid gap-12 py-24 lg:grid-cols-[1.3fr_1fr] lg:py-32">
        <div className="fade-up">
          <span className="inline-block rounded-full bg-white/15 px-4 py-1.5 text-xs font-bold uppercase tracking-widest text-violet-100">
            Premium Curated Job Intelligence
          </span>
          <h1 className="mt-6 text-4xl font-extrabold leading-[1.05] tracking-tight text-white sm:text-5xl lg:text-6xl">
            Stop Searching.<br />Start Discovering.
          </h1>
          <p className="mt-6 max-w-xl text-base text-violet-100 md:text-lg">
            Access carefully curated job opportunities across high-demand functions and apply directly to employers.
          </p>
          <div className="mt-10 flex flex-wrap gap-3">
            <Button size="lg" title="Explore Jobs" onClick={() => navigate("/explore")} data-testid="hero-explore-btn" />
            <Button
              size="lg"
              variant="secondary"
              title={hidden ? (user ? "My Access" : "Claim Free Access") : "View Membership Plans"}
              onClick={() => navigate(hidden ? (user ? "/membership" : "/auth/register") : "/plans")}
              data-testid="hero-plans-btn"
            />
          </div>
        </div>
      </div>
    </section>
  );
}

function Categories() {
  const navigate = useNavigate();
  const tiles = [
    ...INDUSTRIES.map((c) => ({ key: c, label: INDUSTRY_SHORT[c], Icon: CAT_ICON[c] || Briefcase, to: `/explore?industry_category=${encodeURIComponent(c)}`, id: `category-${c}` })),
    { key: "india", label: "India Jobs", Icon: Briefcase, to: "/explore?region=India", id: "region-india" },
    { key: "intl", label: "International Jobs", Icon: Plane, to: "/explore?region=International", id: "region-international" },
  ];
  return (
    <section className="container-x py-20">
      <h2 className="text-2xl font-extrabold text-gray-900">Job Categories</h2>
      <div className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-7">
        {tiles.map(({ key, label, Icon, to, id }) => (
          <button key={key} onClick={() => navigate(to)} data-testid={id}
            className="group flex flex-col items-center gap-3 rounded-2xl border border-gray-200 bg-white p-5 transition-[border-color,transform] duration-200 hover:-translate-y-1 hover:border-brand">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-soft transition-colors group-hover:bg-brand">
              <Icon className="h-6 w-6 text-brand group-hover:text-white" />
            </span>
            <span className="text-center text-sm font-bold text-gray-800">{label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

function Plans({ plans }) {
  const navigate = useNavigate();
  return (
    <section className="container-x py-12">
      <h2 className="text-2xl font-extrabold text-gray-900">Membership Plans</h2>
      <div className="mt-8 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
        {plans.map((p) => (
          <button key={p.plan_id} onClick={() => navigate("/plans")} data-testid={`home-plan-${p.plan_id}`}
            className={`rounded-2xl border p-6 text-left transition-transform hover:-translate-y-1 ${p.featured ? "border-brand bg-brand text-white" : "border-gray-200 bg-white"}`}>
            {p.featured ? <span className="rounded-full bg-white/20 px-3 py-1 text-[11px] font-bold uppercase">{p.best_value ? "Best Value" : "Recommended"}</span> : null}
            <p className="mt-3 font-bold">{p.name}</p>
            <p className="mt-2 text-3xl font-extrabold">{money(p.price, p.currency)}</p>
            <p className={`mt-1 text-sm ${p.featured ? "text-violet-100" : "text-gray-500"}`}>{p.duration_days} days access</p>
          </button>
        ))}
      </div>
      <Button className="mt-8" title="Become a Member" onClick={() => navigate("/plans")} data-testid="become-member-btn" />
    </section>
  );
}

export default function Home() {
  const { user } = useAuth();
  const { data: launch } = useLaunchOffer();
  const hidden = !!launch?.plans_hidden;
  const steps = hidden
    ? STEPS.map((s, i) => (i === 1 ? { ...s, title: "Get free access", desc: "Our first members get free full access." } : s))
    : STEPS;
  const { data: plansData } = useQuery({ queryKey: ["plans"], queryFn: () => api("/plans", { auth: false }) });
  return (
    <div data-testid="home-page">
      <Hero hidden={hidden} user={user} />
      <section className="container-x pt-20">
        <h2 className="text-2xl font-extrabold text-gray-900">How It Works</h2>
        <div className="mt-8 grid gap-5 md:grid-cols-4">
          {steps.map((s, i) => (
            <Card key={s.title} className="fade-up" style={{ animationDelay: `${i * 80}ms` }}>
              <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-soft"><s.icon className="h-5 w-5 text-brand" /></span>
              <p className="mt-4 font-extrabold text-gray-900">Step {i + 1}: {s.title}</p>
              <p className="mt-1 text-sm text-gray-500">{s.desc}</p>
            </Card>
          ))}
        </div>
      </section>
      <Categories />
      <section className="container-x">
        <h2 className="text-2xl font-extrabold text-gray-900">Why JobRadar</h2>
        <Card className="mt-8 grid gap-4 p-8 sm:grid-cols-2 lg:grid-cols-3">
          {WHY.map((w) => (
            <p key={w} className="flex items-center gap-3 font-semibold text-gray-700"><CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />{w}</p>
          ))}
        </Card>
      </section>
      {hidden ? (
        <section className="container-x py-12"><LaunchOfferCard /></section>
      ) : (
        <Plans plans={plansData?.plans || []} />
      )}
    </div>
  );
}
