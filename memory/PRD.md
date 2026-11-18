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

## Backlog
- P1: Real payment gateway (checkout is DEMO).
- P1: WhatsApp alerts (needs approved WhatsApp Business provider).
- P2: Batch membership computation for analytics at large scale; shadcn date pickers.

## Credentials
See /app/memory/test_credentials.md
