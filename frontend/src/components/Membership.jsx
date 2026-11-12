import React from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Gift, Hourglass, Info } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { MEMBERSHIP_UI, OPPORTUNITY_NOTICE, OPPORTUNITY_NOTICE_FREE, formatDate } from "@/lib/constants";
import { Button, Card } from "@/components/kit";

const PLACEHOLDER = { enabled: true, plans_hidden: true, free_days: 90, spots_total: 100, spots_left: -1 };

export function useLaunchOffer() {
  const q = useQuery({ queryKey: ["launch-offer"], queryFn: () => api("/launch-offer", { auth: false }) });
  return { ...q, data: q.data ?? PLACEHOLDER, isPlaceholderData: !q.data };
}

const STATUS_BG = { success: "bg-emerald-600", warning: "bg-amber-600", error: "bg-red-600", info: "bg-brand-ink" };

export function MembershipCard({ membership, onRenew, hidePlanName }) {
  const ui = MEMBERSHIP_UI[membership?.status] || MEMBERSHIP_UI.no_membership;
  const showRenew = ["expiring_soon", "expired", "no_membership", "cancelled", "payment_failed"].includes(membership?.status);
  return (
    <div className={`relative overflow-hidden rounded-2xl p-6 text-white ${STATUS_BG[ui.color]}`} data-testid="membership-status-card">
      <div className="radar-grid absolute inset-0 opacity-60" />
      <div className="relative">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-white/20 px-3 py-1 text-xs font-bold uppercase tracking-wide" data-testid="membership-status-label">{ui.label}</span>
          {membership?.is_demo && !hidePlanName ? <span className="rounded-full bg-amber-400 px-2 py-0.5 text-[10px] font-extrabold text-amber-950">DEMO</span> : null}
        </div>
        {membership?.is_active ? (
          <>
            <p className="mt-4 text-2xl font-extrabold">{hidePlanName ? "Full Access" : membership.plan_name}</p>
            <p className="mt-1 text-white/80" data-testid="membership-days-remaining">
              {membership.days_remaining} day{membership.days_remaining === 1 ? "" : "s"} remaining
            </p>
            <div className="mt-5 flex gap-10 text-sm">
              <div><p className="text-white/70">Started</p><p className="font-bold">{formatDate(membership.start_date)}</p></div>
              <div><p className="text-white/70">Expires</p><p className="font-bold">{formatDate(membership.expiry_date)}</p></div>
            </div>
          </>
        ) : (
          <p className="mt-4 text-white/90">{ui.hint}</p>
        )}
        {showRenew && onRenew ? (
          <Button
            className="mt-5"
            variant="secondary"
            onClick={onRenew}
            title={membership?.status === "no_membership" ? "Become a Member" : "Renew Membership"}
            data-testid="membership-renew-btn"
          />
        ) : null}
      </div>
    </div>
  );
}

export function OpportunityNotice() {
  const { data } = useLaunchOffer();
  return (
    <div className="rounded-2xl border border-brand/20 bg-brand-mist p-5" data-testid="opportunity-notice">
      <p className="flex items-center gap-2 text-sm font-extrabold text-brand-ink">
        <Info className="h-4 w-4 text-brand" /> What opportunities will you get?
      </p>
      <p className="mt-2 text-sm leading-relaxed text-gray-600">{data?.plans_hidden ? OPPORTUNITY_NOTICE_FREE : OPPORTUNITY_NOTICE}</p>
    </div>
  );
}

export function LaunchOfferCard() {
  const navigate = useNavigate();
  const { user, membership } = useAuth();
  const { data, isPlaceholderData } = useLaunchOffer();
  if (!data || isPlaceholderData) return null;
  const status = user?.launch_offer;
  let title = `Free for our first ${data.spots_total} members`;
  let body = `Register now and get free full access for ${data.free_days} days — curated jobs, direct apply links and Career Tools. ${data.spots_left} of ${data.spots_total} free spots left.`;
  let cta = { label: "Claim Free Access", to: "/auth/register" };
  let Icon = Gift;
  if (user && membership?.is_active) {
    title = "You have free full access";
    body = `Enjoy every premium job and Career Tool until ${formatDate(membership.expiry_date)}.`;
    cta = { label: "Explore Jobs", to: "/explore" };
  } else if (user && status === "waitlisted") {
    title = "You're on the waitlist";
    body = "All free launch spots are taken. We'll email you as soon as your access is approved — no payment needed.";
    cta = null;
    Icon = Hourglass;
  } else if (user) {
    title = "Access not active yet";
    body = "Your free access is not active right now. Please contact support and we will help you.";
    cta = null;
    Icon = Hourglass;
  } else if (!data.enabled) {
    title = "Membership opening soon";
    body = "Membership plans are not open yet. Create a free account to browse job previews and we'll notify you when plans are available.";
    cta = { label: "Create Free Account", to: "/auth/register" };
    Icon = Hourglass;
  } else if (data.spots_left <= 0) {
    title = "Free spots are full — join the waitlist";
    body = "All free launch spots have been claimed. Register to join the waitlist and we'll email you when your access is approved.";
    cta = { label: "Join the Waitlist", to: "/auth/register" };
    Icon = Hourglass;
  }
  return (
    <Card className="flex flex-col gap-4 md:flex-row md:items-center" data-testid="launch-offer-card">
      <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-brand-soft"><Icon className="h-7 w-7 text-brand" /></span>
      <div className="flex-1">
        <p className="text-lg font-extrabold text-gray-900">{title}</p>
        <p className="mt-1 text-sm leading-relaxed text-gray-600">{body}</p>
      </div>
      {cta ? <Button title={cta.label} onClick={() => navigate(cta.to)} data-testid="launch-offer-cta" /> : null}
    </Card>
  );
}
