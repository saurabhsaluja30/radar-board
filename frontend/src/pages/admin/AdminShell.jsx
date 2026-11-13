import React, { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Briefcase, CreditCard, FlaskConical, Gift, LayoutDashboard, LogOut, Mail, PieChart, Receipt, ShieldCheck, Sparkles, Trophy, UserPlus, Users } from "lucide-react";
import { RegistrationStats } from "@/pages/admin/AdminAnalytics";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { money } from "@/lib/constants";
import { Button, Card, Input, notify, PageHeader } from "@/components/kit";
import { BrandLogo } from "@/components/Layout";

const GROUPS = [
  ["Dashboard Overview", [{ icon: LayoutDashboard, label: "Dashboard", to: "/admin", end: true }]],
  ["Candidate Management", [{ icon: Users, label: "Candidates", to: "/admin/candidates" }, { icon: Gift, label: "Launch Offer & Waitlist", to: "/admin/launch" }]],
  ["Job Management", [{ icon: Briefcase, label: "Job Management", to: "/admin/jobs" }]],
  ["Subscription and Payment Management", [{ icon: CreditCard, label: "Subscriptions", to: "/admin/subscriptions" }, { icon: Receipt, label: "Payments", to: "/admin/payments" }]],
  ["Analytics", [
    { icon: UserPlus, label: "Candidate Registration Analytics", to: "/admin/registration" },
    { icon: PieChart, label: "Candidate Demand Analytics", to: "/admin/demand" },
    { icon: Trophy, label: "JobRadar Success Analytics", to: "/admin/success" },
  ]],
  ["Tools", [
    { icon: Mail, label: "Email Logs", to: "/admin/emails" }, { icon: Sparkles, label: "Career Tools", to: "/admin/career" },
    { icon: FlaskConical, label: "Developer Test Panel", to: "/admin/dev-panel" },
  ]],
];
const NAV = GROUPS.flatMap(([, items]) => items);

function AdminLogin() {
  const navigate = useNavigate();
  const { adminLogin } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await adminLogin(email.trim(), password);
      notify("Admin logged in", "success");
    } catch (e) {
      notify(e.message || "Login failed", "error");
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="radar-grid flex min-h-screen items-center justify-center bg-brand-ink p-6">
      <Card className="fade-up w-full max-w-md p-8">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand"><ShieldCheck className="h-7 w-7 text-white" /></span>
        <h1 className="mt-5 text-2xl font-extrabold">Admin Portal</h1>
        <p className="muted">JobRadar by Evolveminds</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <Input label="Admin Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="admin-email" />
          <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="admin-password" />
          <Button full type="submit" title="Login as Admin" loading={loading} data-testid="admin-login-submit" />
        </form>
        <button onClick={() => navigate("/")} className="mt-5 text-sm font-semibold text-brand hover:underline" data-testid="admin-back-home">← Back to app</button>
      </Card>
    </div>
  );
}

export function AdminShell() {
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();
  if (loading) return null;
  if (!user || user.role !== "admin") return <AdminLogin />;
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-72 shrink-0 flex-col bg-brand-ink p-5">
        <BrandLogo dark />
        <nav className="mt-8 min-h-0 flex-1 space-y-4 overflow-y-auto pb-4">
          {GROUPS.map(([group, items]) => (
            <div key={group} className="space-y-1">
              <p className="px-3.5 text-[10px] font-bold uppercase tracking-widest text-violet-300">{group}</p>
              {items.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end} data-testid={`admin-nav-${n.label}`}
              className={({ isActive }) => `flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-semibold transition-colors ${isActive ? "bg-white text-brand-ink" : "text-violet-100 hover:bg-white/10"}`}>
              <n.icon className="h-4 w-4 shrink-0" /> {n.label}
            </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <button onClick={() => navigate("/")} className="mb-2 text-left text-sm font-semibold text-violet-200 hover:text-white" data-testid="admin-view-site">← View site</button>
        <button onClick={async () => { await logout(); navigate("/"); }} data-testid="admin-logout"
          className="flex items-center gap-2 rounded-xl bg-white/10 px-3.5 py-2.5 text-sm font-bold text-white hover:bg-white/20">
          <LogOut className="h-4 w-4" /> Logout
        </button>
      </aside>
      <main className="min-w-0 flex-1 bg-[#faf9ff]">
        <div className="fade-up mx-auto max-w-6xl px-10 py-10"><Outlet /></div>
      </main>
    </div>
  );
}

export function AdminDashboard() {
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ["admin-dashboard"], queryFn: () => api("/admin/dashboard") });
  const metrics = [
    { label: "Real Revenue", value: money(data?.real_revenue) },
    { label: "Demo Revenue", value: money(data?.demo_revenue) },
    { label: "Jobs Published", value: data?.jobs_published ?? "—" },
    { label: "Job Views", value: data?.total_job_views ?? "—" },
  ];
  return (
    <>
      <PageHeader title="Dashboard Overview" />
      <h2 className="h-sec mb-4">Candidate Registrations</h2>
      <RegistrationStats />
      <h2 className="h-sec mb-4 mt-10">Business</h2>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {metrics.map((m) => (
          <Card key={m.label} data-testid={`metric-${m.label}`}>
            <p className="text-3xl font-extrabold text-brand">{m.value}</p>
            <p className="mt-1 text-sm font-semibold text-gray-500">{m.label}</p>
          </Card>
        ))}
      </div>
      {data?.popular_plan ? <Card className="mt-5"><p>Most popular plan: <b className="text-brand">{data.popular_plan}</b></p></Card> : null}
      <h2 className="h-sec mb-4 mt-10">Manage</h2>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        {NAV.slice(1).map((n, i) => (
          <button key={n.to} onClick={() => navigate(n.to)} data-testid={`admin-tile-${n.label}`}
            className={`flex items-center gap-3 rounded-2xl border p-5 text-left font-bold transition-transform hover:-translate-y-0.5 ${i === 0 ? "border-brand bg-brand text-white" : "border-gray-200 bg-white text-gray-800"}`}>
            <n.icon className={`h-5 w-5 ${i === 0 ? "text-white" : "text-brand"}`} /> {n.label}
          </button>
        ))}
      </div>
    </>
  );
}
