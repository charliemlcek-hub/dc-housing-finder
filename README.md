# DC Housing Finder

Automated scraper + dashboard + daily email alerts for 2bd/2ba apartments in DC
(Capitol Hill, Navy Yard, Capitol Riverfront, NoMa, Southwest Waterfront),
targeting <$3200/mo with in-unit laundry.

**Features**
- Scrapes Craigslist, Apartments.com, Zillow, HotPads every 3 hours via GitHub Actions
- Deduplicates listings across sources; SQLite-backed history
- Scores listings on neighborhood tier × price × amenities
- Publishes a filterable public HTML dashboard on GitHub Pages
- Emails a daily digest + **instant "extraordinary fit" alerts** (≤$2800, Capitol Hill, strict 2bd/2ba, in-unit laundry)

## One-time setup

### 1. Install dependencies locally (for testing)

```bash
cd dc-housing-finder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Get a Gmail App Password (2 min)

Since you're sending from charliemlcek@gmail.com:

1. Go to https://myaccount.google.com/apppasswords
2. Requires 2-step verification enabled on your Google account
3. Create an app password called "DC Housing Finder"
4. Copy the 16-char password — save it safely

For **local testing**, export it:
```bash
export GMAIL_APP_PASSWORD="your-16-char-password"
```

### 3. Test a dry run (no email sent)

```bash
python main.py --dry-run
```

This scrapes, filters, writes `docs/index.html`, and prints the email instead of sending.

Open the dashboard:
```bash
open docs/index.html
```

### 4. Send a real email to confirm

```bash
python main.py --no-scrape   # use existing DB, send email
```

### 5. Push to GitHub (so it runs on a schedule for free)

```bash
git init
git add .
git commit -m "Initial commit"

# Create repo via GitHub CLI or UI
gh repo create dc-housing-finder --private --source=. --push
```

### 6. Add the Gmail password as a GitHub secret

```bash
gh secret set GMAIL_APP_PASSWORD -b "your-16-char-password"
```

### 7. Enable GitHub Pages (public dashboard URL)

1. Repo Settings → Pages → Source: "GitHub Actions"
2. After the first successful workflow run, note the URL (e.g. `https://charliemlcek.github.io/dc-housing-finder/`)
3. Set it as a GitHub secret so emails link to it:
   ```bash
   gh secret set DASHBOARD_URL -b "https://charliemlcek.github.io/dc-housing-finder/"
   ```

### 8. You're done

- Every 3 hours: scrape runs, dashboard updates, extraordinary fits trigger instant emails
- Every day at 8am ET: daily digest email with new listings

## How to tune criteria

Edit `config.yaml`:
- `search.max_rent` — total apartment rent cap
- `extraordinary_fit` — what triggers instant alerts
- `neighborhoods` — add/remove target areas or adjust score weights
- `must_have` / `nice_to_have` — amenity requirements

Commit and push; the workflow uses the updated config next run.

## Running locally

```bash
python main.py                # full run: scrape + email
python main.py --dry-run      # no email sent
python main.py --no-scrape    # just re-render HTML from existing DB
python main.py --alerts-only  # check for extraordinary fits only
python main.py --no-email     # scrape + render, no email
```

## Troubleshooting

**Scrapers return 0 listings:**
- Apartments.com and Zillow use Cloudflare. The scraper uses `curl_cffi` (Chrome TLS fingerprint) which usually works.
- If they hard-block from GitHub Actions IPs, Craigslist alone will still work.

**Email not sending:**
- Confirm `GMAIL_APP_PASSWORD` is set (not your real Gmail password — an app password).
- Confirm 2-step verification is enabled on the Google account.

**Dashboard not updating on GitHub Pages:**
- Check the Actions tab for errors.
- First run takes ~2 minutes.

## Data

- `data/listings.db` — SQLite store of all seen listings (committed so state persists across GHA runs)
- `docs/index.html` — the public dashboard (served via Pages)
- `config.yaml` — all your search criteria

## Files of interest

- `main.py` — orchestrator
- `core/filters.py` — hard filters + scoring logic
- `core/neighborhoods.py` — neighborhood bounding polygons
- `scrapers/*.py` — one file per source
- `templates/dashboard.html` — public dashboard layout
- `templates/email.html` — email template
- `.github/workflows/scrape.yml` — 3-hourly + daily schedule
