"""Backfill English prose for unchanged DEMO seed problems via the public API.

The script never updates canonical Chinese prose or judge data.  A seed whose
current Chinese prose differs from the bundled source is skipped so that an
old English statement cannot be attached to a newer problem version.
"""

from __future__ import annotations

import argparse
import getpass

import httpx

from oj.translations import TRANSLATABLE_FIELDS

if __package__:
    from .seed_data import DEMO_PROBLEMS
else:
    from seed_data import DEMO_PROBLEMS


def _data(response):
    if response.status_code != 200:
        return None
    value = response.json()
    return value.get("data") if isinstance(value, dict) else None


def seed_problem_translations(client):
    """Install translations only when the current seed prose is unchanged."""

    installed = skipped = 0
    for seed in DEMO_PROBLEMS:
        current = _data(client.get(f"/api/problems/{seed['id']}", params={"locale": "zh-CN"}))
        if not isinstance(current, dict):
            raise RuntimeError(f"Problem {seed['id']} is unavailable")
        if any(current.get(field) != seed.get(field) for field in TRANSLATABLE_FIELDS):
            skipped += 1
            continue
        response = client.put(
            f"/api/problems/{seed['id']}/translations/en",
            json=seed["translations"]["en"],
        )
        if response.status_code != 200:
            raise RuntimeError(f"Translation for {seed['id']} failed ({response.status_code})")
        installed += 1
    return {"installed": installed, "skipped": skipped, "total": len(DEMO_PROBLEMS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument(
        "--course-admin",
        action="store_true",
        help="Use the course's public initial admin password",
    )
    args = parser.parse_args()
    password = "admintestpassword" if args.course_admin else getpass.getpass("Password: ")
    with httpx.Client(
        base_url=args.url,
        timeout=15,
        follow_redirects=True,
        trust_env=False,
    ) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": args.username, "password": password},
        )
        if login.status_code != 200:
            raise SystemExit(f"Login failed ({login.status_code})")
        try:
            result = seed_problem_translations(client)
        finally:
            client.post("/api/auth/logout")
    print(
        "Translations: "
        f"{result['installed']} installed, {result['skipped']} skipped, "
        f"{result['total']} total"
    )


if __name__ == "__main__":
    main()
