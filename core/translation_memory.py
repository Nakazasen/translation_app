"""
Translation Memory and Segment Cache using SQLite
=================================================
Manages exact match caching of translated text segments, preserving
formatting and minimizing redundant API/Google Translate calls.
"""

import os
import sys
import sqlite3
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional, Tuple
from translation_app.core.encoding_utils import safe_read_text, safe_write_text

logger = logging.getLogger(__name__)

def get_tm_db_path() -> Path:
    """Get the correct SQLite DB path for Translation Memory."""
    if getattr(sys, 'frozen', False):
        app_data = os.getenv('APPDATA', os.path.expanduser('~'))
        db_dir = Path(app_data) / 'DichTuDong' / 'data'
    else:
        # Resolve to workspace data directory
        db_dir = Path(__file__).parent.parent / "data"
    
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "translation_memory.sqlite"

def normalize_text(text: str) -> str:
    """Normalize text by collapsing multiple spaces/tabs while preserving newlines."""
    if not text:
        return ""
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines()]
    return "\n".join(lines).strip()

def get_segment_hash(source_lang: str, target_lang: str, text: str) -> str:
    """Calculate SHA-256 hash of normalized text and language pair."""
    normalized = normalize_text(text)
    src = (source_lang or "").strip().lower()
    tgt = (target_lang or "").strip().lower()
    key = f"{src}:{tgt}:{normalized}"
    return hashlib.sha256(key.encode('utf-8')).hexdigest()

class TranslationMemoryManager:
    """
    Manages Translation Memory (TM) and Segment Cache using SQLite.
    Includes exact match lookup, hit count tracking, and glossary storage.
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path) if db_path else get_tm_db_path()
        self._init_db()
        
    def _init_db(self):
        """Initialize database schemas and create indexes for performance."""
        try:
            self.db_path = Path(self.db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Create segments table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS segments (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_lang TEXT NOT NULL,
                        target_lang TEXT NOT NULL,
                        source_text_hash TEXT NOT NULL,
                        source_text TEXT NOT NULL,
                        translated_text TEXT NOT NULL,
                        provider TEXT,
                        model TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        hit_count INTEGER DEFAULT 0
                    )
                """)
                
                # Create glossary table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS glossary (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_term TEXT NOT NULL,
                        target_term TEXT NOT NULL,
                        source_lang TEXT NOT NULL,
                        target_lang TEXT NOT NULL,
                        domain TEXT,
                        note TEXT,
                        is_active INTEGER DEFAULT 1
                    )
                """)
                
                # Create unique index on segments lookup fields
                cursor.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_segments_lookup 
                    ON segments(source_lang, target_lang, source_text_hash)
                """)
                
                # Create glossary lookup index
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_glossary_lookup 
                    ON glossary(source_lang, target_lang, source_term)
                """)
                
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Error initializing Translation Memory database: {e}")

    def lookup_segment(self, source_lang: str, target_lang: str, text: str) -> Optional[str]:
        """
        Look up an exact segment translation match.
        Increments hit count on match.
        """
        if not text or not text.strip():
            return None
            
        src = (source_lang or "").strip().lower()
        tgt = (target_lang or "").strip().lower()
        text_hash = get_segment_hash(src, tgt, text)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, translated_text, hit_count FROM segments WHERE source_lang = ? AND target_lang = ? AND source_text_hash = ?",
                    (src, tgt, text_hash)
                )
                row = cursor.fetchone()
                if row:
                    segment_id, translated_text, hit_count = row
                    new_hit_count = hit_count + 1
                    
                    # Update hit count and timestamp
                    cursor.execute(
                        "UPDATE segments SET hit_count = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_hit_count, segment_id)
                    )
                    conn.commit()
                    
                    # Logging privacy: Log only hash/length, no sensitive text
                    logger.info(f"🔑 TM Hit: hash={text_hash[:8]}..., len={len(text)} chars, hits={new_hit_count}")
                    return translated_text
        except Exception as e:
            logger.error(f"❌ TM Lookup failed: {e}")
            
        return None

    def save_segment(self, source_lang: str, target_lang: str, text: str, translated_text: str, provider: Optional[str] = None, model: Optional[str] = None) -> bool:
        """
        Save a translated segment to TM database.
        Skips caching failures/errors.
        """
        # Validate input
        if not text or not text.strip() or not translated_text or not translated_text.strip():
            return False
            
        # Reject obvious errors / exceptions
        err_keywords = ["translation failed", "error:", "exception:", "timeout", "failed to translate"]
        translated_lower = translated_text.lower()
        if any(kw in translated_lower for kw in err_keywords):
            logger.warning(f"⚠️ TM Save skipped: Detected error string in translation")
            return False
            
        src = (source_lang or "").strip().lower()
        tgt = (target_lang or "").strip().lower()
        text_hash = get_segment_hash(src, tgt, text)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Check for existing record
                cursor.execute(
                    "SELECT id FROM segments WHERE source_lang = ? AND target_lang = ? AND source_text_hash = ?",
                    (src, tgt, text_hash)
                )
                row = cursor.fetchone()
                if row:
                    segment_id = row[0]
                    # Update existing record
                    cursor.execute(
                        "UPDATE segments SET source_text = ?, translated_text = ?, provider = ?, model = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (text, translated_text, provider or "unknown", model or "unknown", segment_id)
                    )
                else:
                    # Insert new record
                    cursor.execute(
                        "INSERT INTO segments (source_lang, target_lang, source_text_hash, source_text, translated_text, provider, model) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (src, tgt, text_hash, text, translated_text, provider or "unknown", model or "unknown")
                    )
                conn.commit()
                # Logging privacy: Log only hash/length, no sensitive text
                logger.info(f"💾 TM Saved: hash={text_hash[:8]}..., len={len(text)} chars, provider={provider or 'unknown'}, model={model or 'unknown'}")
                return True
        except Exception as e:
            logger.error(f"❌ TM Save failed: {e}")
            
        return False

    def search_segments(self, query: str = "", source_lang: Optional[str] = None, target_lang: Optional[str] = None, limit: int = 100) -> list[dict]:
        """
        Search segments in the translation memory database.
        Returns preview-safe dictionary list.
        """
        sql = "SELECT id, source_lang, target_lang, source_text, translated_text, provider, model, hit_count, updated_at FROM segments WHERE 1=1"
        params = []
        
        if query:
            sql += " AND (source_text LIKE ? OR translated_text LIKE ?)"
            params.append(f"%{query}%")
            params.append(f"%{query}%")
        if source_lang and source_lang.lower() != 'auto':
            sql += " AND source_lang = ?"
            params.append(source_lang.strip().lower())
        if target_lang:
            sql += " AND target_lang = ?"
            params.append(target_lang.strip().lower())
            
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        
        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                for r in rows:
                    results.append({
                        "id": r[0],
                        "source_lang": r[1],
                        "target_lang": r[2],
                        "source_text": r[3],
                        "translated_text": r[4],
                        "provider": r[5],
                        "model": r[6],
                        "hit_count": r[7],
                        "updated_at": r[8]
                    })
        except Exception as e:
            logger.error(f"❌ Failed to search TM segments: {e}")
        return results

    def delete_segment(self, segment_id: int) -> bool:
        """Delete a segment from the translation memory by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"💾 TM Segment Removed: id={segment_id}")
                    return True
        except Exception as e:
            logger.error(f"❌ Failed to delete TM segment: {e}")
        return False

    def get_segment(self, segment_id: int) -> Optional[dict]:
        """Get a single TM segment by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, source_lang, target_lang, source_text, translated_text, provider, model, hit_count, updated_at FROM segments WHERE id = ?",
                    (segment_id,)
                )
                r = cursor.fetchone()
                if r:
                    return {
                        "id": r[0],
                        "source_lang": r[1],
                        "target_lang": r[2],
                        "source_text": r[3],
                        "translated_text": r[4],
                        "provider": r[5],
                        "model": r[6],
                        "hit_count": r[7],
                        "updated_at": r[8]
                    }
        except Exception as e:
            logger.error(f"❌ Failed to get TM segment: {e}")
        return None

    # =========================================================================
    # GLOSSARY MANAGEMENT APIs
    # =========================================================================
    
    def add_glossary_term(self, source_term: str, target_term: str, source_lang: str, target_lang: str, domain: str = "", note: str = "", is_active: bool = True) -> Optional[int]:
        """
        Add a new term to the glossary.
        Returns the inserted term_id.
        """
        if not source_term or not source_term.strip() or not target_term or not target_term.strip():
            return None
            
        src = (source_lang or "").strip().lower()
        tgt = (target_lang or "").strip().lower()
        active_val = 1 if is_active else 0
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO glossary (source_term, target_term, source_lang, target_lang, domain, note, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source_term.strip(), target_term.strip(), src, tgt, (domain or "").strip(), (note or "").strip(), active_val)
                )
                conn.commit()
                term_id = cursor.lastrowid
                logger.info(
                    f"📋 Glossary Added: id={term_id}, {src}->{tgt}, "
                    f"source_len={len(source_term.strip())}, target_len={len(target_term.strip())}"
                )
                return term_id
        except Exception as e:
            logger.error(f"❌ Failed to add glossary term: {e}")
        return None

    def remove_glossary_term(self, term_id: int) -> bool:
        """Remove a term from the glossary by ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM glossary WHERE id = ?", (term_id,))
                conn.commit()
                changes = conn.total_changes
                if changes > 0:
                    logger.info(f"📋 Glossary Removed: id={term_id}")
                    return True
        except Exception as e:
            logger.error(f"❌ Failed to remove glossary term: {e}")
        return False

    def update_glossary_term(self, term_id: int, source_term: Optional[str] = None, target_term: Optional[str] = None, source_lang: Optional[str] = None, target_lang: Optional[str] = None, domain: Optional[str] = None, note: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
        """Update fields of an existing glossary term."""
        updates = []
        params = []
        
        if source_term is not None:
            updates.append("source_term = ?")
            params.append(source_term.strip())
        if target_term is not None:
            updates.append("target_term = ?")
            params.append(target_term.strip())
        if source_lang is not None:
            updates.append("source_lang = ?")
            params.append(source_lang.strip().lower())
        if target_lang is not None:
            updates.append("target_lang = ?")
            params.append(target_lang.strip().lower())
        if domain is not None:
            updates.append("domain = ?")
            params.append(domain.strip())
        if note is not None:
            updates.append("note = ?")
            params.append(note.strip())
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
            
        if not updates:
            return False
            
        params.append(term_id)
        query = f"UPDATE glossary SET {', '.join(updates)} WHERE id = ?"
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                if cursor.rowcount > 0:
                    logger.info(f"📋 Glossary Updated: id={term_id}")
                    return True
        except Exception as e:
            logger.error(f"❌ Failed to update glossary term: {e}")
        return False

    def list_glossary_terms(self, source_lang: Optional[str] = None, target_lang: Optional[str] = None, domain: Optional[str] = None, active_only: bool = True) -> list[dict]:
        """
        List all glossary terms with filtering options.
        Sorted by source_term length descending to prioritize longer matches.
        """
        query = "SELECT id, source_term, target_term, source_lang, target_lang, domain, note, is_active FROM glossary WHERE 1=1"
        params = []
        
        if active_only:
            query += " AND is_active = 1"
        if source_lang and source_lang.lower() != 'auto':
            query += " AND source_lang = ?"
            params.append(source_lang.strip().lower())
        if target_lang:
            query += " AND target_lang = ?"
            params.append(target_lang.strip().lower())
        if domain:
            query += " AND domain = ?"
            params.append(domain.strip())
            
        query += " ORDER BY length(source_term) DESC"
        
        results = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                for r in rows:
                    results.append({
                        "id": r[0],
                        "source_term": r[1],
                        "target_term": r[2],
                        "source_lang": r[3],
                        "target_lang": r[4],
                        "domain": r[5],
                        "note": r[6],
                        "is_active": bool(r[7])
                    })
        except Exception as e:
            logger.error(f"❌ Failed to list glossary terms: {e}")
            
        return results

    def find_relevant_terms(self, text: str, source_lang: str, target_lang: str, max_terms: int = 20) -> list[dict]:
        """
        Find active glossary terms that appear in the normalized text.
        Does not log raw text to maintain privacy.
        """
        if not text or not text.strip():
            return []
            
        normalized_text = normalize_text(text)
        text_lower = normalized_text.lower()
        
        # If source_lang is auto, we list matching target_lang terms for all source languages
        terms = self.list_glossary_terms(
            source_lang=source_lang if source_lang.lower() != 'auto' else None,
            target_lang=target_lang,
            active_only=True
        )
        
        relevant = []
        for term in terms:
            term_src = term["source_term"]
            if not term_src or not term_src.strip():
                continue
                
            # Perform case-insensitive substring match
            if term_src.lower() in text_lower:
                relevant.append(term)
                if len(relevant) >= max_terms:
                    break
                    
        # Log matching metrics for privacy, no raw strings
        if relevant:
            logger.info(f"📋 Glossary Matched: {len(relevant)} terms found in segment (len={len(text)} chars)")
            
        return relevant

    # =========================================================================
    # CSV IMPORT / EXPORT APIs
    # =========================================================================

    def import_glossary_csv(self, csv_path: str) -> Tuple[int, int]:
        """
        Import glossary terms from a CSV file.
        Returns: (success_count, fail_count)
        """
        import csv
        import io
        success_count = 0
        fail_count = 0
        
        if not os.path.exists(csv_path):
            logger.error(f"❌ CSV file not found: {csv_path}")
            return 0, 0
            
        try:
            # Read safely via our encoding utilities
            content = safe_read_text(csv_path)
            f = io.StringIO(content)
            reader = csv.DictReader(f)
            headers = {h.strip().lower(): h for h in reader.fieldnames or []}
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for row in reader:
                    try:
                        # Map columns case-insensitively with defaults
                        source_term = row.get(headers.get('source_term', 'source_term'), '').strip()
                        target_term = row.get(headers.get('target_term', 'target_term'), '').strip()
                        source_lang = row.get(headers.get('source_lang', 'source_lang'), '').strip().lower()
                        target_lang = row.get(headers.get('target_lang', 'target_lang'), '').strip().lower()
                        domain = row.get(headers.get('domain', 'domain'), '').strip()
                        note = row.get(headers.get('note', 'note'), '').strip()
                        
                        is_active_val = row.get(headers.get('is_active', 'is_active'), '1').strip().lower()
                        is_active = 0 if is_active_val in ('0', 'false', 'no', 'f') else 1
                        
                        if not source_term or not target_term or not source_lang or not target_lang:
                            fail_count += 1
                            continue
                            
                        cursor.execute(
                            """
                            INSERT INTO glossary (source_term, target_term, source_lang, target_lang, domain, note, is_active)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (source_term, target_term, source_lang, target_lang, domain, note, is_active)
                        )
                        success_count += 1
                    except Exception as row_err:
                        logger.error(f"Error importing row {row}: {row_err}")
                        fail_count += 1
                conn.commit()
            logger.info(f"📋 Glossary Import complete: {success_count} success, {fail_count} failed")
        except Exception as e:
            logger.error(f"❌ Failed to import glossary CSV: {e}")
            
        return success_count, fail_count

    def export_glossary_csv(self, csv_path: str) -> bool:
        """
        Export glossary terms from database to a CSV file.
        """
        import csv
        import io
        try:
            terms = self.list_glossary_terms(active_only=False)
            f = io.StringIO()
            writer = csv.writer(f, lineterminator='\n')
            # Write header
            writer.writerow(['source_term', 'target_term', 'source_lang', 'target_lang', 'domain', 'note', 'is_active'])
            for term in terms:
                writer.writerow([
                    term['source_term'],
                    term['target_term'],
                    term['source_lang'],
                    term['target_lang'],
                    term['domain'],
                    term['note'],
                    1 if term['is_active'] else 0
                ])
            
            # Write safely via our encoding utilities
            safe_write_text(csv_path, f.getvalue())
            logger.info(f"📋 Glossary Export complete: saved {len(terms)} terms to {csv_path}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to export glossary CSV: {e}")
            return False


# Global TranslationMemoryManager instance
_tm_manager: Optional[TranslationMemoryManager] = None

def get_tm_manager(db_path: Optional[str] = None) -> TranslationMemoryManager:
    """Get or create the global Translation Memory manager instance."""
    global _tm_manager
    if _tm_manager is None:
        _tm_manager = TranslationMemoryManager(db_path)
    elif db_path:
        _tm_manager.db_path = Path(db_path)
        _tm_manager._init_db()
    return _tm_manager
