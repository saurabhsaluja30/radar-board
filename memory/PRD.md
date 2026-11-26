# JobRadar Web (RADAR) — PRD

## Original problem statement
Web version of the user's RADAR mobile app (github.com/saurabhsaluja30/radar-preview): bring over existing data & logic, same features and flow adapted to desktop, no new features. Later: three admin enhancements — Candidate Demand Analytics, Registration Counter Visibility (admin-only), JobRadar Success Tracker (candidate tracker + admin success analytics with verification).

## Architecture
- Backend: FastAPI (server.py + career.py copied from mobile repo; new tracker.py, demand.py), MongoDB.
- Frontend: React (CRA) desktop web, react-router, react-query, Tailwind; brand purple / Plus Jakarta Sans as in mobile app.
- Integrations: Emergent LLM key (Career Tools AI), Emergent managed email (Resend), Emergent Object Storage (evidence files), platform cron (.emergent/crons.yml, daily 9:30 IST tracker reminders).

## Implemented
- 2026-06: Full web port — home, explore, job detail, saved, auth (email + Google), plans (DEMO checkout), membership, dashboard, profile, info/legal, Career Tools (resume builder/editor, analyser, interview coach, history), full admin portal.
- 2026-06: Admin enhancements
  - Candidate Demand Analytics (/admin/demand): current vs preferred industry, filters, distributions, recommendations, candidate list + CSV export.
  - Registration stats admin-only (dashboard + /admin/registration); public /api/launch-offer no longer exposes counts.
  - Success Tracker: /tracker for candidates (10 statuses w/ timestamps, interview/hire forms, reminders, optional redacted evidence); /admin/success analytics with conversions, reported vs verified, verify action, evidence viewer, CSV export.

- 2026-06: JobRadar SmartMatch
  - Extended candidate profile (experience, skills, preferred titles/locations, CTC, notice, alerts consent) + completion %.
  - Jobs: verification status, source tracking, exp/salary ranges, expiry auto-sweep, duplicate detection; Published shown as Open, Unpublished as Paused, Closed added.
  - Rule-based engine (smartmatch.py), Control Room, Find Matching Candidates/Jobs, Match Review with audit trail, alerts (in-app + email) with dedupe/consent/frequency, candidate My Job Matches (/matches), SmartMatch analytics.

- 2026-06: Default job alerts: tri-state consent (on / not selected = in-app only / opted out), Job Alert Manager (/admin/alert-manager), dashboard job notifications, alert-preference analytics. Email: paced sender, background welcome email, 15-min retry cron (.emergent/crons.yml email-retry).

- 2026-11: Platform upgrade (resume upload + parsing with candidate confirmation, consented talent database, Apify job imports from Greenhouse/Lever/Ashby, event-driven SmartMatch + automatic in-app alerts, platform analytics/system health, bulk membership computation).
- 2026-11: Razorpay memberships (one-time Standard Checkout, signed webhooks, receipts, reconcile; 4 tiers ₹599/₹1,499/₹1,999/₹2,499), Resume Studio (approve-only tailoring, .doc support, 2 templates), profile-matched feed + free JD fit check, tracker and interview-coach upgrades.
- 2026-11: Consolidation into main + hardening:
  - Auth: per-IP/per-email rate limits (RATE_LIMITS=off for test servers only), 8-char letters+digits passwords, hashed 8-char reset codes with 5-attempt lockout, sessions revoked on reset; Google sign-in can't enter admin or suspended accounts.
  - CORS restricted via CORS_ORIGINS (no credentialed wildcard). First admin from ADMIN_EMAIL/ADMIN_PASSWORD; the legacy default password is rotated at startup when ADMIN_PASSWORD is set. Demo jobs/candidate only with SEED_DEMO_DATA. Developer panel only with ENABLE_DEV_TOOLS.
  - Candidate data deny-by-default: only the owner admin (`is_owner`) or admins with `permissions` [view_resumes, export_candidates].
  - Resume file keys wrapped with RESUME_KEK (legacy keys wrapped at startup); uploads refuse to run without it.
  - Index creation is per index (one failure no longer skips the rest).
  - Payments: payment marked successful only after activation; stale "running" activations are taken over; activation idempotent per payment; failed webhooks are reprocessed on Razorpay retry; full refunds revoke access (refunded renewals give back only their days); RAZORPAY_API_BASE only honoured for test keys on localhost; order creation rate-limited.
- 2026-11: Apify: ISO country codes (IN) count as India; daily/poll/SmartMatch/resume-retry crons registered; 15-min poll imports finished runs without the webhook. LinkedIn sources via bebity/linkedin-jobs-scraper (~$0.0015/job): linkedin.com URLs are routed to it automatically (company page → that company's jobs; job-search URL → scraped as-is; linkedin.com/jobs → keyword × location search); job URLs canonicalised to www.linkedin.com/jobs/view/<id>; paid enrichment off.
- 2026-11: Search-based collection (no URL needed): "Job search (LinkedIn)" sources take only job titles, locations and optional filters (experience, work mode, employment type). Candidate demand search (off by default): a system-managed source rebuilt daily from the most-wanted title × city pairs in candidate preferences (settings: max searches, min candidates per search, jobs per search; preview with cost estimate). Only titles and cities are sent to Apify. All results still go to the import review queue.
- 2026-11: Candidate "Find jobs for me" (personal_search.py, off by default): one live LinkedIn search per candidate per IST day for one preferred title × city at their seniority (rotating daily), only when they have fewer good database matches than a threshold (default 10). Free 5 / members 10 new jobs a day; failed or empty searches don't use the day; one search in flight per candidate (atomic claim, released after 10 min). Same title/city/seniority on the same day shares one Apify run. Admin daily cap (default $2) pauses searches. Found jobs go to the review queue and are shown to that candidate (personal_results) before publishing. Collections: personal_quota, personal_searches, personal_results.
- 2026-11: CV paste: candidates can paste CV text (POST /resume/paste, 200–50,000 chars) as well as upload; the rule-based parser also extracts preferred titles, preferred locations, languages, links and education, confirmed on the same screen. By product decision the CV text (pasted, or read from uploaded files) is stored unencrypted in candidate_resumes.raw_text; admins with view_resumes see it, and the export_candidates CSV includes it (cells capped at 32,000 chars, formula-injection safe).

## Environment
| Variable | Required | Purpose |
|---|---|---|
| MONGO_URL, DB_NAME | yes | Database |
| ADMIN_EMAIL, ADMIN_PASSWORD | yes (first boot) | Creates the owner admin; rotates the old default password |
| RESUME_KEK | for resume uploads | 32 random bytes, base64. Wraps resume file keys. Losing it makes stored resumes unreadable |
| CORS_ORIGINS | recommended | Comma-separated allowed browser origins |
| RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET | for real payments | Razorpay; demo checkout is off once set |
| WEBHOOK_CRON_SECRET | yes | Bearer secret for /api/cron/* |
| EMERGENT_LLM_KEY | for AI tools / storage | LLM + object storage |
| APIFY_TOKEN, APIFY_WEBHOOK_SECRET, PUBLIC_BACKEND_URL | for job imports | Apify |
| SEED_DEMO_DATA, ENABLE_DEV_TOOLS, RATE_LIMITS=off | test servers only | Demo data, developer panel, no rate limits |

## Backlog
- P0 before taking real money: GST tax invoice (GSTIN, SAC, tax breakup); Razorpay live-mode activation.
- P1: Proration on upgrade (remaining days are currently lost); admin-initiated refunds; Razorpay Subscriptions / UPI AutoPay.
- P1: WhatsApp alerts (needs approved WhatsApp Business provider); email channel for automatic match alerts.
- P1: Feed the AI CV extraction into the resume confirm flow; create a tracker entry on apply-click.
- P2: Shared rate-limit store (Redis/Mongo) if running many replicas; job queue for background email; shadcn date pickers.

## Credentials
See /app/memory/test_credentials.md
