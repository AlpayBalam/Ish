"""
Geothermal / Academic Job Search Agent (broad keyword-search version)
----------------------------------------------------------------------
Instead of checking a fixed list of company career pages, this version
searches the Adzuna job API (a free aggregator covering thousands of job
sources across the US) by keyword -- so it isn't limited to companies you
manually list, and isn't broken by individual sites blocking scripts.

It also keeps a couple of directly-verified company career pages as a
supplement, since a handful of employers post roles there before/instead of
aggregators picking them up.

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

# Broad keyword searches run against the Adzuna API (covers the whole US job
# market, not just companies you've listed). Each entry is a separate search
# query -- add/remove freely. Keep this list modest: each query uses one of
# your free 1,000 monthly Adzuna API calls per run.
ADZUNA_QUERIES = [
    "geothermal",
    "geothermal reservoir engineer",
    "geothermal professor",
    "assistant professor geothermal",
    "earth resources engineering faculty",
    "petroleum engineering professor",
    "enhanced geothermal systems",
    "superhot geothermal",
    "subsurface energy storage",
    "geothermal power plant engineer",
]

ADZUNA_COUNTRY = "us"
ADZUNA_RESULTS_PER_QUERY = 20
# Only consider postings from at most this many days ago (keeps results fresh
# and avoids re-surfacing very old listings on first run).
ADZUNA_MAX_DAYS_OLD = 10

# Words that, if present, mean the posting is almost certainly noise for you
# (residential/HVAC "geothermal heat pump installer" jobs, hospitality jobs
# near geothermal spas, etc. -- these share the keyword but aren't your kind
# of role). Adzuna excludes any posting containing any of these words.
ADZUNA_EXCLUDE_WORDS = (
    "hvac installer technician residential plumbing plumber "
    "cook chef banquet massage spa therapist naturalist hospitality"
)

# A few specific company career pages, verified to work with a plain script
# fetch (no JavaScript rendering, no bot-blocking). This is a supplement to
# the broad Adzuna search above, not the main mechanism -- add more here only
# if you've personally confirmed (by visiting in an incognito tab) that the
# URL shows real job listings and isn't blocked.
COMPANIES = [
    {"name": "Ormat Technologies", "url": "https://careers.ormat.com/search/"},
    {"name": "Zanskar", "url": "https://jobs.lever.co/Zanskar"},
]

# Academic job boards -- currently empty. HigherEdJobs and AcademicJobsOnline
# both block or don't support plain script fetches (see README/notes in past
# versions). Their own free "Job Alert" (saved search emailed directly by
# them) is the better option for that source until a workaround is found.
ACADEMIC_SOURCES = []

# Keywords used only for the direct COMPANIES page checks above (Adzuna
# already ranks/filters by your query terms, so it doesn't need this list).
# Multi-word phrases match as substrings; short words match whole-word only.
JOB_KEYWORDS = [
    "geothermal", "reservoir engineer", "reservoir engineering",
    "power plant design", "power plant optimization", "integrated geothermal",
    "associate professor", "professor", "assistant professor",
    "senior scientist", "reservoir simulation", "reservoir modeling",
    "reservoir modelling", "production forecasting", "production prediction",
    "history matching", "wellbore analysis", "well testing",
    "exergy analysis", "exergy", "thermodynamic analysis", "thermo-economic",
    "superhot geothermal", "supercritical geothermal",
    "enhanced geothermal systems", "EGS", "geological energy storage",
    "compressed air energy storage", "CAES", "subsurface energy",
    "flash cycle", "binary geothermal", "organic rankine cycle", "ORC",
    "ground source heat pump", "ground-source heat pump", "combined-cycle",
    "combined cycle", "district heating", "cascade utilization",
    "techno-economic", "life cycle assessment", "LCOE", "LCA",
    "make-up well", "well placement", "resource assessment",
    "geothermal exploration", "feasibility studies", "reservoir characterization",
    "environmental impact assessment", "EIA", "drilling operations",
    "field implementation", "geothermal project development",
    "geothermal power systems", "production optimization",
    "injection optimization", "numerical modeling", "numerical modelling",
    "contractor management", "consultant management", "stakeholder engagement",
    "strategic partnerships", "cross-functional leadership",
    "international collaboration", "technology deployment", "energy transition",
    "program leadership", "government-industry engagement",
    "data-driven geothermal workflows", "multi-well planning",
    "field optimization", "heat extraction", "conceptual modeling",
    "conceptual modelling", "integrated energy systems", "machine learning",
    "reservoir forecasting", "advanced geothermal systems",
    "subsurface energy leader", "geothermal systems", "subsurface energy storage",
    "underground energy storage", "geological thermal energy storage", "GTES",
    "carbon capture and storage", "CCS", "carbon capture, utilization, and storage",
    "CCUS", "CO2 storage", "carbon dioxide storage", "caprock integrity",
    "geomechanics", "geomechanical", "THMC coupling", "fracture permeability",
    "fracture mechanics", "heat flow modeling", "heat-flow modelling",
    "high-enthalpy", "wellbore stability", "wellbore design",
    "reactive flow modeling", "stimulation", "permeability modeling",
    "permeability evolution", "digital twin", "digital twins",
    "repurposing oil and gas wells", "abandoned oil and gas wells",
    "hydrogen storage", "subsurface hydrogen", "geohazards", "induced seismicity",
    "land subsidence", "remote sensing", "geospatial modeling", "aquifer",
    "groundwater", "critical minerals", "geothermal brines", "produced waters",
    "AI-driven", "AI-enabled", "multiphase flow",
    "geothermal reservoir modeling and management",
]

SHORT_KEYWORD_MAX_LEN = 5
SEEN_FILE = "seen_jobs.json"
MAX_PAGE_CHARS = 20000
MIN_LINE_LEN = 8
MAX_LINE_LEN = 140

# ---------------------------------------------------------------------------
# ADZUNA SEARCH (broad, keyword-based, not limited to a company list)
# ---------------------------------------------------------------------------


def search_adzuna(query: str) -> list:
    """Query the Adzuna API for one keyword phrase. Returns a list of jobs."""
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("  ! ADZUNA_APP_ID / ADZUNA_APP_KEY not set -- skipping Adzuna search")
        return []

    url = f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": query,
        "what_exclude": ADZUNA_EXCLUDE_WORDS,
        "results_per_page": ADZUNA_RESULTS_PER_QUERY,
        "max_days_old": ADZUNA_MAX_DAYS_OLD,
        "sort_by": "date",
        "content-type": "application/json",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        print(f"  ! Adzuna search failed for '{query}': {e}")
        return []

    jobs = []
    for item in data.get("results", []):
        jobs.append({
            "title": item.get("title", "").strip(),
            "company": (item.get("company") or {}).get("display_name", "Unknown"),
            "location": (item.get("location") or {}).get("display_name", ""),
            "url": item.get("redirect_url", ""),
            "id": str(item.get("id", "")),
            "source": f"Adzuna search: '{query}'",
        })
    return jobs


# ---------------------------------------------------------------------------
# DIRECT COMPANY PAGE CHECKS (supplement to the Adzuna search)
# ---------------------------------------------------------------------------


def fetch_page_text(url: str) -> str:
    """Fetch a URL and return readable text (HTML stripped), one item per line."""
    try:
        resp = requests.get(
            url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (job-search-agent)"}
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! Failed to fetch {url}: {e}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)[:MAX_PAGE_CHARS]


def extract_matches_from_page(source_name: str, url: str, page_text: str) -> list:
    """Plain keyword search over a fetched company page's text lines."""
    if not page_text:
        return []

    matches = []
    seen_lines = set()
    for line in page_text.split("\n"):
        line = line.strip()
        if not (MIN_LINE_LEN <= len(line) <= MAX_LINE_LEN):
            continue
        if line in seen_lines or " " not in line:
            continue
        lower = line.lower()
        for kw in JOB_KEYWORDS:
            kw_lower = kw.lower()
            if len(kw) <= SHORT_KEYWORD_MAX_LEN:
                found = bool(re.search(rf"\b{re.escape(kw_lower)}\b", lower))
            else:
                found = kw_lower in lower
            if found:
                matches.append({
                    "title": line,
                    "company": source_name,
                    "location": "",
                    "url": url,
                    "id": f"{source_name}::{line.lower()}",
                    "source": source_name,
                })
                seen_lines.add(line)
                break
    return matches


# ---------------------------------------------------------------------------
# SHARED LOGIC: dedupe, digest, email
# ---------------------------------------------------------------------------


def load_seen() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def job_key(job: dict) -> str:
    if job.get("id"):
        return f"{job['source']}::{job['id']}"
    normalized = re.sub(r"\s+", " ", job["title"].strip().lower())
    return f"{job['source']}::{normalized}"


def build_digest(new_jobs: list) -> str:
    lines = [f"{len(new_jobs)} new posting(s) found:\n"]
    by_source = {}
    for job in new_jobs:
        by_source.setdefault(job["source"], []).append(job)

    for source, jobs in by_source.items():
        lines.append(f"\n=== {source} ===")
        for job in jobs:
            loc = f" ({job['location']})" if job.get("location") else ""
            lines.append(f"- {job['title']} @ {job['company']}{loc}")
            if job.get("url"):
                lines.append(f"  {job['url']}")

    lines.append(
        "\n\nNote: Adzuna results are ranked by your search keywords but not "
        "individually verified -- check each link to confirm fit. Direct "
        "company-page results use plain keyword matching, so an occasional "
        "non-job line may slip through."
    )
    return "\n".join(lines)


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
    all_jobs = []

    for query in ADZUNA_QUERIES:
        print(f"Searching Adzuna for '{query}'...")
        results = search_adzuna(query)
        print(f"  -> {len(results)} result(s)")
        all_jobs.extend(results)

    for company in COMPANIES:
        print(f"Checking {company['name']}...")
        text = fetch_page_text(company["url"])
        matches = extract_matches_from_page(company["name"], company["url"], text)
        print(f"  -> {len(matches)} keyword match(es) found on page")
        all_jobs.extend(matches)

    new_jobs = [j for j in all_jobs if job_key(j) not in seen]
    print(f"\n{len(new_jobs)} new job(s) not seen before.")

    if new_jobs:
        digest = build_digest(new_jobs)
        send_email(
            subject=f"Job digest: {len(new_jobs)} new geothermal/academic posting(s)",
            body=digest,
        )
        seen.update(job_key(j) for j in new_jobs)
        save_seen(seen)
    else:
        print("Nothing new to report. No email sent.")


if __name__ == "__main__":
    main()
