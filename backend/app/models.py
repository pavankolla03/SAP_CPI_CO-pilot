import base64
import hashlib
import io
import json
from pathlib import PurePosixPath
from typing import Literal
from zipfile import ZipFile

from defusedxml import ElementTree
from pydantic import BaseModel, Field, model_validator

Identifier = str


def identifier(value: str):
    import re
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', value):
        raise ValueError('Invalid SAP identifier')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def inspect_bundle(content: str):
    try:
        raw = base64.b64decode(content, validate=True)
        if len(raw) > 4_000_000:
            raise ValueError('ZIP must be under 4 MB')
        with ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len(infos) > 300 or sum(i.file_size for i in infos) > 20_000_000:
                raise ValueError('Expanded ZIP is too large')
            names = [i.filename for i in infos]
            if len(set(names)) != len(names):
                raise ValueError('Duplicate archive entries')
            for name in names:
                if name.startswith('/') or '..' in PurePosixPath(name).parts or '\\' in name:
                    raise ValueError('Unsafe ZIP path')
            flows = [n for n in names if n.endswith('.iflw')]
            if not flows or 'META-INF/MANIFEST.MF' not in names:
                raise ValueError('Expected exported iFlow ZIP with manifest and .iflw model')
            for flow in flows:
                ElementTree.fromstring(archive.read(flow))
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'files': names}
    except Exception as exc:
        # Only validation messages are exposed; never archive content.
        if isinstance(exc, ValueError):
            raise
        raise ValueError('Invalid iFlow ZIP or XML') from None


class RunRequest(BaseModel):
    goal: str = Field(default='Deploy a reviewed iFlow to DEV', max_length=2000)
    action: Literal['create_package', 'deploy', 'upload', 'upload_deploy', 'create_partner_parameter'] = 'deploy'
    package_id: str = Field(default='AgentSandbox', max_length=160)
    artifact_id: str = Field(default='HelloWorld', max_length=160)
    name: str = Field(default='Agent Sandbox', min_length=1, max_length=160)
    version: str = Field(default='active', max_length=40)
    artifact_content: str | None = Field(default=None, max_length=5_400_000)

    partner_id: str = Field(default='RelayTestPartner', max_length=160)
    parameter_id: str = Field(default='RelayTestParameter', max_length=160)
    parameter_value: str = Field(default='test', max_length=1000)

    @model_validator(mode='after')
    def check(self):
        for value in (self.package_id, self.artifact_id, self.version, self.partner_id, self.parameter_id):
            identifier(value)
        if self.action in ('upload','upload_deploy'):
            if not self.artifact_content:
                raise ValueError('Upload requires an exported iFlow ZIP')
            inspect_bundle(self.artifact_content)
        elif self.artifact_content:
            raise ValueError('ZIP is only accepted for upload or upload_deploy')
        return self


class Decision(BaseModel):
    approve: bool
    plan_hash: str = Field(min_length=64, max_length=64)
