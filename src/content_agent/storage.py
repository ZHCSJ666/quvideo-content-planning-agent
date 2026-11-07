"""Local state + tool receipts committed together. Single-task OS lock at service boundary."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .domain import canonical, digest


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "business.sqlite", timeout=30, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, args_hash TEXT NOT NULL, state TEXT NOT NULL);
        """)

    def close(self):
        self.db.close()

    def get(self, task_id):
        row = self.db.execute("SELECT state FROM runs WHERE id=?", (task_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def create(self, state):
        fingerprint = digest({k: state[k] for k in ("brief", "mode", "scenario")})
        old = self.db.execute("SELECT fingerprint,state FROM runs WHERE id=?", (state["task_id"],)).fetchone()
        if old:
            if old[0] != fingerprint:
                raise ValueError("task_id already exists with a different request; use resume or a new ID")
            return json.loads(old[1]), False
        with self.db:
            self.db.execute("INSERT INTO runs VALUES (?,?,?)", (state["task_id"], fingerprint, canonical(state)))
        return state, True

    def save(self, state):
        with self.db:
            self.db.execute("UPDATE runs SET state=? WHERE id=?", (canonical(state), state["task_id"]))

    def receipt(self, op_id, action):
        row = self.db.execute("SELECT args_hash,state FROM receipts WHERE id=?", (op_id,)).fetchone()
        if not row:
            return None
        if row[0] != digest(action):
            raise RuntimeError("operation replay with different arguments")
        return json.loads(row[1])

    def commit_operation(self, op_id, action, state):
        with self.db:
            self.db.execute("INSERT INTO receipts VALUES (?,?,?)", (op_id, digest(action), canonical(state)))
            self.db.execute("UPDATE runs SET state=? WHERE id=?", (canonical(state), state["task_id"]))

    def list_runs(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT state FROM runs ORDER BY rowid DESC")]

    @contextmanager
    def lock(self, task_id):
        import fcntl
        path = self.root / (digest(task_id) + ".lock")
        with path.open("w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("task is currently running in another process") from exc
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
