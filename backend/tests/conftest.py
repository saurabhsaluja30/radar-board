"""Shared pytest setup.

Most API tests run against a live deployed backend (REACT_APP_BACKEND_URL) and its database. Without that variable
those modules used to crash during collection (`None.rstrip`), which aborted the whole run. They are now skipped
with a clear reason, so the unit tests (parsers, signatures, rate limiter) still run anywhere.
"""
import os
from pathlib import Path

import pytest

LIVE_MODULES = {
    "test_discovery.py", "test_email_pacing.py", "test_job_alerts.py", "test_jobradar_api.py", "test_ops.py",
    "test_resume_studio.py", "test_resumes.py", "test_smartmatch.py", "test_smartmatch_auto.py",
    "test_smartmatch_expiry.py", "test_tracker_demand.py", "test_tracker_interview.py",
}

collect_ignore = ["ui_setup_alerts.py"]  # a manual setup script, not a test module


def pytest_ignore_collect(collection_path: Path, config):
    if collection_path.name in LIVE_MODULES and not os.environ.get("REACT_APP_BACKEND_URL"):
        return True
    return None


def pytest_report_header(config):
    if not os.environ.get("REACT_APP_BACKEND_URL"):
        return "REACT_APP_BACKEND_URL is not set: live API test modules are skipped"
    return None
