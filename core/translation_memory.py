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
from typing import Optional

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
