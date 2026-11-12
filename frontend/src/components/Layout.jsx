import React from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Radar, ShieldCheck, UserCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

export function BrandLogo({ dark }) {
  return (
    <Link to="/" className="flex items-center gap-2.5" data-testid="brand-logo">
      <span className={`flex h-10 w-10 items-center justify-center rounded-xl ${dark ? "bg-white/15" : "bg-brand-soft"}`}>
        <Radar className={`h-6 w-6 ${dark ? "text-white" : "text-brand"}`} />
      </span>
      <span className="leading-tight">
        <span className={`block text-xl font-extrabold tracking-tight ${dark ? "text-white" : "text-brand"}`}>JobRadar</span>
        <span className={`block text-[10px] font-semibold tracking-wider ${dark ? "text-violet-200" : "text-gray-500"}`}>by Evolveminds</span>
      </span>
    </Link>
  );
}

const NAV = [
  ["/", "Home"],
  ["/explore", "Explore"],
  ["/saved", "Saved"],
  ["/career", "Career Tools"],
];

function TopNav() {
  const { user } = useAuth();
  const navigate = useNavigate();
  return (
    <header className="sticky top-0 z-40 border-b border-gray-100 bg-white/85 backdrop-blur-xl">
      <div className="container-x flex h-[72px] items-center justify-between">
        <div className="flex items-center gap-10">
          <BrandLogo />
          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} data-testid={`nav-${label.toLowerCase().replace(" ", "-")}`}
                className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>
                {label}
              </NavLink>
            ))}
            {user ? (
              <NavLink to="/dashboard" data-testid="nav-dashboard" className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}>
                Dashboard
              </NavLink>
            ) : null}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          {user?.role === "admin" ? (
            <button onClick={() => navigate("/admin")} className="btn btn-sm btn-secondary" data-testid="nav-admin">
              <ShieldCheck className="h-4 w-4" /> Admin
            </button>
          ) : null}
          {user ? (
            <button onClick={() => navigate("/account")} className="btn btn-sm btn-outline" data-testid="header-account-btn">
              <UserCircle className="h-4 w-4" /> {(user.full_name || "Account").split(" ")[0]}
            </button>
          ) : (
            <>
              <button onClick={() => navigate("/auth/login")} className="btn btn-sm btn-ghost" data-testid="header-login-btn">Login</button>
              <button onClick={() => navigate("/auth/register")} className="btn btn-sm btn-primary" data-testid="header-register-btn">Create Account</button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

const FOOT = [
  ["About", "/about"], ["FAQ", "/faq"], ["Contact", "/contact"], ["Terms", "/legal/terms"],
  ["Privacy", "/legal/privacy"], ["Refund", "/legal/refund"], ["Cancellation", "/legal/cancellation"], ["Disclaimer", "/legal/disclaimer"],
];

function Footer() {
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: () => api("/config", { auth: false }) });
  return (
    <footer className="mt-24 border-t border-gray-100 bg-white">
      <div className="container-x grid gap-10 py-12 md:grid-cols-[1.2fr_1fr]">
        <div>
          <BrandLogo />
          <p className="mt-4 flex max-w-lg gap-2 text-xs leading-relaxed text-gray-500">
            <ShieldCheck className="h-4 w-4 shrink-0" /> {cfg?.disclaimer}
          </p>
        </div>
        <div className="flex flex-wrap content-start gap-x-6 gap-y-3 md:justify-end">
          {FOOT.map(([l, h]) => (
            <Link key={l} to={h} className="text-sm font-semibold text-brand hover:underline" data-testid={`footer-${l}`}>{l}</Link>
          ))}
        </div>
      </div>
      <p className="pb-8 text-center text-xs text-gray-400">JobRadar by Evolveminds · Stop Searching. Start Discovering.</p>
    </footer>
  );
}

export default function AppShell() {
  return (
    <div className="flex min-h-screen flex-col">
      <TopNav />
      <main className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}

export const Page = ({ children, narrow }) => (
  <div className={`container-x fade-up py-10 ${narrow ? "max-w-3xl" : ""}`}>{children}</div>
);
