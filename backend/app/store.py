import json
import sqlite3
import threading
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, tenant TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT, phase TEXT,
          at TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY, status TEXT, result TEXT);
        CREATE TABLE IF NOT EXISTS demo(tenant TEXT, kind TEXT, id TEXT, value TEXT,
          PRIMARY KEY(tenant,kind,id));
        ''')
        self.db.commit()

    def query(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            self.db.commit()
            return rows

    def event(self, run, phase, data):
        self.query('INSERT INTO events(run,phase,at,data) VALUES(?,?,?,?)', (run, phase, now(), json.dumps(data)))

    def once(self, key, operation):
        with self.lock:
            old = self.query('SELECT * FROM operations WHERE key=?', (key,))
            if old:
                if old[0]['status'] == 'done':
                    return json.loads(old[0]['result'])
                raise ValueError('Ambiguous or failed write: inspect SAP before starting a new plan; replay blocked')
            self.query('INSERT INTO operations VALUES(?,?,?)', (key, 'started', '{}'))
        # Persist intent before network I/O. Never blindly repeat a side effect after a crash.
        result = operation()
        self.query('UPDATE operations SET status=?,result=? WHERE key=?', ('done', json.dumps(result), key))
        return result

    def demo_get(self, tenant, kind, item=None):
        rows = self.query('SELECT value FROM demo WHERE tenant=? AND kind=?' + (' AND id=?' if item else ''),
                          (tenant, kind, item) if item else (tenant, kind))
        values = [json.loads(r['value']) for r in rows]
        return (values[0] if values else None) if item else values

    def demo_put(self, tenant, kind, item, value):
        self.query('INSERT OR REPLACE INTO demo VALUES(?,?,?,?)', (tenant, kind, item, json.dumps(value)))
        return value
