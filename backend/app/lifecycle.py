"""Lifecycle management: versioning, promotion, rollback, comments."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Lifecycle:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS versions(
            id TEXT PRIMARY KEY, tenant TEXT, artifact_id TEXT,
            version TEXT, status TEXT, content TEXT,
            created_by TEXT, created_at TEXT, promoted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS promotions(
            id TEXT PRIMARY KEY, tenant TEXT, artifact_id TEXT,
            from_env TEXT, to_env TEXT, version TEXT,
            status TEXT, created_at TEXT, approved_by TEXT
        );
        CREATE TABLE IF NOT EXISTS comments(
            id TEXT PRIMARY KEY, tenant TEXT, artifact_id TEXT,
            author TEXT, body TEXT, created_at TEXT, resolved INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS reviews(
            id TEXT PRIMARY KEY, tenant TEXT, artifact_id TEXT,
            version TEXT, reviewer TEXT, decision TEXT,
            comments TEXT, created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_versions_tenant ON versions(tenant);
        CREATE INDEX IF NOT EXISTS idx_promotions_tenant ON promotions(tenant);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def version_artifact(self, tenant: str, artifact_id: str, version: str,
                        content: dict, created_by: str) -> dict:
        vid = f"{artifact_id}:{version}"
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO versions(id,tenant,artifact_id,version,status,content,created_by,created_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (vid, tenant, artifact_id, version, 'draft', json.dumps(content),
                 created_by, now()))
            self.db.commit()
        return {'id': vid, 'artifact_id': artifact_id, 'version': version, 'status': 'draft'}

    def promote(self, tenant: str, artifact_id: str, version: str,
                from_env: str, to_env: str, created_by: str) -> dict:
        pid = f"prom:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with self.lock:
            self.db.execute(
                'INSERT INTO promotions(id,tenant,artifact_id,from_env,to_env,version,status,created_at,approved_by) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
                (pid, tenant, artifact_id, from_env, to_env, version, 'pending_approval', now(), created_by))
            self.db.commit()
        return {'id': pid, 'artifact_id': artifact_id, 'version': version,
                'from_env': from_env, 'to_env': to_env, 'status': 'pending_approval'}

    def approve_promotion(self, promotion_id: str, tenant: str, approver: str):
        with self.lock:
            self.db.execute(
                'UPDATE promotions SET status="approved",approved_by=? WHERE id=? AND tenant=?',
                (approver, promotion_id, tenant))
            self.db.execute(
                'UPDATE versions SET status="released",promoted_at=? WHERE id IN '
                '(SELECT artifact_id || ":" || version FROM promotions WHERE id=? AND tenant=?)',
                (now(), promotion_id, tenant))
            self.db.commit()

    def rollback(self, tenant: str, artifact_id: str, target_version: str,
                 created_by: str) -> dict:
        with self.lock:
            row = self.db.execute(
                'SELECT content FROM versions WHERE artifact_id=? AND version=? AND tenant=?',
                (artifact_id, target_version, tenant)).fetchone()
            if not row:
                raise ValueError(f"Version {target_version} not found")
            current = self.db.execute(
                'SELECT MAX(version) FROM versions WHERE artifact_id=? AND tenant=?',
                (artifact_id, tenant)).fetchone()[0] or '0'
            new_ver = f"rollback_{int(float(current.split('_')[-1])) + 1 if '_' in current else 1}"
            vid = f"{artifact_id}:{new_ver}"
            self.db.execute(
                'INSERT INTO versions(id,tenant,artifact_id,version,status,content,created_by,created_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (vid, tenant, artifact_id, new_ver, 'draft', row['content'],
                 created_by, now()))
            self.db.commit()
        return {'id': vid, 'artifact_id': artifact_id, 'version': new_ver,
                'rolled_back_from': target_version, 'status': 'draft'}

    def add_comment(self, tenant: str, artifact_id: str, author: str, body: str) -> dict:
        cid = f"cmt:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with self.lock:
            self.db.execute(
                'INSERT INTO comments(id,tenant,artifact_id,author,body,created_at) '
                'VALUES(?,?,?,?,?,?)',
                (cid, tenant, artifact_id, author, body, now()))
            self.db.commit()
        return {'id': cid, 'author': author, 'body': body, 'resolved': False}

    def resolve_comment(self, comment_id: str, tenant: str):
        with self.lock:
            self.db.execute('UPDATE comments SET resolved=1 WHERE id=? AND tenant=?',
                          (comment_id, tenant))
            self.db.commit()

    def review(self, tenant: str, artifact_id: str, version: str,
               reviewer: str, decision: str, comments: str = '') -> dict:
        rid = f"rev:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with self.lock:
            self.db.execute(
                'INSERT INTO reviews(id,tenant,artifact_id,version,reviewer,decision,comments,created_at) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (rid, tenant, artifact_id, version, reviewer, decision, comments, now()))
            self.db.commit()
        return {'id': rid, 'decision': decision}

    def versions(self, tenant: str, artifact_id: str | None = None) -> list[dict]:
        q = 'SELECT * FROM versions WHERE tenant=?'
        args: list[Any] = [tenant]
        if artifact_id:
            q += ' AND artifact_id=?'
            args.append(artifact_id)
        q += ' ORDER BY created_at DESC'
        rows = self.db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def promotions(self, tenant: str, status: str | None = None) -> list[dict]:
        q = 'SELECT * FROM promotions WHERE tenant=?'
        args: list[Any] = [tenant]
        if status:
            q += ' AND status=?'
            args.append(status)
        q += ' ORDER BY created_at DESC'
        rows = self.db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def comments(self, tenant: str, artifact_id: str) -> list[dict]:
        rows = self.db.execute(
            'SELECT * FROM comments WHERE tenant=? AND artifact_id=? ORDER BY created_at DESC',
            (tenant, artifact_id)).fetchall()
        return [dict(r) for r in rows]

    def reviews(self, tenant: str, artifact_id: str) -> list[dict]:
        rows = self.db.execute(
            'SELECT * FROM reviews WHERE tenant=? AND artifact_id=? ORDER BY created_at DESC',
            (tenant, artifact_id)).fetchall()
        return [dict(r) for r in rows]
