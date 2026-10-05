"""
Data model for job postings.

Defines the `Job` record shared by the scrapers, the skill grader and the
output writers in main.py.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Job:
  """
  One job posting plus its skill-match result.

  Attributes
  ----------
  title : str
    Job title.
  company : str
    Hiring company.
  url : str
    Link to the posting on the source site.
  site : str
    Source site: "linkedin", "indeed" or "jobstreet".
  posted : str
    Posting date as YYYY-MM-DD, or "" when the site gives none.
  text : str
    Description (or teaser) used for skill matching.
  location : str
    Job location as listed by the site.
  work_type : str
    "hybrid", "remote", "onsite" or "unknown".
  matched : list[str]
    CV skills found in the posting. Filled in by grading.
  score : str
    Match grade as matched/total, e.g. "4/17". Filled in by grading.
  score_pct : float
    Match grade as a percentage. Filled in by grading.
  """
  title: str
  company: str
  url: str
  site: str
  posted: str = ""
  text: str = ""
  location: str = ""
  work_type: str = "unknown"
  matched: list[str] = field(default_factory=list)
  score: str = ""
  score_pct: float = 0.0