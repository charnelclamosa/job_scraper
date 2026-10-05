"""
Configuration constants for the job matcher.
"""

import re

SITES = ["linkedin", "indeed", "jobstreet"]
DEFAULT_LOCATION = "Philippines"
DEFAULT_LIMIT = 30
DEFAULT_DAYS = 30
DEFAULT_MIN_MATCHES = 1
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 5
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20
INDEED_COUNTRY = "Philippines"
JOBSTREET_API_URL = "https://ph.jobstreet.com/api/jobsearch/v5/search"
JOBSTREET_JOB_URL = "https://ph.jobstreet.com/job/{job_id}"
JOBSTREET_SITE_KEY = "PH-Main"
JOBSTREET_PAGE_SIZE = 30
JOBSTREET_HEADERS = {
  "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
}
WORK_ARRANGEMENT_PATTERNS = [
  ("hybrid", re.compile(r"\bhybrid\b", re.IGNORECASE)),
  ("remote", re.compile(
    r"\b(?:remote|work[\s-]from[\s-]home|wfh)\b", re.IGNORECASE)),
  ("onsite", re.compile(
    r"\b(?:on[\s-]?site|in[\s-]office|office[\s-]based)\b", re.IGNORECASE)),
]