"""Monitoring: dashboards, alerts, end-to-end tracing."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Monitoring:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metrics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant TEXT, kind TEXT, label TEXT, value REAL,
            unit TEXT, tags TEXT, ts TEXT
        );
        CREATE TABLE IF NOT EXISTS alerts(
            id TEXT PRIMARY KEY, tenant TEXT, severity TEXT,
            title TEXT, detail TEXT, source TEXT, status TEXT DEFAULT 'open',
            created TEXT, resolved TEXT
        );
        CREATE TABLE IF NOT EXISTS traces(
            id TEXT PRIMARY KEY, tenant TEXT, run_id TEXT,
            artifact_id TEXT, message_id TEXT, status TEXT,
            start_ts TEXT, end_ts TEXT, hops TEXT, error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_metrics_tenant_ts ON metrics(tenant, ts);
        CREATE INDEX IF NOT EXISTS idx_alerts_tenant ON alerts(tenant);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def record(self, tenant: str, kind: str, label: str, value: float,
               unit: str = '', tags: list[str] | None = None):
        with self.lock:
            self.db.execute(
                'INSERT INTO metrics(tenant,kind,label,value,unit,tags,ts) VALUES(?,?,?,?,?,?,?)',
                (tenant, kind, label, value, unit, json.dumps(tags or []), now()))
            self.db.commit()

    def record_deployment(self, tenant: str, artifact_id: str, status: str,
                          duration_s: float, error: str | None = None):
        self.record(tenant, 'deployment', f"{artifact_id}:{status}", duration_s,
                    'seconds', tags=[status])
        if status == 'FAILED' and error:
            self.alert(tenant, 'error', f"Deployment failed: {artifact_id}",
                       error, source='agent')

    def alert(self, tenant: str, severity: str, title: str, detail: str,
              source: str = 'system', alert_id: str | None = None) -> dict:
        aid = alert_id or f"alt:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with self.lock:
            self.db.execute(
                'INSERT OR REPLACE INTO alerts(id,tenant,severity,title,detail,source,status,created) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (aid, tenant, severity, title, detail, source, 'open', now()))
            self.db.commit()
        return {'id': aid, 'severity': severity, 'title': title, 'status': 'open'}

    def resolve_alert(self, alert_id: str, tenant: str):
        with self.lock:
            self.db.execute('UPDATE alerts SET status="resolved",resolved=? WHERE id=? AND tenant=?',
                          (now(), alert_id, tenant))
            self.db.commit()

    def get_alerts(self, tenant: str, status: str = 'open', limit: int = 50) -> list[dict]:
        rows = self.db.execute(
            'SELECT * FROM alerts WHERE tenant=? AND status=? ORDER BY created DESC LIMIT ?',
            (tenant, status, limit)).fetchall()
        return [dict(r) for r in rows]

    def start_trace(self, tenant: str, run_id: str, artifact_id: str,
                    message_id: str) -> dict:
        tid = f"tr:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        with self.lock:
            self.db.execute(
                'INSERT INTO traces(id,tenant,run_id,artifact_id,message_id,status,start_ts) '
                'VALUES(?,?,?,?,?,?,?)',
                (tid, tenant, run_id, artifact_id, message_id, 'running', now()))
            self.db.commit()
        return {'id': tid, 'status': 'running'}

    def hop(self, trace_id: str, node: str, status: str = 'ok', error: str | None = None):
        with self.lock:
            row = self.db.execute('SELECT hops FROM traces WHERE id=?', (trace_id,)).fetchone()
            hops = json.loads(row['hops']) if row and row['hops'] else []
            hops.append({'node': node, 'ts': now(), 'status': status, 'error': error})
            self.db.execute('UPDATE traces SET hops=? WHERE id=?', (json.dumps(hops), trace_id))
            self.db.commit()

    def end_trace(self, trace_id: str, status: str, error: str | None = None):
        with self.lock:
            self.db.execute('UPDATE traces SET status=?,end_ts=?,error=? WHERE id=?',
                          (status, now(), error, trace_id))
            self.db.commit()

    def dashboard(self, tenant: str) -> dict:
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
        depl_rows = self.db.execute(
            'SELECT label, COUNT(*) as cnt, AVG(value) as avg_dur '
            'FROM metrics WHERE tenant=? AND kind="deployment" AND ts>=? GROUP BY label',
            (tenant, since)).fetchall()
        deployments = []
        for r in depl_rows:
            label = r['label']
            status = label.split(':')[-1] if ':' in label else label
            deployments.append({'status': status, 'count': r['cnt'], 'avg_duration_s': round(r['avg_dur'], 1)})

        alerts_open = self.db.execute(
            'SELECT COUNT(*) as c FROM alerts WHERE tenant=? AND status="open"',
            (tenant,)).fetchone()['c']
        alerts = self.db.execute(
            'SELECT * FROM alerts WHERE tenant=? AND status="open" ORDER BY created DESC LIMIT 10'
        ).fetchall()

        recent = self.db.execute(
            'SELECT * FROM metrics WHERE tenant=? AND ts>=? ORDER BY ts DESC LIMIT 20',
            (tenant, since)).fetchall()

        return {
            'date': datetime.now(timezone.utc).date().isoformat(),
            'deployments': deployments,
            'alerts_open': alerts_open,
            'recent_alerts': [dict(r) for r in alerts],
            'recent_metrics': [dict(r) for r in recent],
        }

    def trace(self, trace_id: str, tenant: str) -> dict | None:
        row = self.db.execute('SELECT * FROM traces WHERE id=? AND tenant=?', (trace_id, tenant)).fetchone()
        return dict(row) if row else None
