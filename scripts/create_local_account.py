"""Create a personal demo account; generated credentials stay in ignored local config."""

import argparse
import secrets
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    destination = Path(".env.local")
    if destination.exists():
        raise SystemExit(".env.local already exists; leave existing credentials unchanged.")
    username, password = args.username, secrets.token_urlsafe(15)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=15, trust_env=False) as client:
        response = client.post("/api/users/", json={"username": username, "password": password})
        if response.status_code != 200:
            raise SystemExit(f"Account creation returned {response.status_code}; no file written.")
        # Exclusive creation prevents accidental overwrites. Never print the password.
        with destination.open("x", encoding="utf-8") as handle:
            handle.write(f"OJ_LOCAL_USERNAME={username}\nOJ_LOCAL_PASSWORD={password}\n")
        login = client.post("/api/auth/login", json={"username": username, "password": password})
        if login.status_code != 200:
            raise SystemExit("Account created but login verification failed.")
        client.post("/api/auth/logout")
    print("Created and verified local account; password saved only in ignored .env.local.")


if __name__ == "__main__":
    main()
