from __future__ import annotations

import argparse
import json
import re
import time
from collections import deque
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass(slots=True)
class ScrapedPage:
    url: str
    title: str
    headings: list[str]
    links: list[str]
    text: str


@dataclass(slots=True)
class WebsiteAnalysis:
    site_url: str
    site_name: str
    summary: str
    what_it_does: str
    what_it_sells: str
    theme: str
    keywords: list[str]
    page_count: int


@dataclass(slots=True)
class WebsiteReport:
    analysis: WebsiteAnalysis
    pages: list[ScrapedPage]


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.headings: list[str] = []
        self.links: list[str] = []
        self._title_parts: list[str] = []
        self._heading_parts: list[str] = []
        self._text_parts: list[str] = []
        self._current_tag: str | None = None
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return

        if self._skip_depth > 0:
            return

        if tag in {"h1", "h2", "h3", "title"}:
            self._current_tag = tag

        if tag == "a":
            attributes = dict(attrs)
            href = attributes.get("href")
            if href:
                self.links.append(href)

        if tag == "meta":
            attributes = dict(attrs)
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            content = (attributes.get("content") or "").strip()
            if content and name in {"description", "og:description", "twitter:description"}:
                self.meta_description = content

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return

        if self._skip_depth > 0:
            return

        if tag == self._current_tag:
            if tag == "title":
                self.title = self._collapse_text(self._title_parts)
                self._title_parts.clear()
            elif tag in {"h1", "h2", "h3"}:
                heading = self._collapse_text(self._heading_parts)
                if heading:
                    self.headings.append(heading)
                self._heading_parts.clear()
            self._current_tag = None

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return

        text = data.strip()
        if not text:
            return

        self._text_parts.append(text)
        if self._current_tag == "title":
            self._title_parts.append(text)
        elif self._current_tag in {"h1", "h2", "h3"}:
            self._heading_parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._text_parts)

    @staticmethod
    def _collapse_text(parts: list[str]) -> str:
        return " ".join(" ".join(parts).split())


class WebsiteScraper:
    def __init__(
        self,
        start_url: str,
        max_pages: int = 12,
        delay_seconds: float = 0.0,
        same_domain_only: bool = True,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.start_url = self._normalize_url(start_url)
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.same_domain_only = same_domain_only
        self.timeout_seconds = timeout_seconds
        self.allowed_netloc = urlparse(self.start_url).netloc

    def scrape(self) -> list[ScrapedPage]:
        queue: deque[str] = deque([self.start_url])
        visited: set[str] = set()
        results: list[ScrapedPage] = []
        knowledge_signals: set[str] = set()

        while queue and len(results) < self.max_pages:
            url = queue.popleft()
            if not url:
                continue
            if url in visited:
                continue
            visited.add(url)

            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0 Safari/537.36"
                        )
                    },
                )
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    content_type = response.headers.get("content-type", "")
                    html = response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
            except (HTTPError, URLError, TimeoutError, UnicodeError):
                continue

            if "text/html" not in content_type:
                continue

            parser = PageParser()
            parser.feed(html)
            page = self._parse_page(url, parser)
            results.append(page)
            knowledge_signals.update(self._page_signals(page))

            if self._has_enough_knowledge(results, knowledge_signals):
                break

            ranked_links: list[tuple[int, str]] = []
            for link in page.links:
                normalized = self._normalize_url(link, base_url=url)
                if not normalized or normalized in visited:
                    continue
                if self.same_domain_only and urlparse(normalized).netloc != self.allowed_netloc:
                    continue
                ranked_links.append((self._url_priority(normalized), normalized))

            ranked_links.sort(key=lambda item: item[0], reverse=True)
            for _score, ranked_url in ranked_links:
                if ranked_url not in queue:
                    queue.append(ranked_url)

            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)

        return results

    def analyze(self, pages: list[ScrapedPage]) -> WebsiteAnalysis:
        if not pages:
            host = urlparse(self.start_url).netloc
            return WebsiteAnalysis(
                site_url=self.start_url,
                site_name=host or self.start_url,
                summary="No crawlable pages were found.",
                what_it_does="Not enough information.",
                what_it_sells="Not enough information.",
                theme="unknown",
                keywords=[],
                page_count=0,
            )

        host = urlparse(self.start_url).netloc
        site_name = self._derive_site_name(pages[0].title or host)
        keyword_counts = self._keyword_counts(pages)
        keywords = [word for word, _count in keyword_counts[:8]]
        theme = self._infer_theme(keyword_counts, pages)
        what_it_does = self._infer_what_it_does(pages, keywords)
        what_it_sells = self._infer_what_it_sells(pages, keywords)
        summary = self._build_summary(site_name, keywords, theme, pages, what_it_does, what_it_sells)

        return WebsiteAnalysis(
            site_url=self.start_url,
            site_name=site_name,
            summary=summary,
            what_it_does=what_it_does,
            what_it_sells=what_it_sells,
            theme=theme,
            keywords=keywords,
            page_count=len(pages),
        )

    def _parse_page(self, url: str, parser: PageParser) -> ScrapedPage:
        return ScrapedPage(
            url=url,
            title=parser.title,
            headings=parser.headings,
            links=parser.links,
            text=" ".join(parser.get_text().split()),
        )

    @staticmethod
    def _derive_site_name(title_or_host: str) -> str:
        cleaned = re.sub(r"\s+[\-|\|\u2013\u2014].*$", "", title_or_host).strip()
        return cleaned or title_or_host

    @staticmethod
    def _keyword_counts(pages: list[ScrapedPage]) -> list[tuple[str, int]]:
        stopwords = {
            "the", "and", "for", "with", "that", "this", "from", "you", "your", "are",
            "our", "about", "home", "page", "contact", "more", "have", "has", "was",
            "will", "can", "all", "not", "but", "been", "their", "they", "them",
            "one", "two", "new", "use", "used", "using", "we", "us", "into", "over",
            "services", "service", "products", "product", "site", "website", "read",
        }
        words: dict[str, int] = {}
        for page in pages:
            source = " ".join([page.title, *page.headings, page.text])
            for raw_word in re.findall(r"[a-zA-Z][a-zA-Z']+", source.lower()):
                if len(raw_word) < 3 or raw_word in stopwords:
                    continue
                words[raw_word] = words.get(raw_word, 0) + 1
        return sorted(words.items(), key=lambda item: (-item[1], item[0]))

    @staticmethod
    def _infer_theme(keyword_counts: list[tuple[str, int]], pages: list[ScrapedPage]) -> str:
        words = {word for word, _count in keyword_counts[:40]}
        combined_text = " ".join([page.title for page in pages] + [" ".join(page.headings) for page in pages]).lower()

        theme_rules = [
            ("documentation / technical resource", {"docs", "documentation", "api", "developer", "tutorial", "guide", "reference", "learn"}),
            ("e-commerce / shopping", {"shop", "store", "cart", "checkout", "product", "products", "sale", "pricing", "buy"}),
            ("blog / editorial", {"blog", "article", "articles", "news", "post", "posts", "story", "stories", "magazine"}),
            ("portfolio / personal brand", {"portfolio", "projects", "resume", "cv", "about", "hire", "freelance", "designer", "developer"}),
            ("business / services", {"services", "service", "solutions", "consulting", "agency", "company", "enterprise", "clients"}),
            ("community / forum", {"forum", "community", "members", "discussion", "threads", "chat", "discord", "reddit"}),
            ("media / entertainment", {"music", "video", "games", "stream", "gallery", "podcast", "entertainment"}),
            ("education / learning", {"course", "courses", "lesson", "lessons", "students", "education", "school", "academy"}),
        ]

        for label, markers in theme_rules:
            if words.intersection(markers) or any(marker in combined_text for marker in markers):
                return label

        if not keyword_counts:
            return "unknown"

        top_word = keyword_counts[0][0]
        return f"general content centered on {top_word}"

    def _page_signals(self, page: ScrapedPage) -> set[str]:
        source = " ".join([page.url, page.title, " ".join(page.headings), page.text[:3000]]).lower()
        signals: set[str] = set()

        mapping = {
            "about": {"about", "company", "mission", "story", "who we are"},
            "services": {"service", "services", "solutions", "consulting"},
            "products": {"product", "products", "shop", "store", "catalog"},
            "pricing": {"pricing", "plans", "quote", "subscription", "cost"},
            "contact": {"contact", "email", "phone", "support", "get in touch"},
        }

        for signal, words in mapping.items():
            if any(word in source for word in words):
                signals.add(signal)

        return signals

    def _has_enough_knowledge(self, pages: list[ScrapedPage], signals: set[str]) -> bool:
        if len(pages) >= 10:
            return True
        if len(pages) < 2:
            return False

        has_identity = "about" in signals
        has_offer = bool({"services", "products", "pricing"}.intersection(signals))
        has_contact = "contact" in signals
        strong_signal_count = len(signals.intersection({"about", "services", "products", "pricing", "contact"}))

        return (has_identity and has_offer and has_contact) or strong_signal_count >= 4

    @staticmethod
    def _url_priority(url: str) -> int:
        lower = url.lower()
        score = 0
        priority_markers = [
            (12, {"about", "about-us", "company", "mission", "story"}),
            (12, {"services", "solutions", "what-we-do"}),
            (12, {"products", "product", "shop", "store", "catalog"}),
            (10, {"pricing", "plans", "quote"}),
            (10, {"contact", "support", "help", "faq"}),
            (8, {"features", "platform", "use-cases", "industries"}),
            (5, {"blog", "news", "resources", "docs"}),
        ]

        for weight, markers in priority_markers:
            if any(marker in lower for marker in markers):
                score += weight

        parsed = urlparse(lower)
        if parsed.path in {"", "/"}:
            score += 6
        return score

    @staticmethod
    def _infer_what_it_does(pages: list[ScrapedPage], keywords: list[str]) -> str:
        patterns = [
            r"([^.]{0,100}\b(?:we|our company|the company)\b[^.]{0,160}\b(?:provide|offers?|helps?|builds?|creates?|delivers?|speciali[sz]es in)\b[^.]{0,180}\.)",
            r"([^.]{0,100}\b(?:services|solutions|platform)\b[^.]{0,180}\.)",
        ]
        for page in pages:
            text = page.text[:5000]
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    return " ".join(match.group(1).split())

        if keywords:
            return f"The brand appears to provide offerings related to {', '.join(keywords[:3])}."
        return "Could not confidently determine what the brand does from the scraped pages."

    @staticmethod
    def _infer_what_it_sells(pages: list[ScrapedPage], keywords: list[str]) -> str:
        patterns = [
            r"([^.]{0,110}\b(?:buy|shop|plans?|pricing|subscriptions?|products?|services?)\b[^.]{0,180}\.)",
            r"([^.]{0,110}\b(?:starts at|per month|book now|get a quote)\b[^.]{0,180}\.)",
        ]
        for page in pages:
            text = page.text[:5000]
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    return " ".join(match.group(1).split())

        if any(word in {"shop", "store", "product", "pricing", "plans"} for word in keywords):
            return "The site likely sells products or paid plans, but no clear product sentence was extracted."
        return "No direct product or pricing statement was found; the brand may be informational or service-led."

    @staticmethod
    def _build_summary(
        site_name: str,
        keywords: list[str],
        theme: str,
        pages: list[ScrapedPage],
        what_it_does: str,
        what_it_sells: str,
    ) -> str:
        if not keywords:
            return f"{site_name} appears to be a website with limited crawlable text content."

        lead_topics = ", ".join(keywords[:4])
        page_hint = "page" if len(pages) == 1 else "pages"
        return (
            f"{site_name} appears to focus on {lead_topics}. "
            f"The focused crawl sampled {len(pages)} {page_hint}, and the content theme looks like {theme}. "
            f"What it does: {what_it_does} What it sells: {what_it_sells}"
        )

    @staticmethod
    def _normalize_url(url: str, base_url: str | None = None) -> str:
        if base_url is not None:
            url = urljoin(base_url, url)
        url = url.strip()
        if not url:
            return ""

        if "://" not in url:
            url = f"https://{url}"

        url, _fragment = urldefrag(url)
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ""
        return parsed._replace(fragment="").geturl()


def write_json(output_path: Path, report: WebsiteReport) -> None:
    payload = asdict(report)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl a website and export page data to JSON.")
    parser.add_argument("url", help="The starting URL to scrape")
    parser.add_argument("--max-pages", type=int, default=12, help="Maximum number of pages to crawl")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay in seconds between requests")
    parser.add_argument(
        "--no-same-domain",
        action="store_true",
        help="Allow following links to other domains",
    )
    parser.add_argument(
        "--output",
        default="scraped_pages.json",
        help="Path to the JSON output file",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    scraper = WebsiteScraper(
        start_url=args.url,
        max_pages=args.max_pages,
        delay_seconds=args.delay,
        same_domain_only=not args.no_same_domain,
    )
    pages = scraper.scrape()
    analysis = scraper.analyze(pages)
    report = WebsiteReport(analysis=analysis, pages=pages)
    output_path = Path(args.output)
    write_json(output_path, report)
    print(analysis.summary)
    print(f"Saved {len(pages)} pages to {output_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())