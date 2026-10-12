#!/usr/bin/env python3
"""
Crawl a running copy of the site and fail on any broken page.

Walks the public pages from the home page, logs in to the admin and opens
every model list plus sample add, change and history pages, and fetches each
static asset the pages reference. It only sends GET requests (plus the admin
login POST) and skips links known to change data on GET.

Standard library only, so it runs before or without the project's packages.

Usage:
    python scripts/smoke_crawl.py --base-url http://127.0.0.1:8000 \\
        [--admin-user USER --admin-password PASS] [--behind-proxy] \\
        [--snapshot-dir DIR]

``--behind-proxy`` sends ``X-Forwarded-Proto: https`` so a server running the
production settings (``SECURE_SSL_REDIRECT``) treats requests as HTTPS, the
way it does behind Render's proxy. Admin credentials can also come from the
SMOKE_ADMIN_USER and SMOKE_ADMIN_PASSWORD environment variables.

Exit status is 1 when any page fails, so CI can gate on it.
"""

import argparse
import hashlib
import http.client
import os
import re
import sys
import time
from collections import Counter, defaultdict, deque
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

# Links that change data on GET or end the session; never follow them.
SKIP_PATH_PATTERNS = [
    r"/logout",
    r"/(approve|reject)/$",
    r"/quick-cancel",
    r"/delete/$",
    r"/draft/\d+/(draw|advance|end|undo|pick|finalize|swap|reset|"
    r"captain-rounds|add-signup|dev-autofill)/",
    r"/update/\d+/$",
    r"^/__debug__/",
    r"^/media/",
]
# Links that may legitimately answer with something other than 200.
EXPECTED_STATUSES = [
    # The live draft board keeps hidden download buttons in the page and
    # reveals them when the draft completes; until then the download is 404.
    (r"^/draft/\d+/download/", {200, 404}),
]
# Many URLs differ only by an id (every player, every matchup). Visit a few
# of each shape rather than thousands of near-identical pages.
DEFAULT_PER_PATTERN = 3
ERROR_MARKERS = ("Traceback (most recent call last)", "Server Error (500)")
CSRF_RE = re.compile(
    r'((?:csrfmiddlewaretoken" value=|name="csrf-token" content=)")[^"]+'
    r'|(csrftoken["\']?\s*[:=]\s*["\'])[^"\']+'
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self.assets = [], []
        self.has_search = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        elif tag == "script" and attrs.get("src"):
            self.assets.append(attrs["src"])
        elif (
            tag == "link"
            and attrs.get("href")
            and "stylesheet" in (attrs.get("rel") or "")
        ):
            self.assets.append(attrs["href"])
        elif tag == "img" and attrs.get("src"):
            self.assets.append(attrs["src"])
        elif tag == "input" and attrs.get("name") == "q":
            self.has_search = True


class Crawler:
    def __init__(self, base_url, behind_proxy, per_pattern, max_pages, timeout):
        parts = urlsplit(base_url)
        self.scheme, self.host = parts.scheme, parts.netloc
        self.behind_proxy = behind_proxy
        self.per_pattern = per_pattern
        self.max_pages = max_pages
        self.timeout = timeout
        self.cookies = {}
        self.results = []  # (path, status, seconds, note)
        self.failures = []
        self.seen = set()
        self.pattern_counts = Counter()
        self.bodies = {}

    # -- HTTP -------------------------------------------------------------

    def request(self, method, path, body=None, extra_headers=None):
        conn_cls = (
            http.client.HTTPSConnection
            if self.scheme == "https"
            else http.client.HTTPConnection
        )
        conn = conn_cls(self.host, timeout=self.timeout)
        headers = {"User-Agent": "dcsh-smoke-crawl/1.0", "Accept": "text/html,*/*"}
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        if self.behind_proxy:
            headers["X-Forwarded-Proto"] = "https"
        headers.update(extra_headers or {})
        start = time.monotonic()
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        elapsed = time.monotonic() - start
        for header, value in resp.getheaders():
            if header.lower() == "set-cookie":
                name, _, rest = value.partition("=")
                self.cookies[name.strip()] = rest.split(";", 1)[0]
        conn.close()
        return resp.status, dict(resp.getheaders()), data, elapsed

    def get(self, path, max_redirects=5):
        """GET a path, following same-site redirects. Returns the final
        (path, status, headers, body, seconds)."""
        total = 0.0
        for _ in range(max_redirects + 1):
            status, headers, body, elapsed = self.request("GET", path)
            total += elapsed
            location = headers.get("Location") or headers.get("location")
            if status in (301, 302, 303, 307, 308) and location:
                target = urlsplit(urljoin(f"https://{self.host}{path}", location))
                if target.netloc and target.netloc != self.host:
                    return path, status, headers, body, total
                path = target.path + (f"?{target.query}" if target.query else "")
                continue
            return path, status, headers, body, total
        return path, status, headers, body, total

    # -- Bookkeeping ------------------------------------------------------

    def normalize(self, href, current):
        if not href or href.startswith(
            ("#", "mailto:", "tel:", "javascript:", "data:")
        ):
            return None
        absolute = urljoin(f"{self.scheme}://{self.host}{current}", href)
        parts = urlsplit(absolute)
        if parts.netloc != self.host:
            return None
        return parts.path + (f"?{parts.query}" if parts.query else "")

    def skipped(self, path):
        return any(re.search(p, path) for p in SKIP_PATH_PATTERNS)

    def pattern_of(self, path):
        base, _, query = path.partition("?")
        base = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<uuid>", base)
        base = re.sub(r"\d{4}-\d{2}-\d{2}", "<date>", base)
        base = re.sub(r"/\d+", "/<n>", base)
        keys = sorted(k.split("=")[0] for k in query.split("&") if k)
        return base + ("?" + "&".join(keys) if keys else "")

    def check(self, path, note="", expect=(200,)):
        """Fetch one page, record the outcome, return the parsed body."""
        if path in self.seen or len(self.seen) >= self.max_pages:
            return None
        for pattern, statuses in EXPECTED_STATUSES:
            if re.search(pattern, path):
                expect = tuple(statuses)
        self.seen.add(path)
        try:
            final, status, headers, body, secs = self.get(path)
        except (OSError, http.client.HTTPException) as exc:
            self.fail(path, f"request failed: {exc}")
            return None
        text = body.decode("utf-8", "replace")
        self.results.append((path, status, secs, note))
        if status >= 500 or status not in expect:
            self.fail(path, f"HTTP {status}{' -> ' + final if final != path else ''}")
            return None
        if status != 200:
            return None
        if any(marker in text for marker in ERROR_MARKERS):
            self.fail(path, "error page content in a successful response")
            return None
        ctype = headers.get("Content-Type", headers.get("content-type", ""))
        if "html" not in ctype:
            return None
        self.bodies[path] = text
        parser = LinkParser()
        parser.feed(text)
        return parser

    def fail(self, path, why):
        self.failures.append((path, why))

    # -- Crawls -----------------------------------------------------------

    def crawl_public(self, seeds):
        queue = deque(seeds)
        assets = set()
        while queue and len(self.seen) < self.max_pages:
            path = queue.popleft()
            if path in self.seen or self.skipped(path) or path.startswith("/admin"):
                continue
            pattern = self.pattern_of(path)
            if self.pattern_counts[pattern] >= self.per_pattern:
                continue
            self.pattern_counts[pattern] += 1
            parser = self.check(path, "public")
            if parser is None:
                continue
            for href in parser.links:
                link = self.normalize(href, path)
                if link and not link.startswith("/static/"):
                    queue.append(link)
            for src in parser.assets:
                asset = self.normalize(src, path)
                if asset and asset.startswith("/static/"):
                    assets.add(asset)
        return assets

    def check_assets(self, assets):
        for asset in sorted(assets):
            if asset in self.seen:
                continue
            self.seen.add(asset)
            try:
                _, status, _, _, secs = self.get(asset)
            except (OSError, http.client.HTTPException) as exc:
                self.fail(asset, f"request failed: {exc}")
                continue
            self.results.append((asset, status, secs, "static"))
            if status != 200:
                self.fail(asset, f"static asset HTTP {status}")

    def login(self, user, password):
        _, status, _, body, _ = self.get("/admin/login/")
        match = re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"', body)
        if status != 200 or not match:
            self.fail("/admin/login/", f"login page unavailable (HTTP {status})")
            return False
        origin = f"{'https' if self.behind_proxy else self.scheme}://{self.host}"
        form = urlencode(
            {
                "csrfmiddlewaretoken": match.group(1).decode(),
                "username": user,
                "password": password,
                "next": "/admin/",
            }
        )
        status, headers, _, _ = self.request(
            "POST",
            "/admin/login/",
            body=form,
            extra_headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": origin,
                "Referer": f"{origin}/admin/login/",
            },
        )
        location = headers.get("Location") or headers.get("location") or ""
        if status != 302 or "login" in location:
            self.fail("/admin/login/", f"admin login failed (HTTP {status})")
            return False
        return True

    def crawl_admin(self):
        index = self.check("/admin/", "admin")
        if index is None:
            self.fail("/admin/", "admin index did not render")
            return
        list_re = re.compile(r"^/admin/[a-z_]+/[a-z_]+/(draft-setup/)?$")
        changelists = []
        for href in index.links:
            link = self.normalize(href, "/admin/")
            if link and list_re.match(link) and link not in changelists:
                changelists.append(link)
        if not changelists:
            self.fail("/admin/", "no model lists found on the admin index")
        for changelist in changelists:
            parser = self.check(changelist, "admin list")
            if parser is None:
                continue
            if parser.has_search:
                self.check(changelist + "?q=a", "admin search")
            if not changelist.endswith("draft-setup/"):
                self.check(changelist + "add/", "admin add", expect=(200, 403))
            change_re = re.compile(re.escape(changelist) + r"(\d+)/change/$")
            changes = []
            for href in parser.links:
                link = self.normalize(href, changelist)
                if link and change_re.match(link.split("?")[0]):
                    base = link.split("?")[0]
                    if base not in changes:
                        changes.append(base)
            for change in changes[:2]:
                self.check(change, "admin change", expect=(200, 403))
            if changes:
                self.check(changes[0].replace("/change/", "/history/"), "admin history")

    # -- Output -----------------------------------------------------------

    def write_snapshots(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        index = []
        for path, body in sorted(self.bodies.items()):
            name = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "home"
            name = f"{name[:80]}_{hashlib.sha1(path.encode()).hexdigest()[:8]}.html"
            body = CSRF_RE.sub(lambda m: (m.group(1) or m.group(2)) + "CSRF", body)
            (directory / name).write_text(body)
            index.append(f"{name}\t{path}")
        (directory / "INDEX.tsv").write_text("\n".join(index) + "\n")

    def report(self):
        by_kind = defaultdict(Counter)
        for _, status, _, note in self.results:
            by_kind[note or "other"][status] += 1
        print(f"\nChecked {len(self.results)} URLs")
        for kind, counts in sorted(by_kind.items()):
            summary = ", ".join(f"{s}: {n}" for s, n in sorted(counts.items()))
            print(f"  {kind:<14} {summary}")
        slowest = sorted(self.results, key=lambda r: r[2], reverse=True)[:5]
        print("Slowest:")
        for path, status, secs, _ in slowest:
            print(f"  {secs:6.2f}s  {status}  {path}")
        if self.failures:
            print(f"\nFAILED: {len(self.failures)} problem(s)")
            for path, why in self.failures:
                print(f"  {path}  ->  {why}")
        else:
            print("\nAll pages OK")


PUBLIC_SEEDS = [
    "/",
    "/schedule/",
    "/scores/",
    "/team_standings/",
    "/player_stats/",
    "/hof/",
    "/cups/",
    "/player_trends/",
    "/roster/",
    "/goalie-status/",
    "/captain-urls/",
    "/draft/",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--admin-user", default=os.environ.get("SMOKE_ADMIN_USER"))
    parser.add_argument(
        "--admin-password", default=os.environ.get("SMOKE_ADMIN_PASSWORD")
    )
    parser.add_argument("--behind-proxy", action="store_true")
    parser.add_argument("--per-pattern", type=int, default=DEFAULT_PER_PATTERN)
    parser.add_argument("--max-pages", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--snapshot-dir")
    parser.add_argument(
        "--skip-admin", action="store_true", help="only crawl public pages"
    )
    args = parser.parse_args()

    crawler = Crawler(
        args.base_url,
        args.behind_proxy,
        args.per_pattern,
        args.max_pages,
        args.timeout,
    )
    assets = crawler.crawl_public(PUBLIC_SEEDS)
    crawler.check_assets(assets)
    if not args.skip_admin:
        if not (args.admin_user and args.admin_password):
            crawler.fail("/admin/", "no admin credentials given (use --skip-admin)")
        elif crawler.login(args.admin_user, args.admin_password):
            crawler.crawl_admin()
    if args.snapshot_dir:
        crawler.write_snapshots(args.snapshot_dir)
    crawler.report()
    return 1 if crawler.failures else 0


if __name__ == "__main__":
    sys.exit(main())
