import React from "react";
import "@/App.css";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/context/AuthContext";
import AppShell from "@/components/Layout";
import Home from "@/pages/Home";
import Explore from "@/pages/Explore";
import JobDetail from "@/pages/JobDetail";
import Saved from "@/pages/Saved";
import Tracker from "@/pages/Tracker";
import { Forgot, Login, Register } from "@/pages/Auth";
import { Account, Dashboard, Membership, Plans, Profile } from "@/pages/Member";
import { About, Contact, FAQ, Legal } from "@/pages/Info";
import { CareerHub, ResumeBuilder } from "@/pages/career/Builder";
import ResumeEditor from "@/pages/career/ResumeEditor";
import Analyser from "@/pages/career/Analyser";
import { CareerHistory, InterviewSession, InterviewSetup } from "@/pages/career/Interview";
import { AdminDashboard, AdminShell } from "@/pages/admin/AdminShell";
import { AdminCandidates, AdminJobEdit, AdminJobs, AdminPayments, AdminSubscriptions } from "@/pages/admin/AdminManage";
import { AdminDemand, AdminRegistration, AdminSuccess } from "@/pages/admin/AdminAnalytics";
import { AdminCareer, AdminDevPanel, AdminEmails, AdminLaunch } from "@/pages/admin/AdminTools";
import { useAuth } from "@/context/AuthContext";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 15000 } } });

function RequireUser({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? children : <Navigate to="/auth/login" replace />;
}

function ScrollTop() {
  const { pathname } = useLocation();
  React.useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

const authed = (el) => <RequireUser>{el}</RequireUser>;

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <ScrollTop />
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<Home />} />
              <Route path="/explore" element={<Explore />} />
              <Route path="/job/:id" element={<JobDetail />} />
              <Route path="/saved" element={<Saved />} />
              <Route path="/tracker" element={authed(<Tracker />)} />
              <Route path="/account" element={<Account />} />
              <Route path="/auth/login" element={<Login />} />
              <Route path="/auth/register" element={<Register />} />
              <Route path="/auth/forgot" element={<Forgot />} />
              <Route path="/plans" element={<Plans />} />
              <Route path="/membership" element={<Membership />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/about" element={<About />} />
              <Route path="/faq" element={<FAQ />} />
              <Route path="/contact" element={<Contact />} />
              <Route path="/legal/:type" element={<Legal />} />
              <Route path="/career" element={<CareerHub />} />
              <Route path="/career/resume-builder" element={authed(<ResumeBuilder />)} />
              <Route path="/career/resume/:id" element={authed(<ResumeEditor />)} />
              <Route path="/career/analyser" element={authed(<Analyser />)} />
              <Route path="/career/interview" element={authed(<InterviewSetup />)} />
              <Route path="/career/interview/:id" element={authed(<InterviewSession />)} />
              <Route path="/career/history" element={authed(<CareerHistory />)} />
            </Route>
            <Route path="/admin" element={<AdminShell />}>
              <Route index element={<AdminDashboard />} />
              <Route path="jobs" element={<AdminJobs />} />
              <Route path="job-edit" element={<AdminJobEdit />} />
              <Route path="candidates" element={<AdminCandidates />} />
              <Route path="subscriptions" element={<AdminSubscriptions />} />
              <Route path="payments" element={<AdminPayments />} />
              <Route path="emails" element={<AdminEmails />} />
              <Route path="dev-panel" element={<AdminDevPanel />} />
              <Route path="launch" element={<AdminLaunch />} />
              <Route path="career" element={<AdminCareer />} />
              <Route path="registration" element={<AdminRegistration />} />
              <Route path="demand" element={<AdminDemand />} />
              <Route path="success" element={<AdminSuccess />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
        <Toaster position="top-right" richColors />
      </AuthProvider>
    </QueryClientProvider>
  );
}
