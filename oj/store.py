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

    async def _query(self, sql, args=(), *, fetch=None):
        def run():
            with sqlite3.connect(self.path, timeout=15) as db:
                cursor = db.execute(sql, args)
                if fetch == "one":
                    row = cursor.fetchone()
                    return json.loads(row[0]) if row else None
                if fetch == "all":
                    return [json.loads(row[0]) for row in cursor.fetchall()]

        worker = asyncio.create_task(asyncio.to_thread(run))
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

    async def clear(self):
        await self._query("DELETE FROM documents")
