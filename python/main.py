#!/usr/bin/env python3
"""
Match CV skills against live job postings.

Searches LinkedIn, Indeed, or JobStreet PH for recent job postings and
grades each one by how many of the skills listed in your CV appear in
the posting text. Results are printed to stdout, best match first, and
can optionally be saved to a CSV file. Progress and errors go to stderr.

Each result reports:
  > Job Title, Company, URL (job source website), Posted date,
    match grade (e.g. 4/6) and the list of matched skills

The CV file is a JSON file holding either a plain list of skills or an
object with a "skills" key:
  > ["Python", "Docker", "GCP"]
  > {"skills": ["Python", "Docker", "GCP"]}

Capabilities
------------
- Site selection: a single --site flag picks the job site to search
  (linkedin, indeed, or jobstreet).
- Date filter: --days limits results to postings from the last N days
  (defaults to 30).
- Skill grading: whole-word, case-insensitive matching, so "R" does not
  match inside "React" while "C++" and "C#" still work. Skills are
  graded as matched/total, e.g. 4/6 (66.7%).
- Minimum match filter: --min-matches hides postings that matched fewer
  than N skills (defaults to 1).
- Retry on failure: JobStreet page requests are retried before that
  page is given up on; pages already fetched are still graded.
- Atomic CSV export: --csv writes to a temporary .part path and renames
  it into place only after a successful write.

Notes
-----
- LinkedIn and Indeed go through the `python-jobspy` library. LinkedIn
  descriptions are fetched per posting, which is slow but needed for
  accurate matching, and LinkedIn rate-limits heavily.
- JobStreet PH is not supported by python-jobspy, so its undocumented
  website JSON endpoint is used instead (best-effort; it may change or
  block requests at any time). It only returns a short teaser, so its
  grades are based on title + teaser and are less reliable.
- Scraping these sites may go against their terms of service. Keep
  usage light and personal.

Requirements
------------
  $ pip install python-jobspy pandas requests

Usage
--------
Search LinkedIn (last 30 days):
  $ python job_matcher.py --cv cv.json --site linkedin --query "embedded engineer"

Search Indeed for the last 7 days:
  $ python job_matcher.py --cv cv.json --site indeed --query "python developer" --days 7

Search JobStreet PH, only postings matching at least 3 skills:
  $ python job_matcher.py --cv cv.json --site jobstreet --query "data engineer" --min-matches 3

Search a specific location and save the results to CSV:
  $ python job_matcher.py --cv cv.json --site indeed --query "devops" --location "Metro Manila" --csv results.csv
"""

from __future__ import annotations
import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from job import Job
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from config import (
  SITES, DEFAULT_LOCATION, DEFAULT_LIMIT, DEFAULT_DAYS,
  DEFAULT_MIN_MATCHES, DEFAULT_RETRIES, DEFAULT_RETRY_DELAY_SECONDS,
  DEFAULT_REQUEST_TIMEOUT_SECONDS, INDEED_COUNTRY, JOBSTREET_API_URL,
  JOBSTREET_JOB_URL, JOBSTREET_SITE_KEY, JOBSTREET_PAGE_SIZE,
  JOBSTREET_HEADERS, WORK_ARRANGEMENT_PATTERNS)

# ============================================================================
# LOGGING
# ============================================================================
def configure_logging() -> None:
  logging.basicConfig(
    level=logging.INFO,
    format=(
      "%(asctime)s "
      "%(levelname)-8s "
      "%(message)s"
    ),
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
  )

logger = logging.getLogger(__name__)

# ============================================================================
# ARGUMENT PARSING
# ============================================================================
def positive_int(num) -> int:
  try:
    num = int(num)
  except ValueError as exc:
    raise argparse.ArgumentTypeError(
      f"Invalid integer '{num}'."
    ) from exc

  if num < 1:
    raise argparse.ArgumentTypeError("Number must be greater than/equal to 1.")

  return num


def non_negative_int(num) -> int:
  try:
    num = int(num)
  except ValueError as exc:
    raise argparse.ArgumentTypeError(
      f"Invalid integer '{num}'."
    ) from exc

  if num < 0:
    raise argparse.ArgumentTypeError("Number must be greater than/equal to 0.")

  return num


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description=("Match CV skills against live job postings."),
    formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("-c", "--cv", required=True, type=Path,
    help="Path to the CV skills JSON file.")
  parser.add_argument("-s", "--site", required=True, choices=SITES,
    help="Job site to search.")
  parser.add_argument("-q", "--query", required=True,
    help="Search keywords, e.g. \"embedded engineer\".")
  parser.add_argument("-l", "--location", default=DEFAULT_LOCATION,
    help=f"Job location. Default: {DEFAULT_LOCATION}.")
  parser.add_argument("-n", "--limit", type=positive_int,
    default=DEFAULT_LIMIT,
    help=f"Maximum postings to fetch. Default: {DEFAULT_LIMIT}.")
  parser.add_argument("-d", "--days", type=positive_int,
    default=DEFAULT_DAYS,
    help=(
      "Only include postings from the last N days. "
      f"Default: {DEFAULT_DAYS}."))
  parser.add_argument("-m", "--min-matches", type=non_negative_int,
    default=DEFAULT_MIN_MATCHES, metavar="N",
    help=(
      "Hide postings that matched fewer than N skills. "
      f"Default: {DEFAULT_MIN_MATCHES}."))
  parser.add_argument("-o", "--csv", type=Path,
    help="Optional path to save the results as a CSV file.")

  return parser

# ============================================================================
# CV HANDLING
# ============================================================================
def load_skills(path) -> dict[str, list[str]]:
  """
  Load skills from a CV JSON file.

  Each entry is either a plain string or an object with a "name" and
  optional "aliases". A skill counts as matched when its name or any of
  its aliases appears in a posting, and counts once.

  Parameters
  ----------
  path : Path
    JSON file holding a list of skills, or an object with a "skills" key.

  Returns
  -------
  dict[str, list[str]]
    Mapping of skill name to every term to search for (name first).

  Raises
  ------
  ValueError
    When the file is not valid JSON or contains no skills.
  """
  with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

  entries = data.get("skills", []) if isinstance(data, dict) else data
  skills: dict[str, list[str]] = {}

  for entry in entries:
    if isinstance(entry, dict):
      name = str(entry.get("name", "")).strip()
      aliases = [str(alias).strip() for alias in entry.get("aliases", [])]
    else:
      name = str(entry).strip()
      aliases = []

    if not name:
      continue

    terms = skills.setdefault(name, [name])
    for alias in aliases:
      if alias and alias not in terms:
        terms.append(alias)

  if not skills:
    raise ValueError(f"No skills found in {path}")

  return skills

# ============================================================================
# SKILL MATCHING
# ============================================================================
def skill_pattern(terms) -> re.Pattern:
  """
  Return a whole-word, case-insensitive pattern for one skill.

  Spaces and hyphens inside a term are interchangeable and optional, so
  "Full-Stack" also matches "full stack" and "fullstack". Alphanumerics
  plus '+' and '#' count as word characters, so "C++" and "C#" work. A
  trailing '&' is blocked so "R" does not match "R&D".

  Parameters
  ----------
  terms : list[str]
    The skill name and its aliases.
  """
  alternatives = "|".join(
    r"[\s-]*".join(re.escape(word) for word in re.split(r"[\s-]+", term) if word)
    for term in terms)

  return re.compile(
    r"(?<![A-Za-z0-9+#])(?:" + alternatives + r")(?![A-Za-z0-9+#&])",
    re.IGNORECASE)

def grade_job(job, skills, patterns) -> Job:
  """
  Grade one job by how many CV skills appear in its title and text.

  Parameters
  ----------
  job : Job
    Job posting to grade. Updated in place.
  skills : list[str]
    CV skills, in order.
  patterns : dict[str, re.Pattern]
    Mapping of skill to its compiled pattern.

  Returns
  -------
  Job
    The same job, with `matched`, `score` and `score_pct` filled in.
  """
  haystack = f"{job.title}\n{job.text}"

  job.matched = [skill for skill in skills if patterns[skill].search(haystack)]
  job.score = f"{len(job.matched)}/{len(skills)}"
  job.score_pct = round(100 * len(job.matched) / len(skills), 1)

  return job

def grade_jobs(jobs, skills) -> list[Job]:
  """
  Grade all jobs and sort them by number of matched skills, best first.

  Parameters
  ----------
  jobs : list[Job]
    Job postings to grade.
  skills : dict[str, list[str]]
    CV skills, as returned by `load_skills`.

  Returns
  -------
  list[Job]
    Graded jobs sorted by matched skill count, descending.
  """
  patterns = {name: skill_pattern(terms) for name, terms in skills.items()}
  graded = [grade_job(job, skills, patterns) for job in jobs]

  return sorted(graded, key=lambda job: len(job.matched), reverse=True)

# ============================================================================
# SEARCH LOGIC
# ============================================================================
def clean_text(value) -> str:
  """Return `value` as a string, treating None/NaN/NaT as empty."""
  if value is None or value != value:  # NaN and NaT never equal themselves
    return ""

  return str(value)

def search_jobspy(site, query, location, limit, days) -> list[Job]:
  """
  Search LinkedIn or Indeed through the python-jobspy library.

  Parameters
  ----------
  site : str
    Either "linkedin" or "indeed".
  query : str
    Search keywords.
  location : str
    Job location.
  limit : int
    Maximum postings to fetch.
  days : int
    Only include postings from the last `days` days.

  Returns
  -------
  list[Job]
    Postings found, ungraded.
  """
  try:
    from jobspy import scrape_jobs
  except ImportError as exc:
    raise RuntimeError(
      "Missing dependency. Run: pip install python-jobspy pandas"
    ) from exc

  kwargs = {
    "site_name": [site],
    "search_term": query,
    "location": location,
    "results_wanted": limit,
    "hours_old": 24 * days,
    "country_indeed": INDEED_COUNTRY,  # only used by Indeed
  }

  if site == "linkedin":
    # Slower, but needed for real skill matching.
    kwargs["linkedin_fetch_description"] = True

  jobs = []
  df = scrape_jobs(**kwargs)

  for _, row in df.iterrows():
    structured = clean_text(row.get("work_from_home_type"))
    if not structured and str(row.get("is_remote")).lower() == "true":
      structured = "remote"

    title = clean_text(row.get("title"))
    location = clean_text(row.get("location"))
    description = clean_text(row.get("description"))

    jobs.append(Job(
      title=title,
      company=clean_text(row.get("company")),
      url=clean_text(row.get("job_url")),
      site=site,
      posted=clean_text(row.get("date_posted"))[:10],
      location=location,
      work_type=detect_work_arrangement(
        structured, title, location, description),
      text=description))

  return jobs

def fetch_jobstreet_page(params, retries, retry_delay) -> list[dict]:
  """
  Fetch one page of JobStreet PH search results.

  Parameters
  ----------
  params : dict
    Query string parameters for the search request.
  retries : int
    Maximum request attempts.
  retry_delay : int
    Seconds to wait between attempts.

  Returns
  -------
  list[dict]
    Raw job items from the response. Empty when there are no more pages.
  """
  for attempt in range(1, retries + 1):
    try:
      logger.info("REQUEST jobstreet page=%s attempt=%s/%s",
        params["page"], attempt, retries)

      response = requests.get(
        JOBSTREET_API_URL,
        params=params,
        headers=JOBSTREET_HEADERS,
        timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS)
      response.raise_for_status()

      return response.json().get("data", [])

    except Exception as exc:
      logger.warning("Request failed for jobstreet page=%s attempt=%s/%s: %s",
        params["page"], attempt, retries, exc)

      if attempt == retries:
        raise

      logger.info("Retrying in %s seconds...", retry_delay)
      time.sleep(retry_delay)

  return []

def search_jobstreet(query, location, limit, days,
    retries=DEFAULT_RETRIES,
    retry_delay=DEFAULT_RETRY_DELAY_SECONDS) -> list[Job]:
  """
  Search JobStreet PH through its website JSON endpoint.

  The date window is sent to the server and also checked against each
  posting's listing date, in case the server ignores it. Postings with
  no usable date are kept.

  Parameters
  ----------
  query : str
    Search keywords.
  location : str
    Job location.
  limit : int
    Maximum postings to return.
  days : int
    Only include postings from the last `days` days.
  retries : int, optional
    Maximum request attempts per page. Default is `DEFAULT_RETRIES`.
  retry_delay : int, optional
    Seconds to wait between attempts. Default is
    `DEFAULT_RETRY_DELAY_SECONDS`.

  Returns
  -------
  list[Job]
    Postings found, ungraded. Pages already fetched are still returned
    if a later page fails.
  """
  cutoff = datetime.now(timezone.utc) - timedelta(days=days)
  jobs: list[Job] = []
  page = 1

  while len(jobs) < limit:
    params = {
      "siteKey": JOBSTREET_SITE_KEY,
      "keywords": query,
      "where": location,
      "page": page,
      "pageSize": JOBSTREET_PAGE_SIZE,
      "dateRange": days,
    }

    try:
      items = fetch_jobstreet_page(params, retries, retry_delay)
    except Exception:
      logger.error("Giving up on jobstreet page=%s, keeping %s jobs so far.",
        page, len(jobs))
      break

    if not items:
      break

    for item in items:
      posted = item.get("listingDate", "")

      try:
        posted_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
        if posted_at < cutoff:
          continue
      except ValueError:
        pass  # no/unknown date: keep the job

      advertiser = item.get("advertiser") or {}
      locations = item.get("locations") or [{}]

      jobs.append(Job(
        title=item.get("title", ""),
        company=item.get("companyName") or advertiser.get("description", ""),
        location=locations[0].get("label", ""),
        work_type=detect_work_arrangement(
          clean_text(item.get("workArrangements")),
          item.get("title", ""), item.get("teaser", "")),
        url=JOBSTREET_JOB_URL.format(job_id=item.get("id")),
        site="jobstreet",
        posted=posted[:10],
        text=item.get("teaser", "")))

    page += 1

  return jobs[:limit]

def search_jobs(site, query, location, limit, days) -> list[Job]:
  """Dispatch the search to the scraper that handles `site`."""
  if site == "jobstreet":
    return search_jobstreet(query, location, limit, days)

  return search_jobspy(site, query, location, limit, days)

def detect_work_arrangement(structured, *texts) -> str:
  """
  Classify a posting as "hybrid", "remote", "onsite" or "unknown".

  The site's structured value is checked first. If it says nothing, the
  title, location and description are searched for keywords. "hybrid" is
  checked before "remote" so "hybrid, 2 days remote" is not misread.

  Parameters
  ----------
  structured : str
    Work-arrangement value from the site itself, or "" if it has none.
  *texts : str
    Free text to fall back on (title, location, description/teaser).

  Returns
  -------
  str
    One of "hybrid", "remote", "onsite", "unknown".
  """
  for source in (structured, "\n".join(texts)):
    for label, pattern in WORK_ARRANGEMENT_PATTERNS:
      if pattern.search(source):
        return label

  return "unknown"

# ============================================================================
# OUTPUT
# ============================================================================
def print_results(jobs) -> None:
  """Print graded jobs to stdout, one block per job."""
  for rank, job in enumerate(jobs, start=1):
    print(f"\n#{rank}  {job.title}")
    print(f"    Company : {job.company}")
    print(f"    Location: {job.location or 'unknown'}")
    print(f"    Work    : {job.work_type}")
    print(f"    Match   : {job.score} ({job.score_pct}%)"
      f"  -> {', '.join(job.matched) or '-'}")
    print(f"    Posted  : {job.posted or 'unknown'}")
    print(f"    URL     : {job.url}")

def save_csv(jobs, path) -> None:
  """
  Save graded jobs to a CSV file.

  Writes to a temporary .part file first, then renames it into place
  after a successful write, so a failed run never leaves a half-written
  CSV at the final path.

  Parameters
  ----------
  jobs : list[Job]
    Graded jobs to save.
  path : Path
    Destination CSV path.
  """
  path.parent.mkdir(parents=True, exist_ok=True)
  temp_path = path.with_suffix(f"{path.suffix}.part")

  with open(temp_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(
      ["Job Title", "Company", "Location", "Work Arrangement", 
       "URL", "Posted", "Match", "Match %", "Matched Skills"])

    for job in jobs:
      writer.writerow(
        [job.title, job.company, job.location, job.work_type, job.url, 
         job.posted, job.score, job.score_pct, "; ".join(job.matched)])

  os.replace(temp_path, path)
  logger.info("SAVED %s rows to %s", len(jobs), path)

# ============================================================================
# MAIN
# ============================================================================
def main() -> int:
  parser = build_parser()
  args = parser.parse_args()
  configure_logging()

  logger.info("Job matching started")
  logger.info("Site: %s", args.site)
  logger.info("Query: %s", args.query)
  logger.info("Location: %s", args.location)
  logger.info("Posted within: last %s days", args.days)
  logger.info("Limit: %s", args.limit)
  logger.info("Minimum matches: %s", args.min_matches)

  try:
    skills = load_skills(args.cv)
    logger.info("Loaded %s skills: %s", len(skills), ", ".join(skills))

    jobs = search_jobs(args.site, args.query, args.location, args.limit,
      args.days)
    logger.info("Fetched %s postings", len(jobs))

    jobs = grade_jobs(jobs, skills)
    shown = [job for job in jobs if len(job.matched) >= args.min_matches]

    logger.info("SEARCH SUMMARY fetched=%s shown=%s hidden=%s",
      len(jobs), len(shown), len(jobs) - len(shown))

    if not shown:
      logger.warning("No jobs found matching your criteria.")
      return 0

    print_results(shown)

    if args.csv:
      save_csv(shown, args.csv)

    return 0
  except KeyboardInterrupt:
    logger.warning("Operation interrupted by user.")
    return 130
  except (OSError, ValueError) as exc:
    logger.error("%s", exc)
    return 1
  except Exception:
    logger.exception("Fatal error.")
    return 1

if __name__ == "__main__":
  sys.exit(main())