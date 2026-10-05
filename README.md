# Job Scraper

> Note: This is only a personal side project, built for my own job hunting. It's provided as-is, with no guarantees, and may break whenever the job sites change.
Searches **LinkedIn**, **Indeed**, or **JobStreet PH** for recent job postings and grades each one by how many of the skills in your CV appear in the posting. Results are printed to the terminal, best match first, and saved to a CSV file.

For each posting you get:

- Job title, company, and location
- Work arrangement (`remote`, `hybrid`, `onsite`, or `unknown`)
- Match grade (e.g. `5/17 (29.4%)`) and the list of matched skills
- Posted date
- URL of the posting on the source site

## Project structure

```
.
├── data/
│   └── skills.json      # your skills (see "Skills file")
├── python/
│   ├── main.py          # CLI entry point: search, grade, output
│   ├── job.py           # Job dataclass
│   └── config.py        # constants: defaults, URLs, headers, patterns
├── output/              # generated CSV files (created on first run)
├── Dockerfile
├── Makefile
└── requirements.txt
```

## Requirements

- Docker (recommended), or Python **3.10+** to run directly
- Python dependencies: `python-jobspy`, `pandas`, `requests`

`python-jobspy` requires Python 3.10 or newer, so the Docker base image must be 3.10+ (for example `python:3.12-slim`). On `python:3.9-slim`, `pip install` fails with "No matching distribution found for python-jobspy".

## Quick start

1. Build the image:

   ```bash
   make build
   ```

2. Put your skills in `data/skills.json` (format below).

3. Run a search:

   ```bash
   make run QUERY="cloud engineer"
   ```

Results print in the terminal and are saved to `output/cloud-engineer-linkedin-30d.csv`.

## Usage

`QUERY` is required. Everything else has a default and can be overridden on the command line:

```bash
make run QUERY="cloud engineer" DAYS=7
make run QUERY="cloud engineer" SITE=jobstreet DAYS=7 MIN_MATCHES=1
make run QUERY="python developer" SITE=indeed LOCATION="Metro Manila" LIMIT=50
make run QUERY="devops" CV=data/other_skills.json
```

| Variable | Default | Description |
| --- | --- | --- |
| `QUERY` | (required) | Search keywords |
| `SITE` | `linkedin` | `linkedin`, `indeed`, or `jobstreet` |
| `CV` | `data/skills.json` | Path to your skills file |
| `LOCATION` | `Philippines` | Job location |
| `DAYS` | `30` | Only include postings from the last N days |
| `LIMIT` | `30` | Maximum postings to fetch |
| `MIN_MATCHES` | `3` | Hide postings that matched fewer than N skills |
| `OUTPUT_DIR` | `output` | Folder for CSV files |

The CSV filename is built from the query, site and day window: `output/<query-slug>-<site>-<days>d.csv`. For example, `QUERY="Cloud Engineer" SITE=indeed DAYS=7` writes `output/cloud-engineer-indeed-7d.csv`. A CSV is only written when at least one posting passes the `MIN_MATCHES` filter.

The container runs as your own user (`--user`), so output files are owned by you, not root.

### Example output

```
#1  Cloud Engineer
    Company : Example Corp
    Location: Taguig, Metro Manila
    Work    : hybrid
    Match   : 6/17 (35.3%)  -> Python, GCP, Linux, SQL, Git, DevOps
    Posted  : 2026-10-01
    URL     : https://...
```

The CSV has the columns: `Job Title`, `Company`, `Location`, `Work Arrangement`, `URL`, `Posted`, `Match`, `Match %`, `Matched Skills`.

## Skills file

`data/skills.json` holds your skills. Each entry is either a plain string, or an object with a `name` and optional `aliases`:

```json
{
  "skills": [
    "Python",
    "Linux",
    {"name": "GCP", "aliases": ["Google Cloud", "Google Cloud Platform"]},
    {"name": "SQL", "aliases": ["PostgreSQL", "Postgres", "MySQL"]},
    {"name": "Full-Stack Development", "aliases": ["full stack", "fullstack"]},
    {"name": "DevOps", "aliases": ["CI/CD"]}
  ]
}
```

A plain list (`["Python", "Linux"]`) also works.

### How matching works

- A skill counts as **matched once** if its name **or any alias** appears in the job title or description. Aliases for the same skill don't inflate the score.
- Matching is **case-insensitive** and **whole-word**: `R` does not match inside `React`, and `SQL` does not match inside `NoSQL`.
- Spaces and hyphens in a term are interchangeable and optional, so `Full-Stack` also matches `full stack` and `fullstack`.
- `+` and `#` count as part of a word, so `C++` and `C#` work.
- A skill followed by `&` is not matched, so `R` does not match `R&D`.
- The grade is `matched skills / total skills in your file`.

Tips for a good skills list:

- Use short terms that real postings contain. A phrase like "Technical Requirements & Specification" almost never appears word for word.
- Add aliases only for true synonyms of the same skill. Adding adjacent skills you haven't claimed makes the grade meaningless.
- If a skill matches almost every posting (such as `Automation`), it adds little signal. If it never matches, it's probably too abstract.

### Work arrangement

The script uses the site's own work-type field when it exists. Otherwise it looks for keywords (`hybrid`, `remote` / `work from home` / `WFH`, `onsite` / `in-office`) in the title, location and description. `hybrid` is checked before `remote`. Many postings stay `unknown`, and keyword matching can misread phrases like "no remote work", so treat this column as a hint.

## Running without Docker

```bash
pip install -r requirements.txt

python python/main.py --cv data/skills.json --site linkedin \
  --query "cloud engineer" --days 7 --csv output/results.csv
```

| Option | Short | Default | Description |
| --- | --- | --- | --- |
| `--cv` | `-c` | (required) | Path to the skills JSON file |
| `--site` | `-s` | (required) | `linkedin`, `indeed`, or `jobstreet` |
| `--query` | `-q` | (required) | Search keywords |
| `--location` | `-l` | `Philippines` | Job location |
| `--limit` | `-n` | `30` | Maximum postings to fetch |
| `--days` | `-d` | `30` | Only include postings from the last N days |
| `--min-matches` | `-m` | `1` | Hide postings that matched fewer than N skills |
| `--csv` | `-o` | none | Save results to this CSV path |

Results go to stdout and logs go to stderr, so you can redirect the results without the log lines. Exit codes: `0` success, `1` error, `130` interrupted.

Default values, URLs, headers and the work-arrangement patterns live in `python/config.py`.

## Makefile targets

| Target | What it does |
| --- | --- |
| `make build` | Build the Docker image |
| `make run QUERY=...` | Run the job search (see above) |
| `make run-reload` | Start the gunicorn app with hot reload on `PORT` (default 8080) |
| `make logs` | Stream logs from the running container |
| `make python-cli` | Open a Python shell in a new container |
| `make bash` | Open a bash shell in a new container |
| `make stop` | Stop the running container |
| `make clean` | Remove the built image |

## Site notes and limitations

- **LinkedIn / Indeed** use the [`python-jobspy`](https://pypi.org/project/python-jobspy/) library. LinkedIn descriptions are fetched per posting, which is slow but needed for accurate matching. LinkedIn also rate-limits heavily, so keep `LIMIT` modest.
- **JobStreet PH** is not supported by `python-jobspy`, so the script calls the same JSON endpoint the website uses. This endpoint is undocumented and may change or block requests at any time. It only returns a short teaser, not the full description, so grades from JobStreet are lower and less reliable. Use a lower `MIN_MATCHES` (for example `1`) with this site.
- The date filter is applied by the site and, for JobStreet, checked again in the script. Postings with no date are kept and show `unknown`.
- Scraping these sites may go against their terms of service. Keep usage light and personal.

## Troubleshooting

**`python-jobspy` fails to install (`No matching distribution found`)**
The base image is Python 3.9 or older. Use `python:3.10-slim` or newer in the Dockerfile and rebuild.

**`SEARCH SUMMARY fetched=30 shown=0 hidden=30`**
The search worked, but every posting matched fewer skills than `MIN_MATCHES`. Lower it, or use `MIN_MATCHES=0` to see everything. This is most common with JobStreet because of the short teaser.

**`ModuleNotFoundError: No module named 'job'` (or `config`)**
`job.py` and `config.py` must be in the same folder as `main.py` (`python/`).

**`CV file not found`**
`CV` is resolved from the project root. Check the path, or pass `CV=path/to/skills.json`.

**CSV files are owned by root and can't be edited**
The container ran without `--user`. The Makefile includes it. To fix existing files: `sudo chown -R $(id -u):$(id -g) output`.

**`QUERY is required`**
Pass a query: `make run QUERY="your keywords"`.