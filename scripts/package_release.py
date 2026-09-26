"""Build source-only release archives; exclude local credentials, databases and speech models."""
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from dotenv import dotenv_values


def main():
    root = Path(__file__).resolve().parents[1]
    files = [root / name for name in (
        'README.md', 'pyproject.toml', 'uv.lock', 'Dockerfile', 'compose.yaml',
        'tenants.example.json', '.env.example', '.gitignore', '.dockerignore')]
    for folder in ('backend', 'extension', 'docs', 'samples', 'scripts', 'modules'):
        files.extend(p for p in (root / folder).rglob('*') if p.is_file()
                     and p.suffix != '.pyc'
                     and not any(x.startswith('.') or x == '__pycache__' for x in p.relative_to(root).parts))
    values = dotenv_values(root / '.env')
    secrets = [v for k, v in values.items() if v and len(v) > 12
               and any(word in k for word in ('SECRET', 'KEY', 'TOKEN'))]
    secrets.extend(json.loads(values.get('API_KEYS_JSON', '{}')).keys())
    for path in files:
        if any(secret.encode() in path.read_bytes() for secret in secrets):
            raise ValueError('Configured credential found in release file: ' + str(path.relative_to(root)))
    with ZipFile(root.parent / 'sap-agent-mvp.zip', 'w', ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, 'sap-agent/' + str(path.relative_to(root)))
    with ZipFile(root.parent / 'relay-chrome-extension.zip', 'w', ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_relative_to(root / 'extension'):
                archive.write(path, str(path.relative_to(root / 'extension')))
    print('Updated both release archives; configured credential scan passed.')


if __name__ == '__main__':
    main()
