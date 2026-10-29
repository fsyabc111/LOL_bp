"""Branch storage: a branch is a historical prefix plus user actions, kept apart from source data."""
import contextlib
import datetime
import json
from pathlib import Path
import sqlite3

from . import draft

DEFAULT_PATH = Path(__file__).resolve().parents[1] / 'data/app/branches.sqlite3'


class BranchNotFound(KeyError):
    pass


class BranchStore:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, gameid TEXT NOT NULL, '
                      'fork_step INTEGER NOT NULL, name TEXT NOT NULL, fearless_override TEXT, created_at TEXT NOT NULL, '
                      'updated_at TEXT NOT NULL, actions_json TEXT NOT NULL)')

    @contextlib.contextmanager
    def _connect(self):
        """Commit (or roll back) and close; sqlite3's own context manager only commits."""
        connection = sqlite3.connect(self.path); connection.row_factory = sqlite3.Row
        try:
            with connection: yield connection
        finally: connection.close()

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _row(self, branch_id):
        with self._connect() as c:
            row = c.execute('SELECT * FROM branches WHERE id = ?', (branch_id,)).fetchone()
        if row is None: raise BranchNotFound(branch_id)
        return {**dict(row), 'actions': json.loads(row['actions_json'])}

    def list(self, gameid=None):
        with self._connect() as c:
            rows = c.execute('SELECT * FROM branches WHERE (? IS NULL OR gameid = ?) ORDER BY id', (gameid, gameid)).fetchall()
        return [{**dict(r), 'actions': json.loads(r['actions_json'])} for r in rows]

    def create(self, repository, gameid, fork_step, name, fearless_override=None):
        steps, _, _ = repository.sequence(gameid)
        if not 0 <= fork_step <= len(steps): raise ValueError('fork_step out of range')
        now = self._now()
        with self._connect() as c:
            cursor = c.execute('INSERT INTO branches (gameid, fork_step, name, fearless_override, created_at, updated_at, actions_json) '
                               'VALUES (?, ?, ?, ?, ?, ?, ?)', (gameid, fork_step, name, fearless_override, now, now, '[]'))
        return cursor.lastrowid

    def delete(self, branch_id):
        self._row(branch_id)
        with self._connect() as c: c.execute('DELETE FROM branches WHERE id = ?', (branch_id,))

    def actions(self, repository, branch):
        """Historical prefix up to fork_step followed by the branch's own actions."""
        rules, _, _ = repository.draft_rules(branch['gameid'], branch['fearless_override'])
        steps, _, _ = repository.sequence(branch['gameid'])
        prefix = tuple(draft.Action(s['step'], s['side'], s['action'], s['champion']) for s in steps[:branch['fork_step']])
        own = tuple(draft.Action(a['step'], a['side'], a['action'], a['champion']) for a in branch['actions'])
        return rules, prefix + own

    def append(self, repository, branch_id, champion):
        branch = self._row(branch_id)
        rules, actions = self.actions(repository, branch)
        new = draft.apply(rules, actions, champion)[-1]
        self._save(branch_id, branch['actions'] + [{'step': new.step, 'side': new.side, 'action': new.action, 'champion': new.champion}])

    def undo(self, branch_id):
        branch = self._row(branch_id)
        if not branch['actions']: raise ValueError('nothing to undo at fork point')
        self._save(branch_id, branch['actions'][:-1])

    def _save(self, branch_id, actions):
        with self._connect() as c:
            c.execute('UPDATE branches SET actions_json = ?, updated_at = ? WHERE id = ?', (json.dumps(actions), self._now(), branch_id))

    def get(self, branch_id):
        return self._row(branch_id)
