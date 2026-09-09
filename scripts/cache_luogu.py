"""Privately cache exactly P1001/P1002; never import them as judge-ready problems.

Run from the project: uv run --locked python scripts/cache_luogu.py
The cache stays under ignored runtime/catalog. Policy changes and previous failures
require human review; this command never refreshes or retries them automatically.
"""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import time
from datetime import datetime, timezone
from urllib.robotparser import RobotFileParser

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "runtime" / "catalog"
USER_AGENT = "CourseOJPrivateCache/1.0 (two-page personal study cache)"
ROBOTS_URL = "https://www.luogu.com.cn/robots.txt"
ULA_URL = "https://help.luogu.com.cn/ula/luogu"
PROBLEMS = {
    "P1001": "https://www.luogu.com.cn/problem/P1001",
    "P1002": "https://www.luogu.com.cn/problem/P1002",
}
# Human-reviewed source policy fingerprints, 2026-09-09. Not redistribution rights.
# Never replace these with newly downloaded values without reviewing the changes.
APPROVED_POLICIES = {
    ROBOTS_URL: "b3afed0f84caa47229e80b15cd0eeed058799e04b9d8e9db2ef4c7baffe55293",
    ULA_URL: "38f19677426bc89634d4e7cb029ffe9e0b087e3cafe2d0c5613ff0750829ca5d",
}
MAX_BYTES = 2_000_000
CHALLENGES = (
    "cf-chl-",
    "challenge-platform",
    "verify you are human",
    "checking your browser",
    "just a moment...",
    "访问过于频繁",
    "人机验证",
    "请输入验证码",
)


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def policy_text(url, body):
    if url == ROBOTS_URL:
        return "\n".join(line.strip() for line in body.splitlines() if line.strip())
    parser = VisibleText()
    parser.feed(body)
    return " ".join(" ".join(parser.parts).split())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StopCollection(Exception):
    def __init__(self, status, reason, http_status=None):
        self.status, self.reason, self.http_status = status, reason, http_status


def collect(cache_dir=CACHE_DIR, *, transport=None, sleep=time.sleep, clock=time.monotonic):
    """One sequential batch; injected transport/clock are only for offline tests."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = cache_dir / "manifest.json"
    if manifest_path.exists():
        # Reuse terminal observations, including failures. No implicit retry on rerun.
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(existing, dict)
            or existing.get("schema_version") != 1
            or not isinstance(existing.get("problems"), dict)
            or set(existing["problems"]) != set(PROBLEMS)
        ):
            raise ValueError("Invalid cache manifest; manual review required")
        for key, record in existing["problems"].items():
            if (
                not isinstance(record, dict)
                or record.get("source_url") != PROBLEMS[key]
                or record.get("license_status") != "unknown"
                or record.get("judging_ready") is not False
                or (
                    existing.get("status") == "cached"
                    and record.get("retrieval_status") != "cached"
                )
            ):
                raise ValueError("Invalid cache record; manual review required")
            if record.get("retrieval_status") == "cached":
                path = cache_dir / f"{key}.html"
                if not path.is_file() or digest(path.read_bytes()) != record.get("sha256"):
                    raise ValueError("Cache integrity failed; manual review required")
        return existing
    manifest = {
        "schema_version": 1,
        "status": "in_progress",
        "started_at": timestamp(),
        "private_use_only": True,
        "license_status": "unknown",
        "judging_ready": False,
        "policies": {},
        "problems": {
            key: {
                "provider": "luogu",
                "source_id": key,
                "source_url": url,
                "retrieved_at": None,
                "retrieval_status": "not_attempted",
                "license_status": "unknown",
                "judging_ready": False,
            }
            for key, url in PROBLEMS.items()
        },
    }

    def save():
        temporary = cache_dir / "manifest.json.tmp"
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(manifest_path)

    last_finished = None
    interval = 10.0
    with httpx.Client(
        transport=transport,
        timeout=20,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        def fetch(url):
            nonlocal last_finished
            if last_finished is not None:
                sleep(max(0, interval - (clock() - last_finished)))
            client.cookies.clear()  # Even server-set anonymous cookies are not forwarded.
            try:
                with client.stream("GET", url) as response:
                    status = response.status_code
                    if status != 200:
                        blocked = status in {401, 403, 429} or 300 <= status < 400
                        raise StopCollection(
                            "blocked" if blocked else "failed", f"http_{status}", status
                        )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise StopCollection("blocked", "response_too_large", status)
                        body.extend(chunk)
                    raw = bytes(body)
                    text = raw.decode("utf-8", errors="replace")
                    if any(marker in text.lower() for marker in CHALLENGES):
                        raise StopCollection("blocked", "challenge_page", status)
                    return raw, text, response.headers.get("content-type", "")
            except httpx.HTTPError as error:
                raise StopCollection("failed", type(error).__name__) from None
            finally:
                last_finished = clock()

        current_record = None
        try:
            for url in (ROBOTS_URL, ULA_URL):
                current_record = {"source_url": url, "retrieved_at": timestamp()}
                manifest["policies"][url] = current_record
                _, text, _ = fetch(url)
                normalized = policy_text(url, text)
                observed = digest(normalized.encode())
                current_record.update(sha256=observed, http_status=200, retrieved_at=timestamp())
                if observed != APPROVED_POLICIES[url]:
                    raise StopCollection("blocked", "policy_changed_review_required", 200)
                current_record["retrieval_status"] = "verified_unchanged"
                if url == ROBOTS_URL:
                    rules = RobotFileParser()
                    rules.parse(text.splitlines())
                    if not all(rules.can_fetch(USER_AGENT, page) for page in PROBLEMS.values()):
                        raise StopCollection("blocked", "robots_disallow", 200)
                    interval = max(interval, rules.crawl_delay(USER_AGENT) or 0)
            for key, url in PROBLEMS.items():
                current_record = manifest["problems"][key]
                current_record["retrieved_at"] = timestamp()
                raw, text, media_type = fetch(url)
                if "text/html" not in media_type.lower() or "<html" not in text.lower():
                    raise StopCollection("blocked", "not_normal_html", 200)
                visible = policy_text(ULA_URL, text)
                if key not in visible or not ("题目描述" in visible or "题目背景" in visible):
                    raise StopCollection("blocked", "problem_page_not_confirmed", 200)
                # Raw HTML only: do not follow media, execute JS, or extract hidden JSON/APIs.
                path = cache_dir / f"{key}.html"
                if path.exists():
                    raise StopCollection("blocked", "untracked_cache_file_review_required")
                path.write_bytes(raw)
                current_record.update(
                    retrieval_status="cached",
                    retrieved_at=timestamp(),
                    http_status=200,
                    cache_file=path.name,
                    sha256=digest(raw),
                    bytes=len(raw),
                )
                save()
            manifest["status"] = "cached"
        except StopCollection as error:
            manifest.update(status=error.status, reason=error.reason)
            if current_record is not None:
                current_record.update(
                    retrieval_status=error.status,
                    reason=error.reason,
                    http_status=error.http_status,
                )
        finally:
            manifest["finished_at"] = timestamp()
            save()
    return manifest


def main():
    try:
        manifest = collect()
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "reason": type(error).__name__}))
        return 1
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if manifest["status"] == "cached" else 1


if __name__ == "__main__":
    raise SystemExit(main())
