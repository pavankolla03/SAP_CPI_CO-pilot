"""Analytics: usage reports, throughput, failure trends."""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone, timedelta
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Analytics:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS usage(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant TEXT, action TEXT, artifact_id TEXT, package_id TEXT,
            duration_ms REAL, status TEXT, channel TEXT,
            ts TEXT
        );
        CREATE TABLE IF NOT EXISTS throughput(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant TEXT, artifact_id TEXT, messages_count INTEGER,
            bytes_count INTEGER, window_start TEXT, window_end TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_usage_tenant_ts ON usage(tenant, ts);
        CREATE INDEX IF NOT EXISTS idx_throughput_tenant ON throughput(tenant);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def record_usage(self, tenant: str, action: str, artifact_id: str, package_id: str,
                     duration_ms: float, status: str, channel: str = 'web'):
        with self.lock:
            self.db.execute(
                'INSERT INTO usage(tenant,action,artifact_id,package_id,duration_ms,status,channel,ts) '
                'VALUES(?,?,?,?,?,?,?,?)',
                (tenant, action, artifact_id, package_id, duration_ms, status, channel, now()))
            self.db.commit()

    def record_throughput(self, tenant: str, artifact_id: str, messages: int,
                          bytes_count: int, window_minutes: int = 60):
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=window_minutes)
        with self.lock:
            self.db.execute(
                'INSERT INTO throughput(tenant,artifact_id,messages_count,bytes_count,window_start,window_end) '
                'VALUES(?,?,?,?,?,?)',
                (tenant, artifact_id, messages, bytes_count, start.isoformat(), end.isoformat()))
            self.db.commit()

    def usage_report(self, tenant: str, days: int = 7) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        by_action = self.db.execute(
            'SELECT action, COUNT(*) as count, AVG(duration_ms) as avg_ms, '
            'SUM(CASE WHEN status="success" THEN 1 ELSE 0 END) as successes '
            'FROM usage WHERE tenant=? AND ts>=? GROUP BY action',
            (tenant, since)).fetchall()
        by_channel = self.db.execute(
            'SELECT channel, COUNT(*) as count FROM usage WHERE tenant=? AND ts>=? '
            'GROUP BY channel', (tenant, since)).fetchall()
        daily = self.db.execute(
            'SELECT DATE(ts) as day, COUNT(*) as count, '
            'SUM(CASE WHEN status="success" THEN 1 ELSE 0 END) as successes '
            'FROM usage WHERE tenant=? AND ts>=? GROUP BY day ORDER BY day',
            (tenant, since)).fetchall()
        return {
            'period_days': days,
            'by_action': [dict(r) for r in by_action],
            'by_channel': [dict(r) for r in by_channel],
            'daily': [dict(r) for r in daily],
            'total_actions': sum(r['count'] for r in by_action),
            'success_rate': round(sum(r['successes'] for r in by_action) / max(sum(r['count'] for r in by_action), 1) * 100, 1),
        }

    def throughput_report(self, tenant: str, hours: int = 24) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = self.db.execute(
            'SELECT artifact_id, SUM(messages_count) as messages, SUM(bytes_count) as bytes, '
            'COUNT(*) as windows FROM throughput WHERE tenant=? AND window_end>=? '
            'GROUP BY artifact_id ORDER BY messages DESC',
            (tenant, since)).fetchall()
        return {
            'period_hours': hours,
            'artifacts': [dict(r) for r in rows],
            'total_messages': sum(r['messages'] for r in rows),
            'total_bytes': sum(r['bytes'] for r in rows),
        }

    def failure_clusters(self, tenant: str, days: int = 7) -> dict:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        failures = self.db.execute(
            'SELECT artifact_id, action, COUNT(*) as fail_count, '
            'GROUP_CONCAT(status) as statuses '
            'FROM usage WHERE tenant=? AND ts>=? AND status!="success" '
            'GROUP BY artifact_id, action ORDER BY fail_count DESC LIMIT 20',
            (tenant, since)).fetchall()
        return {
            'period_days': days,
            'failure_clusters': [dict(r) for r in failures],
            'total_failures': sum(r['fail_count'] for r in failures),
        }
