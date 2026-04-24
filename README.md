# Website Scraper

A focused Python scraper that gathers enough information to understand a brand or service without crawling an entire site. Now with a web interface!

It prioritizes useful pages (home, about, services, products, pricing, contact) and stops early when it has enough context.

## Quick Start (Web Interface)

### 1. Install Dependencies

```bash
pip install flask
```

### 2. Start the Web Server

```bash
python3 app.py
```

The server runs on `http://localhost:5000`. Open this in your browser to access the WICK interface.

### 3. Enter a URL and Analyze

- Type any domain into the search box (e.g., `github.com`)
- Click "Analyze →" to start scanning
- The scraper analyzes the site and returns results

## Command Line Usage

For direct scraper access without the web interface:

```bash
python3 scraper.py https://example.com --output pages.json
```

### Options

- `--max-pages`: hard cap for crawled pages (default: 12)
- `--delay`: pause between requests in seconds
- `--backend`: `urllib` (default) or `playwright`
- `--playwright-stealth`: enable stealth evasions (only with `--backend playwright`)
- `--no-same-domain`: follow links to other domains too
- `--output`: JSON destination path

### For JavaScript-Heavy Sites

For sites that need JavaScript rendering:

```bash
pip install playwright playwright-stealth
playwright install chromium
python3 scraper.py https://example.com --backend playwright --playwright-stealth --output pages.json
```

## Architecture

- **index.html**: WICK web interface with real-time scanning
- **scraper.py**: Core Python scraper with multiple backend options
- **app.py**: Flask API server connecting the frontend to the scraper

## Output

The JSON contains:

- `analysis.summary`: plain-English site overview
- `analysis.what_it_does`: what the brand/service appears to do
- `analysis.what_it_sells`: what it appears to sell (products/plans/services)
- `analysis.theme`: likely site content category
- `analysis.keywords`: top extracted keywords
- `pages`: sampled pages used to produce the analysis
