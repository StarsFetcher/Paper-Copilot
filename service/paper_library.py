"""
Paper Library Module
====================
SQLite-based metadata database for discovered and analyzed papers.

Stores: paper_id, title, authors, abstract, arxiv_id, url, published_date,
        tags, quality_score, relevance_score, analysis_json, created_at

Provides CRUD operations for the paper collection workflow.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class PaperLibrary:
    """SQLite-backed paper metadata store."""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or settings.PAPER_LIBRARY_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_table()

    # -----------------------------------------------------------------
    # Connection management
    # -----------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _ensure_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS papers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id TEXT UNIQUE NOT NULL,
                title TEXT,
                authors TEXT,
                abstract TEXT,
                arxiv_id TEXT,
                url TEXT,
                published_date TEXT,
                tags TEXT,
                quality_score REAL,
                relevance_score REAL,
                analysis_json TEXT,
                status TEXT DEFAULT 'discovered',
                storage_path TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Gracefully add column for existing databases
        try:
            self.conn.execute("ALTER TABLE papers ADD COLUMN storage_path TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        self.conn.commit()
        logger.info(f"Paper library initialized: {self._db_path}")

    # -----------------------------------------------------------------
    # CRUD operations
    # -----------------------------------------------------------------

    def add_paper(self, paper: Dict[str, Any]) -> bool:
        """
        Add or update a paper in the library.

        Args:
            paper: Dict with keys matching the papers table columns.
                   paper_id is required; all others optional.

        Returns:
            True if inserted, False if updated
        """
        paper_id = paper.get("paper_id") or paper.get("arxiv_id")
        if not paper_id:
            raise ValueError("paper_id or arxiv_id is required")

        # Serialize complex fields
        if isinstance(paper.get("tags"), list):
            paper["tags"] = json.dumps(paper["tags"], ensure_ascii=False)
        if isinstance(paper.get("analysis_json"), dict):
            paper["analysis_json"] = json.dumps(
                paper["analysis_json"], ensure_ascii=False,
            )

        existing = self.get_paper(paper_id)
        if existing:
            # Update
            updates = []
            values = []
            for key in ["title", "authors", "abstract", "arxiv_id", "url",
                        "published_date", "tags", "quality_score",
                        "relevance_score", "analysis_json", "status",
                        "storage_path"]:
                if key in paper:
                    updates.append(f"{key} = ?")
                    values.append(paper[key])
            if updates:
                updates.append("updated_at = datetime('now')")
                values.append(paper_id)
                self.conn.execute(
                    f"UPDATE papers SET {', '.join(updates)} WHERE paper_id = ?",
                    values,
                )
                self.conn.commit()
            return False
        else:
            # Insert
            self.conn.execute("""
                INSERT INTO papers
                    (paper_id, title, authors, abstract, arxiv_id, url,
                     published_date, tags, quality_score, relevance_score,
                     analysis_json, status, storage_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                paper_id,
                paper.get("title", ""),
                paper.get("authors", ""),
                paper.get("abstract", ""),
                paper.get("arxiv_id", paper_id),
                paper.get("url", ""),
                paper.get("published_date", ""),
                paper.get("tags", "[]"),
                paper.get("quality_score", 0),
                paper.get("relevance_score", 0),
                paper.get("analysis_json", "{}"),
                paper.get("status", "discovered"),
                paper.get("storage_path", ""),
            ))
            self.conn.commit()
            return True

    def get_paper(self, paper_id: str) -> Optional[Dict[str, Any]]:
        """Get a paper by its paper_id."""
        row = self.conn.execute(
            "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_papers(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List papers, optionally filtered by status.

        Args:
            status: Filter by status ('discovered', 'screened', 'analyzed', 'stored')
            limit: Max results
            offset: Pagination offset
        """
        if status:
            rows = self.conn.execute(
                "SELECT * FROM papers WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM papers ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_status(self, paper_id: str, status: str) -> bool:
        """Update paper status."""
        self.conn.execute(
            "UPDATE papers SET status = ?, updated_at = datetime('now') "
            "WHERE paper_id = ?",
            (status, paper_id),
        )
        self.conn.commit()
        return self.conn.total_changes > 0

    def delete_paper(self, paper_id: str) -> bool:
        """
        Delete a paper from the library by paper_id.

        Args:
            paper_id: The unique identifier for the paper

        Returns:
            True if a row was deleted, False if paper_id not found
        """
        self.conn.execute(
            "DELETE FROM papers WHERE paper_id = ?", (paper_id,)
        )
        self.conn.commit()
        deleted = self.conn.total_changes > 0
        if deleted:
            logger.info(f"已从论文库删除: paper_id='{paper_id}'")
        else:
            logger.warning(f"论文不存在，跳过删除: paper_id='{paper_id}'")
        return deleted

    def update_analysis(
        self, paper_id: str, analysis: Dict[str, Any],
    ) -> bool:
        """Store structured analysis results for a paper."""
        self.conn.execute(
            "UPDATE papers SET analysis_json = ?, status = 'analyzed', "
            "updated_at = datetime('now') WHERE paper_id = ?",
            (json.dumps(analysis, ensure_ascii=False), paper_id),
        )
        self.conn.commit()
        return self.conn.total_changes > 0

    def count(self, status: Optional[str] = None) -> int:
        """Count papers, optionally by status."""
        if status:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM papers WHERE status = ?",
                (status,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM papers",
            ).fetchone()
        return row["cnt"] if row else 0

    def search_by_title(self, keyword: str, limit: int = 20) -> List[Dict]:
        """Full-text search by title keyword."""
        rows = self.conn.execute(
            "SELECT * FROM papers WHERE title LIKE ? LIMIT ?",
            (f"%{keyword}%", limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        # Deserialize JSON fields
        for field in ["tags", "analysis_json"]:
            if field in d and isinstance(d[field], str):
                try:
                    d[field] = json.loads(d[field])
                except json.JSONDecodeError:
                    pass
        return d

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


# ================================================================
# Global Singleton
# ================================================================

_library_instance: Optional[PaperLibrary] = None


def get_paper_library() -> PaperLibrary:
    global _library_instance
    if _library_instance is None:
        _library_instance = PaperLibrary()
    return _library_instance
