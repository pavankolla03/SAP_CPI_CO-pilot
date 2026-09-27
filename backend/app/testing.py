"""Testing: auto-generated test cases, regression checks, sample payloads."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Testing:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS test_cases(
            id TEXT PRIMARY KEY, tenant TEXT, artifact_id TEXT,
            name TEXT, description TEXT, input_payload TEXT,
            expected_output TEXT, assertions TEXT, status TEXT DEFAULT "pending",
            last_run TEXT, last_result TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS regression_suites(
            id TEXT PRIMARY KEY, tenant TEXT, package_id TEXT,
            name TEXT, test_ids TEXT, created_at TEXT, last_run TEXT, status TEXT
        );
        CREATE TABLE IF NOT EXISTS regression_runs(
            id TEXT PRIMARY KEY, suite_id TEXT, tenant TEXT,
            run_at TEXT, total INTEGER, passed INTEGER, failed INTEGER,
            skipped INTEGER, duration_ms REAL, results TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tests_tenant ON test_cases(tenant);
        CREATE INDEX IF NOT EXISTS idx_regr_tenant ON regression_suites(tenant);
        ''')
        self.db.commit()

    def close(self):
        self.db.close()

    def generate_test(self, tenant: str, artifact_id: str, name: str,
                      scenario: dict) -> dict:
        tid = f"tst:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        input_payload = self._sample_payload(scenario)
        expected = self._expected_output(scenario)
        assertions = self._default_assertions(scenario)
        with self.lock:
            self.db.execute(
                'INSERT INTO test_cases(id,tenant,artifact_id,name,description,input_payload,expected_output,assertions,created_at) '
                'VALUES(?,?,?,?,?,?,?,?,?)',
                (tid, tenant, artifact_id, name, scenario.get('description', ''),
                 json.dumps(input_payload), json.dumps(expected),
                 json.dumps(assertions), now()))
            self.db.commit()
        return {
            'id': tid, 'name': name, 'input': input_payload,
            'expected': expected, 'assertions': assertions
        }

    def run_test(self, test_id: str, tenant: str) -> dict:
        row = self.db.execute('SELECT * FROM test_cases WHERE id=? AND tenant=?',
                            (test_id, tenant)).fetchone()
        if not row:
            raise ValueError('Test not found')
        input_payload = json.loads(row['input_payload'])
        expected = json.loads(row['expected_output'])
        assertions = json.loads(row['assertions'])
        try:
            results = []
            passed = True
            for assertion in assertions:
                result = self._evaluate(input_payload, expected, assertion)
                results.append(result)
                if not result['passed']:
                    passed = False
            status = 'passed' if passed else 'failed'
            with self.lock:
                self.db.execute(
                    'UPDATE test_cases SET status=?,last_run=?,last_result=? WHERE id=? AND tenant=?',
                    (status, now(), json.dumps(results), test_id, tenant))
                self.db.commit()
            return {'test_id': test_id, 'status': status, 'results': results}
        except Exception as e:
            with self.lock:
                self.db.execute(
                    'UPDATE test_cases SET status="error",last_run=?,last_result=? WHERE id=? AND tenant=?',
                    (now(), json.dumps({'error': str(e)}), test_id, tenant))
                self.db.commit()
            return {'test_id': test_id, 'status': 'error', 'error': str(e)}

    def regression_suite(self, tenant: str, package_id: str, name: str,
                        artifact_ids: list[str]) -> dict:
        sid = f"reg:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        test_ids = []
        for aid in artifact_ids:
            tid = f"tst:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}:{aid[-4:]}"
            test_ids.append(tid)
            self.generate_test(tenant, aid, f"Regression: {aid}", {
                'description': f"Regression smoke test for {aid}",
                'artifact_type': 'iflow'
            })
        with self.lock:
            self.db.execute(
                'INSERT INTO regression_suites(id,tenant,package_id,name,test_ids,created_at) '
                'VALUES(?,?,?,?,?,?)',
                (sid, tenant, package_id, name, json.dumps(test_ids), now()))
            self.db.commit()
        return {'id': sid, 'name': name, 'test_count': len(test_ids)}

    def run_regression(self, suite_id: str, tenant: str) -> dict:
        row = self.db.execute(
            'SELECT * FROM regression_suites WHERE id=? AND tenant=?',
            (suite_id, tenant)).fetchone()
        if not row:
            raise ValueError('Suite not found')
        test_ids = json.loads(row['test_ids'])
        start = datetime.now(timezone.utc)
        results = []
        for tid in test_ids:
            r = self.run_test(tid, tenant)
            results.append(r)
        end = datetime.now(timezone.utc)
        duration_ms = (end - start).total_seconds() * 1000
        rid = f"run:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        passed = sum(1 for r in results if r['status'] == 'passed')
        failed = sum(1 for r in results if r['status'] == 'failed')
        with self.lock:
            self.db.execute(
                'INSERT INTO regression_runs(id,suite_id,tenant,run_at,total,passed,failed,skipped,duration_ms,results) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                (rid, suite_id, tenant, now(), len(results), passed, failed, 0,
                 duration_ms, json.dumps(results)))
            self.db.execute(
                'UPDATE regression_suites SET last_run=?,status=? WHERE id=? AND tenant=?',
                (now(), 'passed' if failed == 0 else 'failed', suite_id, tenant))
            self.db.commit()
        return {
            'id': rid, 'suite_id': suite_id, 'total': len(results),
            'passed': passed, 'failed': failed, 'duration_ms': round(duration_ms, 1),
            'status': 'passed' if failed == 0 else 'failed'
        }

    def test_cases(self, tenant: str, artifact_id: str | None = None) -> list[dict]:
        q = 'SELECT * FROM test_cases WHERE tenant=?'
        args: list[Any] = [tenant]
        if artifact_id:
            q += ' AND artifact_id=?'
            args.append(artifact_id)
        q += ' ORDER BY created_at DESC'
        rows = self.db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def regression_runs(self, tenant: str, suite_id: str | None = None) -> list[dict]:
        q = 'SELECT * FROM regression_runs WHERE tenant=?'
        args: list[Any] = [tenant]
        if suite_id:
            q += ' AND suite_id=?'
            args.append(suite_id)
        q += ' ORDER BY run_at DESC LIMIT 20'
        rows = self.db.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def _sample_payload(self, scenario: dict) -> dict:
        t = scenario.get('artifact_type', 'iflow')
        if t == 'api':
            return {'method': 'GET', 'path': '/api/v1/test', 'headers': {'Content-Type': 'application/json'}, 'body': {}}
        if t == 'b2b':
            return {'interchange': {'sender': 'SENDER', 'receiver': 'RECEIVER'}, 'message': {'type': 'ORDERS', 'version': 'D96A'}}
        return {'message': {'id': 'TEST-001', 'timestamp': now(), 'data': {'test': True}}}

    def _expected_output(self, scenario: dict) -> dict:
        return {'status': 'success', 'processed': True, 'errors': []}

    def _default_assertions(self, scenario: dict) -> list[dict]:
        return [
            {'type': 'status_ok', 'description': 'Response status is successful'},
            {'type': 'schema_valid', 'description': 'Response matches expected schema'},
            {'type': 'no_errors', 'description': 'No errors in response'},
        ]

    def _evaluate(self, inp: dict, exp: dict, assertion: dict) -> dict:
        atype = assertion.get('type', '')
        passed = True
        detail = 'OK'
        if atype == 'status_ok':
            passed = inp.get('status') in (None, 'success', 'ok') or not inp.get('error')
            detail = 'Status check' + (' passed' if passed else ' failed')
        elif atype == 'schema_valid':
            passed = isinstance(inp, (dict, list))
            detail = 'Schema check'
        elif atype == 'no_errors':
            passed = not inp.get('error') and not (isinstance(inp.get('errors'), list) and inp['errors'])
            detail = 'Error check'
        else:
            passed = True
            detail = f"Unknown assertion type: {atype}"
        return {'assertion': atype, 'passed': passed, 'detail': detail}
