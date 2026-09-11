"""
Geothermal / Academic Job Search Agent (free version)
-------------------------------------------------------
Fetches career pages and academic job boards, does simple keyword matching
(no paid API calls), filters out postings you've already seen, and emails
you a digest of anything new.

Run manually with:  python job_agent.py
Runs automatically via the GitHub Actions workflow in .github/workflows/.
"""

import os
import json
import re
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# CONFIG - edit this section to change what the agent searches for
# ---------------------------------------------------------------------------

# Companies to check for corporate openings. Add/remove freely.
# "url" should point to the page listing their open roles.
# NOTE: Many large-company career sites block simple scripts like this one
# (403 errors) or only render listings via JavaScript (so a plain fetch sees
# an empty page). Ormat's job search page below was verified to work with a
# plain fetch. The others are commented out because they didn't work when
# tested -- if you find a working URL for one (open it in an incognito
# browser tab and copy the URL of the actual listing page, not the homepage),
# uncomment and fix the line.
COMPANIES = [
    {"name": "Ormat Technologies", "url": "https://careers.ormat.com/search/"},
    # {"name": "Fervo Energy", "url": "BLOCKED_403_NEEDS_REAL_URL"},
    # {"name": "Jacobs", "url": "JS_ONLY_NEEDS_REAL_URL"},
    # {"name": "Baker Hughes", "url": "JS_ONLY_NEEDS_REAL_URL"},
    # {"name": "SLB", "url": "BROKEN_URL_NEEDS_FIXING"},
    # {"name": "Chevron New Energies", "url": "BLOCKED_403_NEEDS_REAL_URL"},
    # {"name": "Sage Geosystems", "url": "NEEDS_REAL_ATS_URL"},
    # {"name": "Constellation Energy", "url": "BROKEN_URL_NEEDS_FIXING"},
]

# Academic job boards to check for faculty positions.
# HigherEdJobs runs bot-protection (Incapsula) that blocks plain scripts, so
# it's commented out here -- use their free "Job Alert" (saved search, emailed
# to you directly by HigherEdJobs) instead, since that request comes from
# their own system rather than an outside script and won't be blocked.
ACADEMIC_SOURCES = [
    # {"name": "HigherEdJobs", "url": "BLOCKED_BY_BOT_PROTECTION"},
    # AcademicJobsOnline removed: its /ajo/jobs page is a filter UI (categories),
    # not a list of postings, so it only produced noise. If you find a specific
    # department's AJO page (e.g. academicjobsonline.org/ajo/YourUni/YourDept),
    # add it here instead -- those pages DO list real postings.
]

# Keywords that define a match (case-insensitive). Multi-word phrases match
# as substrings; single words match whole-word only (see extract_matches).
JOB_KEYWORDS = [
    # Core
    "geothermal", "reservoir engineer", "reservoir engineering",
    "power plant design", "power plant optimization", "integrated geothermal",
    "associate professor", "professor", "assistant professor",
    "senior scientist",
    # Reservoir simulation / modeling / forecasting
    "reservoir simulation", "reservoir modeling", "reservoir modelling",
    "production forecasting", "production prediction", "history matching",
    "wellbore analysis", "well testing",
    # Thermodynamics / exergy
    "exergy analysis", "exergy", "thermodynamic analysis", "thermo-economic",
    # Advanced / next-gen geothermal
    "superhot geothermal", "supercritical geothermal",
    "enhanced geothermal systems", "EGS",
    # Energy storage / adjacent subsurface energy
    "geological energy storage", "compressed air energy storage", "CAES",
    "subsurface energy",
    # Power cycle optimization
    "flash cycle", "binary geothermal", "organic rankine cycle", "ORC",
    "ground source heat pump", "ground-source heat pump",
    "combined-cycle", "combined cycle", "district heating",
    "cascade utilization",
    # Economic / lifecycle analysis
    "techno-economic", "life cycle assessment", "LCOE", "LCA",
    # Well/field development planning
    "make-up well", "well placement",
    # Resource assessment / exploration / field implementation
    "resource assessment", "geothermal exploration", "feasibility studies",
    "reservoir characterization", "environmental impact assessment", "EIA",
    "drilling operations", "field implementation",
    # From all industry CV variants (Hexagon, XGS, Jacobs, Ormat, Zanskar) --
    # every distinct skill-list phrase across all versions, not just the
    # ones that seemed novel.
    "geothermal project development", "geothermal power systems",
    "production optimization", "injection optimization",
    "numerical modeling", "numerical modelling",
    "contractor management", "consultant management",
    "stakeholder engagement", "strategic partnerships",
    "cross-functional leadership", "international collaboration",
    "technology deployment", "energy transition", "program leadership",
    "government-industry engagement", "data-driven geothermal workflows",
    "multi-well planning", "field optimization", "heat extraction",
    "conceptual modeling", "conceptual modelling",
    "integrated energy systems", "machine learning",
    "reservoir forecasting", "advanced geothermal systems",
    "subsurface energy leader", "geothermal systems",
    # From academic CVs, cover letters, and research statements (Penn State,
    # Nevada/GBCGE, Texas STARR applications) -- every distinct
    # skill/expertise phrase found, not just ones judged novel.
    "subsurface energy storage", "underground energy storage",
    "geological thermal energy storage", "GTES",
    "carbon capture and storage", "CCS",
    "carbon capture, utilization, and storage", "CCUS",
    "CO2 storage", "carbon dioxide storage",
    "caprock integrity", "geomechanics", "geomechanical",
    "THMC coupling", "fracture permeability", "fracture mechanics",
    "heat flow modeling", "heat-flow modelling", "high-enthalpy",
    "wellbore stability", "wellbore design", "reactive flow modeling",
    "stimulation", "permeability modeling", "permeability evolution",
    "digital twin", "digital twins",
    "repurposing oil and gas wells", "abandoned oil and gas wells",
    "hydrogen storage", "subsurface hydrogen",
    "geohazards", "induced seismicity", "land subsidence",
    "remote sensing", "geospatial modeling",
    "aquifer", "groundwater",
    "critical minerals", "geothermal brines", "produced waters",
    "AI-driven", "AI-enabled", "multiphase flow",
    "geothermal reservoir modeling and management",
]

# Keywords under this length are treated as whole-word-only matches (to avoid
# short acronyms like "EGS" or "ORC" matching inside unrelated words).
SHORT_KEYWORD_MAX_LEN = 5

SEEN_FILE = "seen_jobs.json"
MAX_PAGE_CHARS = 20000
# Lines shorter than this are usually menu items/junk, not job titles.
MIN_LINE_LEN = 8
MAX_LINE_LEN = 140

# ---------------------------------------------------------------------------
# CORE LOGIC
# ---------------------------------------------------------------------------


def fetch_page_text(url: str) -> str:
    """Fetch a URL and return readable text (HTML stripped), one item per line."""
    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (job-search-agent)"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! Failed to fetch {url}: {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return text[:MAX_PAGE_CHARS]


def extract_matches(source_name: str, url: str, page_text: str) -> list:
    """Plain keyword search over the page's text lines. No API calls."""
    if not page_text:
        return []

    matches = []
    seen_lines = set()
    for line in page_text.split("\n"):
        line = line.strip()
        if not (MIN_LINE_LEN <= len(line) <= MAX_LINE_LEN):
            continue
        lower = line.lower()
        if line in seen_lines:
            continue
        if " " not in line.strip():
            # Skip run-together tokens like "ASSISTANTPROFESSOR1" -- these are
            # almost always filter-UI labels, not real job titles.
            continue
        for kw in JOB_KEYWORDS:
            kw_lower = kw.lower()
            if len(kw) <= SHORT_KEYWORD_MAX_LEN:
                # Whole-word match only, e.g. "EGS" but not "leGSlation".
                if re.search(rf"\b{re.escape(kw_lower)}\b", lower):
                    found = True
                else:
                    found = False
            else:
                found = kw_lower in lower
            if found:
                matches.append({
                    "title": line,
                    "matched_keyword": kw,
                    "source": source_name,
                    "source_url": url,
                })
                seen_lines.add(line)
                break
    return matches


def build_digest(new_jobs: list) -> str:
    """Plain-text digest, grouped by source."""
    lines = [f"{len(new_jobs)} new posting(s) matched your keywords:\n"]
    by_source = {}
    for job in new_jobs:
        by_source.setdefault(job["source"], []).append(job)

    for source, jobs in by_source.items():
        lines.append(f"\n=== {source} ===")
        for job in jobs:
            lines.append(f"- {job['title']}  (matched: '{job['matched_keyword']}')")
        lines.append(f"  Source: {jobs[0]['source_url']}")

    lines.append(
        "\n\nNote: this is plain keyword matching, not AI-reviewed, so some "
        "entries may be noise (nav text, unrelated mentions) rather than "
        "real job titles. Check the source link to confirm."
    )
    return "\n".join(lines)


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def job_id(job: dict) -> str:
    """A stable-ish identifier so we don't re-notify on the same posting."""
    normalized = re.sub(r"\s+", " ", job["title"].strip().lower())
    return f"{job['source']}::{normalized}"


def send_email(subject: str, body: str):
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    to_email = os.environ.get("TO_EMAIL", gmail_address)

    msg = MIMEMultipart()
    msg["From"] = gmail_address
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_address, gmail_app_password)
        server.send_message(msg)
    print(f"Email sent to {to_email}")


def main():
    seen = load_seen()
    all_matches = []

    for source in COMPANIES + ACADEMIC_SOURCES:
        print(f"Checking {source['name']}...")
        text = fetch_page_text(source["url"])
        matches = extract_matches(source["name"], source["url"], text)
        print(f"  -> {len(matches)} keyword match(es) found on page")
        all_matches.extend(matches)

    new_jobs = [j for j in all_matches if job_id(j) not in seen]
    print(f"\n{len(new_jobs)} new job(s) not seen before.")

    if new_jobs:
        digest = build_digest(new_jobs)
        send_email(
            subject=f"Job digest: {len(new_jobs)} new geothermal/academic posting(s)",
            body=digest,
        )
        seen.update(job_id(j) for j in new_jobs)
        save_seen(seen)
    else:
        print("Nothing new to report. No email sent.")


if __name__ == "__main__":
    main()
