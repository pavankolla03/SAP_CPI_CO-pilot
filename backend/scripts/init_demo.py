"""Initialise backend/.env for local development.

Usage:
    python scripts/init_demo.py

Writes a .env file with a dev token so `pydantic-settings` can validate
`API_KEYS_JSON` on startup. Use this only on trusted local machines.

The written token is for local use only. Do not commit .env.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

TOKEN = "dev-token-00000000000000000000000000"
PRINCIPAL = {
    "tenant_id": "demo",
    "actor": "local-dev",
    "role": "approver",
}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    env_path = backend / ".env"
    if env_path.exists():
        ans = input(f"{env_path} already exists. Overwrite? [y/N]: ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    # Merge with existing .env if present, preserving unknown keys.
    env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

    env.update({
        "DATA_DIR": "data",
        "TENANTS_FILE": ".tenants.json",
        "API_KEYS_JSON": json.dumps({TOKEN: PRINCIPAL}),
        "EXTENSION_ORIGIN": "chrome-extension://*",
        "LLM_ENABLED": "false",
        "POLL_ATTEMPTS": "6",
        "POLL_SECONDS": "2",
        "CHANNEL_WORKER_ENABLED": "false",
    })

    env_path.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    print(f"Wrote {env_path}.")
    print(f"Access token: {TOKEN}")
    print("Use it in the extension Settings panel or Authorization header.")


if __name__ == "__main__":
    main()
