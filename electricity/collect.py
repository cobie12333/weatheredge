#!/usr/bin/env python3
"""Discover and cautiously download public Eskom data-portal files.

Uses only Python's standard library. Does not bypass authentication or scrape
third-party market dashboards. Review the source site's terms before automation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SOURCES = {
    "demand-capacity": "https://www.eskom.co.za/dataportal/demand-side/system-hourly-demand-and-available-capacity/",
    "demand-forecast": "https://www.eskom.co.za/dataportal/demand-side/system-hourly-actual-and-forecasted-demand/",
    "renewables-hourly": "https://www.eskom.co.za/dataportal/renewables-performance/hourly-renewable-generation/",
    "renewables-total": "https://www.eskom.co.za/dataportal/renewables-performance/total-hourly-renewable-generation/",
}
USER_AGENT = "WeatherEdge-electricity-research/0.1 (public-data discovery; respectful rate)"
MAX_BYTES = 25 * 1024 * 1024
PAUSE_SECONDS = 1.5
KEYWORDS = ("csv", "download", "export", "excel", "xlsx", "xls", "data file")


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(" ".join(self._text).split())))
            self._href = None
            self._text = []


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch(url: str, limit: int = MAX_BYTES) -> tuple[bytes, str, str]:
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    with urlopen(req, timeout=25) as response:
        final_url = response.geturl()
        if not allowed_host(final_url):
            raise ValueError(f"redirected outside eskom.co.za: {final_url}")
        length = response.headers.get("Content-Length")
        if length and int(length) > limit:
            raise ValueError(f"response too large ({length} bytes)")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError(f"response exceeds {limit} byte safety limit")
        return data, response.headers.get("Content-Type", ""), final_url


def allowed_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "eskom.co.za" or host.endswith(".eskom.co.za")


def candidate_url(base: str, href: str, label: str) -> str | None:
    url = urljoin(base, href.strip())
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not allowed_host(url):
        return None
    haystack = (parsed.path + " " + parsed.query + " " + label).lower()
    ext = Path(parsed.path.lower()).suffix
    if ext in (".csv", ".xlsx", ".xls", ".zip") or any(k in haystack for k in KEYWORDS):
        return url
    return None


def discover(out: Path) -> list[dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for name, page in SOURCES.items():
        print(f"PAGE {name}: {page}")
        try:
            raw, content_type, final_url = fetch(page, limit=5 * 1024 * 1024)
            if "html" not in content_type.lower() and b"<html" not in raw[:1000].lower():
                print(f"  SKIP: expected HTML, received {content_type}")
                continue
            parser = LinkParser()
            parser.feed(raw.decode("utf-8", errors="replace"))
            count = 0
            for href, label in parser.links:
                target = candidate_url(final_url, href, label)
                if target:
                    found.setdefault(target, {"url": target, "page": final_url, "label": label, "source": name})
                    count += 1
            print(f"  candidate links: {count}")
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")
        time.sleep(PAUSE_SECONDS)
    links = list(found.values())
    out.mkdir(parents=True, exist_ok=True)
    (out / "discovered_links.json").write_text(json.dumps(links, indent=2), encoding="utf-8")
    print(f"Saved {len(links)} unique candidates to {out / 'discovered_links.json'}")
    return links


def append_manifest(out: Path, record: dict[str, object]) -> None:
    with (out / "manifest.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def safe_filename(url: str, content_type: str) -> str:
    name = Path(urlparse(url).path).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not name or name.lower() in ("download", "export", "file"):
        name = hashlib.sha256(url.encode()).hexdigest()[:16]
    if not Path(name).suffix:
        ext = ".csv" if "csv" in content_type.lower() else ".bin"
        name += ext
    return name[:140]


def download_all(out: Path) -> None:
    links_path = out / "discovered_links.json"
    if not links_path.exists():
        discover(out)
    links = json.loads(links_path.read_text(encoding="utf-8"))
    for item in links:
        url = item["url"]
        record: dict[str, object] = {
            "retrieved_at_utc": now_utc(), "source_url": url,
            "discovery_page": item.get("page"), "label": item.get("label"),
        }
        try:
            print(f"GET {url}")
            data, content_type, final_url = fetch(url)
            # Reject HTML login/error pages even if the URL looked like a CSV.
            if "html" in content_type.lower() or data[:200].lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise ValueError(f"received HTML instead of a data file ({content_type})")
            name = safe_filename(final_url, content_type)
            dest = out / name
            if dest.exists():
                digest = hashlib.sha256(data).hexdigest()[:10]
                dest = out / f"{dest.stem}_{digest}{dest.suffix}"
            dest.write_bytes(data)
            record.update({
                "status": "saved", "final_url": final_url, "file": str(dest),
                "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "content_type": content_type,
            })
            print(f"  SAVED {dest} ({len(data)} bytes)")
        except Exception as exc:
            record.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
            print(f"  ERROR {record['error']}")
        append_manifest(out, record)
        time.sleep(PAUSE_SECONDS)


def inspect_csv(out: Path, limit: int = 5) -> None:
    import csv

    files = sorted(out.glob("*.csv"))
    if not files:
        print(f"No .csv files in {out}. Run 'download' and inspect discovered_links.json first.")
        return
    for path in files:
        print(f"\nFILE {path} ({path.stat().st_size} bytes)")
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                sample = handle.read(8192)
                handle.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t|")
                except csv.Error:
                    dialect = csv.excel
                reader = csv.reader(handle, dialect)
                for index, row in enumerate(reader):
                    print("  " + json.dumps(row[:12], ensure_ascii=False))
                    if index >= limit:
                        break
        except (OSError, UnicodeError, csv.Error) as exc:
            print(f"  INSPECT ERROR: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("discover", "download", "inspect"))
    parser.add_argument("--out", default="data/electricity_raw", help="raw data output directory")
    parser.add_argument("--preview-rows", type=int, default=5, help="rows to preview for inspect")
    args = parser.parse_args()
    out = Path(args.out)
    if args.command == "discover":
        discover(out)
    elif args.command == "download":
        download_all(out)
    else:
        inspect_csv(out, max(0, args.preview_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
