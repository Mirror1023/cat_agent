#!/usr/bin/env python3
"""
Instagram Login OAuth helper.

No local server required — Instagram redirects to http://localhost and you
paste the full redirect URL back into the terminal.

Usage:
    python get_token.py

The redirect URI used is: http://localhost
Make sure it's added under App Settings > Basic > Site URL (Website platform).
"""

import os
import sys
import webbrowser
import requests
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from dotenv import load_dotenv, set_key

load_dotenv()

APP_ID = os.getenv("INSTAGRAM_APP_ID", "")
APP_SECRET = os.getenv("INSTAGRAM_APP_SECRET", "")
REDIRECT_URI = "http://localhost"
SCOPES = "instagram_business_basic,instagram_business_content_publish,instagram_business_manage_comments"
ENV_FILE = Path(__file__).resolve().parent / ".env"


def extract_code(redirect_url: str) -> str:
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    if "code" in params:
        return params["code"][0]
    if "error_description" in params:
        raise ValueError(params["error_description"][0])
    raise ValueError(f"No code found in URL: {redirect_url}")


def exchange_code_for_short_token(code: str) -> str:
    resp = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"Failed to get short-lived token: {data}")
    return data["access_token"]


def exchange_for_long_lived_token(short_token: str) -> dict:
    resp = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": APP_SECRET,
            "access_token": short_token,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if "access_token" not in data:
        raise ValueError(f"Failed to get long-lived token: {data}")
    return data


def main():
    if not APP_ID or not APP_SECRET:
        print("Error: INSTAGRAM_APP_ID and INSTAGRAM_APP_SECRET must be set in .env")
        sys.exit(1)

    auth_url = (
        f"https://www.instagram.com/oauth/authorize"
        f"?client_id={APP_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPES}"
        f"&response_type=code"
    )

    print("=" * 60)
    print("Instagram Login Token Generator")
    print("=" * 60)
    print()
    print("Opening Instagram authorization in your browser...")
    print()
    webbrowser.open(auth_url)

    print("After you approve access, your browser will redirect to")
    print("http://localhost (which won't load — that's expected).")
    print()
    print("Copy the full URL from your browser's address bar and paste it below.")
    print()

    redirect_url = input("Paste the full redirect URL here: ").strip()

    try:
        code = extract_code(redirect_url)
    except ValueError as e:
        print(f"Error extracting code: {e}")
        sys.exit(1)

    print()
    print("Exchanging auth code for tokens...")

    try:
        short_token = exchange_code_for_short_token(code)
        print("Short-lived token obtained.")

        token_data = exchange_for_long_lived_token(short_token)
        long_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 0)

        print()
        print("=" * 60)
        print("Success! Long-lived token obtained.")
        print(f"Expires in: {int(expires_in) // 86400} days")
        print("=" * 60)

        set_key(str(ENV_FILE), "INSTAGRAM_ACCESS_TOKEN", long_token)
        print()
        print(".env updated with new INSTAGRAM_ACCESS_TOKEN.")
        print("You're good to go — run: python run.py")

    except requests.HTTPError as e:
        print(f"HTTP error: {e}")
        print(f"Response: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
