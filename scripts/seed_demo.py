"""Install original teaching fixtures using only the public course REST API."""

import argparse
import getpass

import httpx

if __package__:
    from .seed_data import DEMO_PROBLEMS
else:
    from seed_data import DEMO_PROBLEMS


def seed_problems(client):
    """Create missing fixtures only; a 409 must never trigger update or deletion."""
    created = existing = 0
    for problem in DEMO_PROBLEMS:
        result = client.post("/api/problems/", json=problem)
        if result.status_code not in (200, 409):
            raise SystemExit(f"Import {problem['id']} failed ({result.status_code})")
        if result.status_code == 200:
            created += 1
        else:
            existing += 1
        print(f"{problem['id']}: {'created' if result.status_code == 200 else 'already exists'}")
    print(f"Completed: {created} created, {existing} unchanged, {len(DEMO_PROBLEMS)} total")
    return {"created": created, "existing": existing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument(
        "--course-admin", action="store_true", help="Use the course's public initial admin password"
    )
    args = parser.parse_args()
    password = "admintestpassword" if args.course_admin else getpass.getpass("Password: ")
    with httpx.Client(
        base_url=args.url, timeout=15, follow_redirects=True, trust_env=False
    ) as client:
        login = client.post(
            "/api/auth/login", json={"username": args.username, "password": password}
        )
        if login.status_code != 200:
            raise SystemExit(f"Login failed ({login.status_code})")
        try:
            seed_problems(client)
        finally:
            client.post("/api/auth/logout")


if __name__ == "__main__":
    main()
