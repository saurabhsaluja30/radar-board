export const CATEGORIES = [
  "HR & Recruitment",
  "Finance & Accounting",
  "Operations & Customer Experience",
  "Travel & Hospitality",
  "Sales & Business Development",
  "IT & Technology",
  "Other Professional Roles",
];

export const INDUSTRIES = [
  "HR & Recruitment",
  "Finance & Accounting",
  "IT & Technology",
  "Travel & Hospitality",
  "BPO / Customer Experience",
];
export const INDUSTRIES_WITH_OTHER = [...INDUSTRIES, "Other"];

export const INDUSTRY_SHORT = {
  "HR & Recruitment": "HR",
  "Finance & Accounting": "Finance",
  "IT & Technology": "IT",
  "Travel & Hospitality": "Travel",
  "BPO / Customer Experience": "BPO",
  Other: "Other",
};

export const REGIONS = ["India", "International"];
export const PREF_WORK_MODES = ["Work From Office", "Hybrid", "Remote", "Any"];
export const CURRENCIES = ["INR", "USD", "GBP", "EUR", "AED", "SGD", "AUD", "CAD"];
export const WORK_MODES = ["Work From Office", "Hybrid", "Remote"];
export const EXPERIENCE_RANGES = ["0-2 years", "2-5 years", "5-8 years", "8+ years"];
export const JOB_STATUSES = ["Draft", "Published", "Unpublished", "Expired", "Closed"];
export const JOB_STATUS_LABEL = { Draft: "Draft", Published: "Open", Unpublished: "Paused", Expired: "Expired", Closed: "Closed" };
export const VERIFICATION_STATUSES = ["Pending Verification", "Verified", "Rejected"];
export const JOB_SOURCES = ["EevolveX recruitment assignment", "Direct employer submission", "Recruiter submission",
  "Approved external job feed / API", "Other authorised source"];
export const NOTICE_PERIODS = ["Immediate", "15 days", "30 days", "45 days", "60 days", "90 days", "More than 90 days"];
export const EMPLOYMENT_TYPES = ["Full-time", "Part-time", "Contract", "Internship", "Any"];
export const ALERT_FREQUENCIES = ["Instant", "Daily", "Weekly"];
export const MATCH_STATUS_LABEL = {
  suggested: "Suggested by System", pending_review: "Pending Admin Review", approved: "Approved", rejected: "Rejected",
  shared: "Shared with Candidate", interested: "Candidate Interested", not_interested: "Candidate Not Interested",
  applied: "Candidate Applied Independently", interview_reported: "Interview Reported", closed: "Closed",
};
export const scoreColor = (s) => (s >= 80 ? "success" : s >= 65 ? "warning" : "error");

export const OPPORTUNITY_NOTICE =
  "JobRadar currently provides curated job opportunities primarily across HR & Recruitment, Finance & Accounting, " +
  "IT & Technology, Travel & Hospitality, and BPO / Customer Experience. We also publish selected opportunities from " +
  "India and international markets. Please select a membership only if these job categories are relevant to your " +
  "career interests. JobRadar provides access to curated job information and application opportunities. Membership " +
  "does not guarantee a job, interview or employment.";

export const OPPORTUNITY_NOTICE_FREE =
  "JobRadar currently provides curated job opportunities primarily across HR & Recruitment, Finance & Accounting, " +
  "IT & Technology, Travel & Hospitality, and BPO / Customer Experience. We also publish selected opportunities from " +
  "India and international markets. Access is currently free for our first members. JobRadar provides access to " +
  "curated job information and application opportunities and does not guarantee a job, interview or employment.";

export const MEMBERSHIP_UI = {
  active: { label: "Active", color: "success", hint: "You have full access to all curated jobs." },
  expiring_soon: { label: "Expiring Soon", color: "warning", hint: "Renew now to keep uninterrupted access." },
  expired: { label: "Expired", color: "error", hint: "Renew to unlock premium job details again." },
  cancelled: { label: "Cancelled", color: "error", hint: "Your membership was cancelled." },
  payment_failed: { label: "Payment Failed", color: "error", hint: "Your last payment could not be completed." },
  pending: { label: "Pending Payment", color: "warning", hint: "Complete your payment to activate." },
  no_membership: { label: "No Membership", color: "info", hint: "Get access to unlock full job details." },
};

export function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export function timeAgo(iso) {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 30) return `${days}d ago`;
  return formatDate(iso);
}

export function money(amount, currency = "INR") {
  if (amount === undefined || amount === null) return "—";
  const sym = currency === "INR" ? "₹" : currency + " ";
  return `${sym}${Number(amount).toLocaleString("en-IN")}`;
}
