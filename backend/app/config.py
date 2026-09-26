import json
import os
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceConnection(BaseModel):
    api_url: str
    token_url: str = ''
    client_id_env: str = ''
    client_secret_env: str = ''
    api_token_env: str = ''

    @model_validator(mode='after')
    def check(self):
        for value in [self.api_url] + ([self.token_url] if self.token_url else []):
            parsed = urlparse(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                raise ValueError('Service URLs must be administrator-configured HTTPS URLs')
        if not self.api_token_env and not (self.token_url and self.client_id_env and self.client_secret_env):
            raise ValueError('Service requires bearer token reference or OAuth credentials')
        return self


class Tenant(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str
    mode: str = 'demo'
    environment: str = 'DEV'
    api_url: str = ''
    token_url: str = ''
    client_id_env: str = ''
    client_secret_env: str = ''
    allow_upload: bool = False
    description_package_id: str = ''
    apim: ServiceConnection | None = None
    aem: ServiceConnection | None = None

    @model_validator(mode='after')
    def validate_connection(self):
        if self.environment != 'DEV' or self.mode not in ('demo', 'sap'):
            raise ValueError('Only DEV tenants and demo/sap modes are supported')
        if self.mode == 'sap':
            for url in (self.api_url, self.token_url):
                parsed = urlparse(url)
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
                    raise ValueError('SAP endpoints must be administrator-configured HTTPS URLs')
            if not self.api_url.endswith('/api/v1'):
                raise ValueError('api_url must end in /api/v1')
            if not self.client_id_env or not self.client_secret_env:
                raise ValueError('Credential environment variable names required')
        return self


class Principal(BaseModel):
    tenant_id: str
    actor: str
    role: str = Field(pattern='^(viewer|operator|approver)$')


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    data_dir: str = 'data'
    tenants_file: str = '.tenants.json'
    # JSON mapping bearer tokens to server-owned tenant/actor/role claims.
    api_keys_json: str = '{}'
    extension_origin: str = ''
    llm_enabled: bool = False
    llm_models: str = 'nvidia/nemotron-3-super-120b-a12b:free,nex-agi/nex-n2.5-pro:free'
    poll_attempts: int = Field(default=6, ge=1, le=20)
    poll_seconds: float = Field(default=2, ge=0, le=10)

    voice_enabled: bool = False
    voice_model_path: str = 'data/voice-model'
    channel_worker_enabled: bool = True
    whatsapp_enabled: bool = False
    whatsapp_send_enabled: bool = False
    whatsapp_app_secret: str = ''
    whatsapp_verify_token: str = ''
    whatsapp_access_token: str = ''
    whatsapp_phone_number_id: str = ''
    whatsapp_graph_version: str = 'v25.0'
    whatsapp_links_json: str = '{}'

    def tenants(self):
        path = Path(self.tenants_file)
        values = json.loads(path.read_text()) if path.exists() else [dict(id='demo', name='Acme · Development')]
        tenants = {item.id: item for item in map(Tenant.model_validate, values)}
        if len(tenants) != len(values):
            raise ValueError('Duplicate tenant ID')
        return tenants

    def principals(self):
        values = json.loads(self.api_keys_json)
        if not values:
            raise ValueError('API_KEYS_JSON is required; run python scripts/init_demo.py')
        if any(len(token) < 24 for token in values):
            raise ValueError('API tokens must be at least 24 characters')
        return {token: Principal.model_validate(value) for token, value in values.items()}


def credential(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError('SAP credentials are missing from the backend environment')
    return value
