# Website Scraper

A focused Python scraper that gathers enough information to understand a brand or service without crawling an entire site.

It prioritizes useful pages (home, about, services, products, pricing, contact) and stops early when it has enough context.

## Usage

```bash
c:/Users/daksh/Documents/Scraper/.venv/Scripts/python.exe scraper.py https://example.com --output pages.json
```

Options:

- `--max-pages`: hard cap for crawled pages (default: 12)
- `--delay`: pause between requests in seconds
- `--no-same-domain`: follow links to other domains too
- `--output`: JSON destination path

This version uses only the Python standard library.

## Output

The JSON contains:

- `analysis.summary`: plain-English site overview
- `analysis.what_it_does`: what the brand/service appears to do
- `analysis.what_it_sells`: what it appears to sell (products/plans/services)
- `analysis.theme`: likely site content category
- `analysis.keywords`: top extracted keywords
- `pages`: sampled pages used to produce the analysis
