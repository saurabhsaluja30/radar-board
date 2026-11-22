"""Candidate JD match check: turns a pasted job description into the job fields SmartMatch scores, so one engine
powers My Job Matches, alerts, admin search and this check. Rule-based, so it costs nothing per use and never invents
anything about the candidate: factors the JD or the profile doesn't cover are reported as not assessed."""
import re
from typing import Optional

from resume_parse import INDUSTRY_HINTS, SKILLS, _find_terms
from smartmatch import WEIGHTS, norm_skill, score_match, split_list

PREFERRED_CUE = re.compile(r"\b(?:preferred|nice to have|good to have|plus|advantage|desirable|bonus)\b", re.I)
REQUIRED_CUE = re.compile(r"\b(?:must|required|mandatory|requirements?|essential|key skills|you will need)\b", re.I)
EXP_RANGE = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:\+|-|–|to)\s*(\d{1,2}(?:\.\d)?)?\s*(?:years?|yrs?)", re.I)
EXP_MIN = re.compile(r"(?:minimum|min\.?|at least|atleast)\s*(\d{1,2})\s*(?:years?|yrs?)", re.I)
LPA_RANGE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:-|–|to)\s*(\d{1,3}(?:\.\d+)?)\s*(?:lpa|lakhs?|l\.?p\.?a)", re.I)
LABELS = (("Suitable", "Your profile meets this job's key requirements."),
          ("Partially Suitable", "You meet some key requirements; close the gaps below before applying."),
          ("Not Currently Suitable", "Important requirements are not met yet. See what to work on below."))


def _candidate_terms(c: dict) -> list:
    return [s.lower() for s in split_list(c.get("primary_skills")) + split_list(c.get("secondary_skills"))
            + split_list(c.get("tools")) + split_list(c.get("certifications")) if len(s) >= 2]


def jd_to_job(text: str, c: dict, title: Optional[str] = None) -> dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    vocab = SKILLS["technical"] + SKILLS["functional"] + SKILLS["tools"] + _candidate_terms(c)
    body = lines[1:] if title is None and len(lines) > 1 else lines  # the first line is the job title, not a skill list
    preferred_text = "\n".join(ln for ln in body if PREFERRED_CUE.search(ln))
    # When the JD marks what is required, only those lines are mandatory and other mentions count as preferred.
    # Without such markers, every skill mentioned outside "good to have" lines is treated as required.
    marked = [ln for ln in body if REQUIRED_CUE.search(ln) and not PREFERRED_CUE.search(ln)]
    rest = [ln for ln in body if not PREFERRED_CUE.search(ln) and ln not in marked]
    req = _find_terms("\n".join(marked or rest), vocab)
    pref = [s for s in _find_terms(preferred_text + ("\n" + "\n".join(rest) if marked else ""), vocab) if s not in req]
    job = {"title": (title or (lines[0] if lines else ""))[:120], "required_skills": req, "preferred_skills": pref}
    m = EXP_RANGE.search(text)
    if m:
        job["experience_min"] = float(m.group(1))
        job["experience_max"] = float(m.group(2)) if m.group(2) else None
    elif EXP_MIN.search(text):
        job["experience_min"] = float(EXP_MIN.search(text).group(1))
    low = text.lower()
    if re.search(r"\b(?:fully remote|remote)\b", low) and "not remote" not in low:
        job["work_mode"] = "Remote"
    elif "hybrid" in low:
        job["work_mode"] = "Hybrid"
    elif re.search(r"\b(?:on-?site|work from office|wfo|in-office)\b", low):
        job["work_mode"] = "On-site"
    s = LPA_RANGE.search(text)
    if s:
        job["salary_min"], job["salary_max"], job["currency"] = float(s.group(1)) * 1e5, float(s.group(2)) * 1e5, "INR"
    terms = {norm_skill(t) for t in _find_terms(text, [h for hs in INDUSTRY_HINTS.values() for h in hs])}
    hits = sorted(((len({norm_skill(h) for h in hs} & terms), ind) for ind, hs in INDUSTRY_HINTS.items()), reverse=True)
    if hits and hits[0][0] >= 2:
        job["industry_category"] = hits[0][1]
    # Location: only places the candidate cares about are looked for; anything else stays "not assessed".
    places = split_list(c.get("preferred_locations")) + split_list(c.get("preferred_location") or "") + \
        [(c.get("current_location") or "").split(",")[0]]
    found = next((p for p in places if p and re.search(rf"\b{re.escape(p.lower())}\b", low)), None)
    if found:
        job["location"] = job["city"] = found
    return job


def suitability(res: dict) -> dict:
    """Score over the factors that could be assessed, then a plain-language verdict."""
    comps = res["components"]
    assessed = {k: v for k, v in comps.items() if v["assessed"]}
    possible = sum(v["max"] for v in assessed.values())
    score = round(sum(v["score"] for v in assessed.values()) * 100 / possible) if possible else 0
    exp_gap = any(f.startswith("Below required experience") for f in res["flags"])
    if score >= 80 and not res["mandatory_gap"] and not exp_gap:
        i = 0
    elif score >= 65 or (score >= 50 and not res["mandatory_gap"]):
        i = 1
    else:
        i = 2
    if (res["mandatory_gap"] or exp_gap) and i == 0:
        i = 1
    return {"score": score, "verdict": LABELS[i][0], "summary": LABELS[i][1],
            "assessed_factors": len(assessed), "total_factors": len(comps)}


def recommendations(res: dict) -> list:
    out = []
    if res["missing_mandatory_skills"]:
        out.append("Key skills the job asks for that your profile doesn't show: "
                   + ", ".join(res["missing_mandatory_skills"][:8])
                   + ". If you have them, add them to your profile and resume; if not, these are the skills to build.")
    if res["missing_preferred_skills"]:
        out.append("Nice-to-have skills you could highlight or learn: " + ", ".join(res["missing_preferred_skills"][:8]) + ".")
    for f in res["flags"]:
        if f.startswith("Below required experience"):
            out.append(f + ". Highlight directly relevant projects, or look for roles with a lower minimum.")
        elif f.startswith("Above experience range"):
            out.append(f + ". The role may be junior for you; check the responsibilities and salary.")
    profile_gaps = [m for m in res["missing_data"] if m.startswith("Candidate")]
    if profile_gaps:
        out.append("Complete these in your profile for a fuller check: "
                   + ", ".join(m.replace("Candidate ", "") for m in profile_gaps) + ".")
    if not out:
        out.append("Your profile covers what this job asks for. Tailor your resume to the job description before applying.")
    return out


def check(text: str, c: dict, related: list, weights: Optional[dict] = None, job: Optional[dict] = None) -> dict:
    j = job or jd_to_job(text, c)
    res = score_match(c, j, related, weights or WEIGHTS)
    return {**suitability(res), "matched_skills": res["matched_skills"],
            "missing_mandatory_skills": res["missing_mandatory_skills"],
            "missing_preferred_skills": res["missing_preferred_skills"],
            "experience_gaps": [f for f in res["flags"] if "experience" in f.lower()],
            "other_checks": [f for f in res["flags"] if "experience" not in f.lower() and not f.startswith("Missing mandatory")],
            "components": res["components"], "not_assessed": res["missing_data"],
            "recommendations": recommendations(res), "job_read_as": {k: v for k, v in j.items() if k in (
                "title", "required_skills", "preferred_skills", "experience_min", "experience_max", "work_mode",
                "industry_category", "location", "salary_min", "salary_max")}}
