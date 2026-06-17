#!/usr/bin/env python3
"""Interactive CLI to create / update config/credentials.enc.

Usage:
    python src/scrapers/encrypt_creds.py

Reads MASTER_CRYPTO_KEY from environment, prompts for each platform's
credentials, merges with any existing store, and re-encrypts to
config/credentials.enc.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Allow running as a standalone script from the repo root
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from cryptography.fernet import Fernet

ENC_PATH = ROOT / "config" / "credentials.enc"

PLATFORMS = [
    "linkedin",
    "naukri",
    "indeed",
    "instahyre",
    "wellfound",
    "weworkremotely",
    "hirist",
    "cutshort",
]

# LinkedIn uses Google SSO; all others use username + password.
GOOGLE_SSO_PLATFORMS = {"linkedin"}


def _get_key() -> bytes:
    raw = os.environ.get("MASTER_CRYPTO_KEY", "").strip()
    if not raw:
        print("ERROR: MASTER_CRYPTO_KEY environment variable is not set.", file=sys.stderr)
        print("Generate one with:  python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
        sys.exit(1)
    return raw.encode() if isinstance(raw, str) else raw


def _load_existing(fernet: Fernet) -> dict:
    if not ENC_PATH.exists():
        return {}
    try:
        plaintext = fernet.decrypt(ENC_PATH.read_bytes())
        return json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        print(f"WARNING: Could not decrypt existing credentials ({exc}). Starting fresh.")
        return {}


def _prompt_platform(platform: str, existing: dict) -> dict | None:
    """Prompt the user for credentials for *platform*.

    Returns None if the user skips (presses Enter on all fields with existing data).
    """
    print(f"\n{'─' * 50}")
    print(f"  Platform: {platform.upper()}")
    if platform in existing:
        print("  (existing credentials found — press Enter to keep)")
    print(f"{'─' * 50}")

    if platform in GOOGLE_SSO_PLATFORMS:
        default_email = (existing.get(platform) or {}).get("google_email", "yashdeshmukh7@gmail.com")
        google_email = input(f"  Google SSO email [{default_email}]: ").strip()
        if not google_email:
            google_email = default_email
        if platform in existing and existing[platform].get("google_email") == google_email:
            print("  → No change.")
            return existing[platform]
        return {"method": "google_sso", "google_email": google_email}

    # Password-based platforms
    default_user = (existing.get(platform) or {}).get("username", "yashdeshmukh7@gmail.com")
    username = input(f"  Username / email [{default_user}]: ").strip()
    if not username:
        username = default_user

    print(f"  Password (leave blank to keep existing): ", end="", flush=True)
    # Use getpass if available for non-echoing input
    try:
        import getpass
        password = getpass.getpass(prompt="")
    except Exception:
        password = input("").strip()

    if not password:
        if platform in existing:
            existing_password = existing[platform].get("password", "")
            if existing_password:
                print("  → Keeping existing password.")
                if existing[platform].get("username") == username:
                    return existing[platform]
                return {**existing[platform], "username": username}

    if not password:
        print(f"  WARNING: No password provided for {platform}. Skipping.")
        return existing.get(platform)

    return {"method": "password", "username": username, "password": password}


def main() -> None:
    print("=" * 50)
    print("  Job Hunter — Credential Setup")
    print("=" * 50)
    print("\nThis tool encrypts platform credentials into config/credentials.enc.")
    print("The file is never committed (it is in .gitignore).\n")

    fernet = Fernet(_get_key())
    store = _load_existing(fernet)

    print(f"Loaded {len(store)} existing platform(s): {', '.join(store.keys()) or 'none'}")
    print("\nYou will be prompted for each platform's credentials.")
    print("Press Enter to keep existing values.\n")

    for platform in PLATFORMS:
        creds = _prompt_platform(platform, store)
        if creds is not None:
            store[platform] = creds

    # Ensure config/ directory exists
    ENC_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Encrypt and write
    plaintext = json.dumps(store, indent=2).encode("utf-8")
    encrypted = fernet.encrypt(plaintext)
    ENC_PATH.write_bytes(encrypted)

    print(f"\n✓ Credentials saved to {ENC_PATH}")
    print(f"  Platforms stored: {', '.join(store.keys())}")


if __name__ == "__main__":
    main()
