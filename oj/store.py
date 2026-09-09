"""SQLite persistence, with all disk operations off the ASGI event loop."""

import asyncio
import json
import sqlite3
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)

    async def initialize(self):
        def initialize():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.path) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS documents "
                    "(namespace TEXT, id TEXT, value TEXT NOT NULL, "
                    "PRIMARY KEY(namespace, id))"
                )

        await asyncio.to_thread(initialize)

    async def _worker(self, operation):
        """Run one SQLite operation without releasing a caller lock on cancellation."""

        worker = asyncio.create_task(asyncio.to_thread(operation))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            # Cancelling an await cannot stop SQLite's worker thread. Keep the
            # caller's mutation lock until its transaction really has finished.
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
            try:
                worker.result()
            except Exception:
                pass
            raise

    async def _query(self, sql, args=(), *, fetch=None):
        def run():
            with sqlite3.connect(self.path, timeout=15) as db:
                cursor = db.execute(sql, args)
                if fetch == "one":
                    row = cursor.fetchone()
                    return json.loads(row[0]) if row else None
                if fetch == "all":
                    return [json.loads(row[0]) for row in cursor.fetchall()]

        return await self._worker(run)

    async def get(self, namespace, key):
        return await self._query(
            "SELECT value FROM documents WHERE namespace=? AND id=?", (namespace, key), fetch="one"
        )

    async def all(self, namespace):
        return await self._query(
            "SELECT value FROM documents WHERE namespace=? ORDER BY rowid",
            (namespace,),
            fetch="all",
        )

    async def put(self, namespace, key, value):
        await self._query(
            "INSERT INTO documents(namespace,id,value) VALUES(?,?,?) "
            "ON CONFLICT(namespace,id) DO UPDATE SET value=excluded.value",
            (namespace, key, json.dumps(value, ensure_ascii=False)),
        )

    async def delete(self, namespace, key):
        await self._query("DELETE FROM documents WHERE namespace=? AND id=?", (namespace, key))

    async def snapshot(self, *namespaces):
        """Read several namespaces from the same SQLite transaction snapshot."""

        ordered = tuple(dict.fromkeys(str(namespace) for namespace in namespaces))
        if not ordered or any(not namespace for namespace in ordered):
            raise ValueError("at least one non-empty namespace is required")

        def run():
            result = {}
            with sqlite3.connect(self.path, timeout=15) as db:
                db.execute("BEGIN")
                for namespace in ordered:
                    rows = db.execute(
                        "SELECT value FROM documents WHERE namespace=? ORDER BY rowid",
                        (namespace,),
                    ).fetchall()
                    result[namespace] = [json.loads(row[0]) for row in rows]
                db.commit()
            return result

        return await self._worker(run)

    async def write_batch(self, *, puts=(), deletes=()):
        """Atomically apply document writes and deletes in one transaction."""

        encoded = [
            (str(namespace), str(key), json.dumps(value, ensure_ascii=False))
            for namespace, key, value in puts
        ]
        removals = [(str(namespace), str(key)) for namespace, key in deletes]
        if any(not namespace or not key for namespace, key, *_ in encoded) or any(
            not namespace or not key for namespace, key in removals
        ):
            raise ValueError("namespace and key must be non-empty")

        def run():
            with sqlite3.connect(self.path, timeout=15) as db:
                db.execute("BEGIN IMMEDIATE")
                for namespace, key, value in encoded:
                    db.execute(
                        "INSERT INTO documents(namespace,id,value) VALUES(?,?,?) "
                        "ON CONFLICT(namespace,id) DO UPDATE SET value=excluded.value",
                        (namespace, key, value),
                    )
                for namespace, key in removals:
                    db.execute("DELETE FROM documents WHERE namespace=? AND id=?", (namespace, key))
                db.commit()

        await self._worker(run)

    async def clear(self):
        await self._query("DELETE FROM documents")
