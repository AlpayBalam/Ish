"""
Geothermal / Academic Job Search Agent
---------------------------------------
Fetches career pages (target companies) and academic job boards, asks Claude
to extract postings matching your keywords, filters out ones you've already
seen, ranks the new ones against your background, and emails you a digest.

Run manually with:  python job_agent.py
Runs automatically via the GitHub Actions workflow in .github/workflows/.
"""

import os
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from anthropic import Anthropic

# ---------------------------------------------------------------------------
# CONFIG - edit this section to change what the agent searches for
# ---------------------------------------------------------------------------

# Companies to check for corporate openings. Add/remove freely.
# "url" should point to the page listing their open roles.
COMPANIES = [
    {"name": "Ormat Technologies", "url": "https://www.ormat.com/en/careers/open-positions/"},
    {"name": "Fervo Energy", "url": "https://fervoenergy.com/careers/"},
    {"name": "Jacobs", "url": "https://careers.jacobs.com/search/?q=geothermal"},
    {"name": "Baker Hughes", "url": "https://careers.bakerhughes.com/global/en/search-results?keywords=geothermal"},
    {"name": "SLB", "url": "https://careers.slb.com/search-jobs?keywords=geothermal"},
    {"name": "Chevron New Energies", "url": "https://www.chevron.com/careers/search-jobs?keywords=geothermal"},
    {"name": "Sage Geosystems", "url": "https://www.sagegeosystems.com/careers"},
    {"name": "Constellation Energy", "url": "https://www.constellationenergy.com/careers/job-search.html?keywords=geothermal"},
]

# Academic job boards to check for faculty positions.
ACADEMIC_SOURCES = [
    {"name": "HigherEdJobs", "url": "https://www.higheredjobs.com/faculty/search.cfm?Keyword=geothermal"},
    {"name": "HigherEdJobs (Reservoir/Petroleum)", "url": "https://www.higheredjobs.com/faculty/search.cfm?Keyword=reservoir+engineering"},
    {"name": "AcademicJobsOnline", "url": "https://academicjobsonline.org/ajo/jobs"},
]

# Keywords that define a match (case-insensitive, partial match).
JOB_KEYWORDS = [
    "geothermal", "reservoir engineer", "reservoir engineering",
    "power plant design", "power plant optimization", "integrated geothermal",
    "associate professor", "professor", "assistant professor",
]

# Short background summary used to help Claude judge fit. Edit this to keep
# it current -- it is NOT your full CV, just enough context for ranking.
USER_BACKGROUND = """
PhD in Earth Resources Engineering (geothermal), extensive experience in
geothermal reservoir engineering (reservoir simulation, well testing,
tracer tests), and geothermal power plant design and optimization
(exergy analysis, flash/binary/hybrid cycles). Former academic (Associate
Professor / Professor level) at Kyushu University and Akita University;
currently Senior Scientist. Looking for senior reservoir engineering or
integrated geothermal engineer roles at established companies, or
associate/full professor positions in the US.
"""

SEEN_FILE = "seen_jobs.json"
MAX_PAGE_CHARS = 12000  # truncate fetched pages to keep API calls small/cheap

# ---------------------------------------------------------------------------
# CORE LOGIC
# ---------------------------------------------------------------------------

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def fetch_page_text(url: str) -> str:
    """Fetch a URL and return readable text (HTML stripped)."""
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
    """Ask Claude to pull out job postings matching our keywords."""
    if not page_text:
        return []

    prompt = f"""You are reading the text of a careers/jobs page from "{source_name}"
(fetched from {url}).

Find any job postings on this page that match ANY of these keywords or roles
(partial/related matches count): {", ".join(JOB_KEYWORDS)}

Return ONLY a JSON array (no other text, no markdown fences) of objects like:
[{{"title": "...", "location": "... or empty string", "snippet": "one sentence about the role"}}]

If there are no matches, return an empty array: []

PAGE TEXT:
{page_text}
"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        matches = json.loads(raw) if raw else []
        for m in matches:
            m["source"] = source_name
            m["source_url"] = url
        return matches
    except Exception as e:
        print(f"  ! Claude extraction failed for {source_name}: {e}")
        return []


def rank_and_summarize(new_jobs: list) -> str:
    """Ask Claude to write a short ranked digest of the new job matches."""
    if not new_jobs:
        return ""

    jobs_json = json.dumps(new_jobs, indent=2)
    prompt = f"""Here is my background:
{USER_BACKGROUND}

Here are newly found job postings (JSON):
{jobs_json}

Write a short email-friendly digest (plain text, no markdown headers) that:
1. Lists each posting with its title, company/source, location if known, and a
   1-2 sentence note on why it's a good or partial fit for my background.
2. Orders them best-fit first.
3. Includes the source_url for each so I can click through.

Keep it concise and scannable."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")


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
    return f"{job['source']}::{job.get('title','').strip().lower()}::{job.get('location','').strip().lower()}"


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
        digest = rank_and_summarize(new_jobs)
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
