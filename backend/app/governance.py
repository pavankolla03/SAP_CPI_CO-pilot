"""Governance: roles, approval policies, audit logging, credential safety."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Governance:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS audit_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant TEXT, actor TEXT, action TEXT, target TEXT,
            detail TEXT, ip TEXT, ts TEXT
        );
        CREATE TABLE IF NOT EXISTS policies(
            id TEXT PRIMARY KEY, tenant TEXT, name TEXT,
            rules TEXT, created_at TEXT, updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS tokens(
            id TEXT PRIMARY KEY, tenant TEXT, name TEXT,
            scope TEXT, expires_at TEXT, last_used TEXT,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_tenant_ts ON audit_log(tenant, ts);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def audit(self, tenant: str, actor: str, action: str, target: str,
              detail: str, ip: str | None = None):
        with self.lock:
            self.db.execute(
                'INSERT INTO audit_log(tenant,actor,action,target,detail,ip,ts) '
                'VALUES(?,?,?,?,?,?,?)',
                (tenant, actor, action, target, detail, ip, now()))
            self.db.commit()

    def policy(self, tenant: str, name: str, rules: dict) -> dict:
        pid = f"pol:{tenant}:{name}"
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO policies(id,tenant,name,rules,created_at,updated_at) '
                'VALUES(?,?,?,?,?,?)',
                (pid, tenant, name, json.dumps(rules), now(), now()))
            self.db.commit()
        return {'id': pid, 'name': name, 'rules': rules}

    def policies(self, tenant: str) -> list[dict]:
        rows = self.db.execute('SELECT * FROM policies WHERE tenant=?', (tenant,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d['rules'] = json.loads(d['rules']) if d['rules'] else {}
            result.append(d)
        return result

    def register_token(self, tenant: str, name: str, scope: list[str],
                       expires_at: str | None = None) -> dict:
        tid = f"tok:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with self.lock:
            self.db.execute(
                'INSERT INTO tokens(id,tenant,name,scope,expires_at,created_at) '
                'VALUES(?,?,?,?,?,?)',
                (tid, tenant, name, json.dumps(scope), expires_at, now()))
            self.db.commit()
        return {'id': tid, 'name': name, 'scope': scope}

    def rotate_token(self, token_id: str, tenant: str):
        with self.lock:
            self.db.execute('UPDATE tokens SET expires_at=? WHERE id=? AND tenant=?',
                          (now(), token_id, tenant))
            self.db.commit()

    def audit_log(self, tenant: str, action: str | None = None,
                  limit: int = 100) -> list[dict]:
        q = 'SELECT * FROM audit_log WHERE tenant=?'
        args: list[Any] = [tenant]
        if action:
            q += ' AND action=?'
            args.append(action)
        q += ' ORDER BY ts DESC LIMIT ?'
        args.append(limit)
        rows = self.db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def check_permission(self, actor_role: str, action: str) -> bool:
        draft_actions = {'create_package', 'upload', 'design', 'compile', 'propose'}
        approval_actions = {'deploy', 'upload_deploy', 'promote', 'rollback'}
        if action in approval_actions:
            return actor_role == 'approver'
        if action in draft_actions:
            return actor_role in ('operator', 'approver')
        return actor_role in ('viewer', 'operator', 'approver')
