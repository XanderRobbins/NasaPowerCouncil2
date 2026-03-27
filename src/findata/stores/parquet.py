"""L3 DuckDB + Parquet historical storage backend.

Requires: pip install findata[duckdb]

Historical price data is stored as per-symbol Parquet files under
``~/.findata/data/prices/{symbol}.parquet``.  DuckDB reads Parquet directly
with predicate pushdown, making queries over 20 years of daily data fast.

An incremental sync manager tracks ``last_fetched_date`` per symbol in a
SQLite metadata database, so only new data is requested from APIs.
"""

from __future__ import annotations

import pathlib
import sqlite3
from datetime import date
from typing import Any

_DEFAULT_DIR = pathlib.Path.home() / ".findata" / "data"
_META_DB = pathlib.Path.home() / ".findata" / "meta.sqlite3"


class ParquetStore:
    """Store and query price history as Parquet files via DuckDB.

    Parameters
    ----------
    data_dir:
        Root directory for Parquet files.  Defaults to ``~/.findata/data``.
    meta_db:
        SQLite path for tracking sync state.  Defaults to ``~/.findata/meta.sqlite3``.
    """

    def __init__(
        self,
        data_dir: pathlib.Path | str | None = None,
        meta_db: pathlib.Path | str | None = None,
    ) -> None:
        try:
            import duckdb  # type: ignore[import-untyped]
            import pyarrow  # noqa: F401  # type: ignore[import-untyped]
        except ImportError:
            from findata.exceptions import MissingDependencyError
            raise MissingDependencyError("duckdb", "duckdb") from None

        self._data_dir = pathlib.Path(data_dir or _DEFAULT_DIR)
        self._meta_db_path = pathlib.Path(meta_db or _META_DB)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._meta_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._duckdb = duckdb
        self._init_meta()

    # ── Public API ────────────────────────────────────────────────────────────

    def read(self, symbol: str, *, start: date | None = None, end: date | None = None) -> Any:
        """Read price history for *symbol* as a pandas DataFrame.

        Uses DuckDB predicate pushdown on the Parquet file for efficiency.
        Returns an empty DataFrame if no data is stored.
        """
        import pandas as pd  # already in core deps

        path = self._parquet_path(symbol)
        if not path.exists():
            return pd.DataFrame()

        query = f"SELECT * FROM read_parquet('{path}')"
        filters = []
        if start:
            filters.append(f"timestamp >= '{start}'")
        if end:
            filters.append(f"timestamp <= '{end}'")
        if filters:
            query += " WHERE " + " AND ".join(filters)
        query += " ORDER BY timestamp"

        con = self._duckdb.connect()
        try:
            df = con.execute(query).df()
        finally:
            con.close()

        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp")
        return df

    def write(self, symbol: str, df: Any) -> None:
        """Append or create Parquet data for *symbol*.

        Existing data is merged by timestamp (deduplication) and the result
        is written as a single sorted Parquet file.
        """
        import pandas as pd
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as pq  # type: ignore[import-untyped]

        path = self._parquet_path(symbol)
        new_df = df.copy()
        if new_df.index.name == "timestamp":
            new_df = new_df.reset_index()

        if path.exists():
            existing = pd.read_parquet(path)
            if existing.index.name == "timestamp":
                existing = existing.reset_index()
            combined = pd.concat([existing, new_df], ignore_index=True)
        else:
            combined = new_df

        combined = combined.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
        table = pa.Table.from_pandas(combined, preserve_index=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, path, compression="snappy")

    def last_date(self, symbol: str) -> date | None:
        """Return the most recent date stored for *symbol*, or None."""
        with sqlite3.connect(self._meta_db_path) as con:
            row = con.execute(
                "SELECT last_date FROM sync_meta WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if row and row[0]:
            return date.fromisoformat(row[0])
        return None

    def update_last_date(self, symbol: str, d: date) -> None:
        with sqlite3.connect(self._meta_db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO sync_meta (symbol, last_date) VALUES (?, ?)",
                (symbol.upper(), d.isoformat()),
            )
            con.commit()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _parquet_path(self, symbol: str) -> pathlib.Path:
        safe = symbol.upper().replace("/", "_").replace(":", "_")
        return self._data_dir / "prices" / f"{safe}.parquet"

    def _init_meta(self) -> None:
        with sqlite3.connect(self._meta_db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_meta (
                    symbol   TEXT PRIMARY KEY,
                    last_date TEXT
                )
                """
            )
            con.commit()
