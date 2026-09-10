# Geothermal / Academic Job Search Agent

Checks a list of geothermal companies and academic job boards every 2 days,
uses Claude to find postings matching your target roles, and emails you a
ranked digest of anything new.

## Setup (one-time)

### 1. Create the GitHub repo
(done)

### 2. Get an Anthropic API key
1. Go to https://console.anthropic.com and sign in/sign up.
2. Go to **API Keys** → **Create Key**. Copy it (you won't see it again).
3. Note: this is billed separately from any claude.ai subscription — usage
   here (a few short calls every 2 days) should cost cents to a few dollars
   a month.

### 3. Create a Gmail App Password
1. Go to https://myaccount.google.com/security
2. Turn on **2-Step Verification** if it isn't already on.
3. Search for **App Passwords** (or go directly to
   https://myaccount.google.com/apppasswords), create one named e.g. "job
   agent", and copy the 16-character password shown.

### 4. Add your secrets to the GitHub repo
In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add each of these:

| Secret name          | Value                                          |
|-----------------------|-------------------------------------------------|
| `ANTHROPIC_API_KEY`   | the key from step 2                            |
| `GMAIL_ADDRESS`       | your Gmail address (used to send)              |
| `GMAIL_APP_PASSWORD`  | the 16-character app password from step 3      |
| `TO_EMAIL`            | saeidjalili@gmail.com (where the digest goes)  |

### 5. Test it
1. In your repo, go to the **Actions** tab.
2. Click **Job Search Agent** on the left, then **Run workflow** (top right)
   → **Run workflow** again to confirm.
3. Wait a minute or two, refresh, and click into the run to see the logs.
   If everything is set up right, you'll get an email digest (or a log
   saying "Nothing new to report" if there are no matches yet).

After that, it runs automatically every 2 days — no further action needed.

## Adjusting the search later

Open `job_agent.py` and edit:
- `COMPANIES` — add/remove companies or fix a career-page URL if a link
  goes stale.
- `ACADEMIC_SOURCES` — add more job boards or a specific university's
  careers page.
- `JOB_KEYWORDS` — add/remove keywords to widen or narrow matches.
- `USER_BACKGROUND` — keep this current; it's what Claude uses to judge
  fit and ranking.

Commit the change (or re-upload the edited file) and it takes effect on the
next scheduled run.

## A note on coverage

Some of the company career-page URLs (Jacobs, Baker Hughes, SLB, Chevron,
Constellation) use search-results pages that may load listings via
JavaScript, which a simple page fetch can't always see. If you notice a
company never turns up any matches even when you know they have open
roles, check that URL manually in your browser and swap in a more direct
listing page if needed — the script's fetch step is intentionally simple
so it's easy for you to fix.

Also worth doing in parallel: HigherEdJobs, LinkedIn, and Indeed all offer
free built-in job alerts (saved searches emailed to you) — those catch
things this script won't (e.g. university career pages not on
AcademicJobsOnline). This agent is a complement to those, not a full
replacement.
