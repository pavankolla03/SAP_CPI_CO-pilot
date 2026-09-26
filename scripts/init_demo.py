"""Generate private local bootstrap config, without overwriting existing configuration."""
import json
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / '.env'
if path.exists():
    raise SystemExit('.env already exists; preserved. Retrieve the token from your existing file.')
token = secrets.token_urlsafe(32)
claims = {token: {'tenant_id': 'demo', 'actor': 'local-developer', 'role': 'approver'}}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as file:
    file.write("API_KEYS_JSON='" + json.dumps(claims) + "'\nDATA_DIR=data\n")
print('Created .env with a private demo token. Copy the key from API_KEYS_JSON into the side panel.')
