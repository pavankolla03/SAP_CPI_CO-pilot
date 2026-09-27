"""Knowledge graph: reusable patterns, mappings, conventions."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeGraph:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS nodes(
            id TEXT PRIMARY KEY, kind TEXT, tenant TEXT,
            name TEXT, content TEXT, tags TEXT, created TEXT, updated TEXT
        );
        CREATE TABLE IF NOT EXISTS edges(
            src TEXT, dst TEXT, kind TEXT, weight REAL DEFAULT 1.0,
            PRIMARY KEY(src, dst, kind)
        );
        CREATE TABLE IF NOT EXISTS suggestions(
            id TEXT PRIMARY KEY, tenant TEXT, context TEXT,
            node_id TEXT, confidence REAL, created TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
        CREATE INDEX IF NOT EXISTS idx_nodes_tenant ON nodes(tenant);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def add_node(self, kind: str, name: str, content: dict, tags: list[str] | None = None,
                 tenant: str = 'global', node_id: str | None = None) -> dict:
        nid = node_id or f"{kind}:{name}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO nodes(id,kind,tenant,name,content,tags,created,updated) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (nid, kind, tenant, name, json.dumps(content), json.dumps(tags or []),
                 now(), now()))
            self.db.commit()
        return {'id': nid, 'kind': kind, 'name': name, 'tags': tags or []}

    def add_edge(self, src: str, dst: str, kind: str = 'related', weight: float = 1.0):
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO edges(src,dst,kind,weight) VALUES(?,?,?,?)',
                (src, dst, kind, weight))
            self.db.commit()

    def search(self, query: str, kind: str | None = None, tenant: str = 'global',
               limit: int = 20) -> list[dict]:
        q = 'SELECT * FROM nodes WHERE tenant=? AND (name LIKE ? OR content LIKE ?)'
        args: list[Any] = [tenant, f'%{query}%', f'%{query}%']
        if kind:
            q += ' AND kind=?'
            args.append(kind)
        q += ' ORDER BY updated DESC LIMIT ?'
        args.append(limit)
        rows = self.db.execute(q, args).fetchall()
        return [self._row(r) for r in rows]

    def similar(self, node_id: str, limit: int = 10) -> list[dict]:
        rows = self.db.execute(
            'SELECT dst, kind, weight FROM edges WHERE src=? ORDER BY weight DESC LIMIT ?',
            (node_id, limit)).fetchall()
        results = []
        for row in rows:
            n = self.db.execute('SELECT * FROM nodes WHERE id=?', (row['dst'],)).fetchone()
            if n:
                results.append({**self._row(n), 'edge_kind': row['kind'], 'weight': row['weight']})
        return results

    def suggest(self, context: str, tenant: str = 'global', limit: int = 5) -> list[dict]:
        hits = self.search(context, tenant=tenant, limit=limit * 3)
        scored = []
        for h in hits:
            score = len(context) / (len(context) + len(h.get('name', ''))) * h.get('_weight', 1.0)
            scored.append({**h, 'confidence': round(min(score, 0.99), 2)})
        scored.sort(key=lambda x: x['confidence'], reverse=True)
        suggestions = []
        with self.lock:
            for s in scored[:limit]:
                sid = f"sugg:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
                self.db.execute(
                    'INSERT OR REPLACE INTO suggestions(id,tenant,context,node_id,confidence,created) '
                    'VALUES(?,?,?,?,?,?)',
                    (sid, tenant, context, s['id'], s['confidence'], now()))
                suggestions.append(s)
            self.db.commit()
        return suggestions

    def team_conventions(self, tenant: str) -> list[dict]:
        rows = self.db.execute(
            'SELECT * FROM nodes WHERE tenant=? AND kind="convention" ORDER BY updated DESC',
            (tenant,)).fetchall()
        return [self._row(r) for r in rows]

    def seed_defaults(self, tenant: str = 'global'):
        defaults = [
            ('convention', 'error-handling-retry', {'pattern': 'Exponential backoff: 1s, 2s, 4s, 8s', 'max_retries': 4, 'dlq': True}, ['error-handling', 'retry']),
            ('convention', 'naming-convention', {'flow': 'FLOW_{DOMAIN}_{ACTION}', 'package': 'PKG_{DOMAIN}', 'mapping': 'MAP_{SOURCE}_{TARGET}'}, ['naming']),
            ('pattern', 'request-reply-sync', {'type': 'request-reply', 'timeout': 30000, 'retry': 3}, ['integration', 'sync']),
            ('pattern', 'async-store-forward', {'type': 'store-and-forward', 'persist': True, 'trigger': 'timer'}, ['integration', 'async']),
            ('mapping', 'sap-idoc-standard', {'idoc_type': 'MATMAS04', 'segment': 'E1MARAM', 'fields': ['MATNR', 'MAKTX', 'MEINS']}, ['idoc', 'sap']),
            ('connector', 'sap-successfactors', {'adapter': 'HTTPS', 'auth': 'OAuth2', 'endpoint': '/OData/v2'}, ['sap', 'hr']),
            ('connector', 'sap-s4hana', {'adapter': 'IDoc', 'version': 'IDoc', 'encoding': 'UTF-8'}, ['sap', 'erp']),
        ]
        for kind, name, content, tags in defaults:
            self.add_node(kind, name, content, tags, tenant)

    def _row(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d['content'] = json.loads(d['content']) if d.get('content') else {}
        d['tags'] = json.loads(d['tags']) if d.get('tags') else []
        d.pop('content', None)
        d.pop('tags', None)
        return d
