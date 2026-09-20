import sqlite3
import os
import json
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "gallery.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=60.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000") # 64MB cache
        conn.execute("PRAGMA wal_autocheckpoint=500")
    except Exception:
        pass
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # Core media metadata table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS media (
        path TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        ext TEXT NOT NULL,
        size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        width INTEGER DEFAULT 0,
        height INTEGER DEFAULT 0,
        aspect_ratio REAL DEFAULT 1.0,
        megapixels REAL DEFAULT 0.0,
        sharpness REAL DEFAULT 0.0,
        dominant_hex TEXT DEFAULT '#000000',
        dominant_hue REAL DEFAULT 0.0,
        is_dark INTEGER DEFAULT 1,
        rating TEXT DEFAULT 'general',
        character_count TEXT DEFAULT 'solo',
        hour INTEGER DEFAULT 0,
        day_of_week INTEGER DEFAULT 0,
        tags_json TEXT DEFAULT '[]',
        tag_scores_json TEXT DEFAULT '{}',
        indexed_at REAL DEFAULT 0,
        dhash TEXT DEFAULT '',
        is_favorite INTEGER DEFAULT 0,
        aspect_category TEXT DEFAULT 'portrait',
        quality_tier TEXT DEFAULT 'hd',
        caption TEXT DEFAULT '',
        caption_model TEXT DEFAULT '',
        captioned_at REAL DEFAULT 0,
        title TEXT DEFAULT ''
    )
    """)
    
    # Safe migrations for existing DB
    for col, col_type in [("caption", "TEXT DEFAULT ''"), ("caption_model", "TEXT DEFAULT ''"), ("captioned_at", "REAL DEFAULT 0"), ("title", "TEXT DEFAULT ''")]:
        try:
            cursor.execute(f"ALTER TABLE media ADD COLUMN {col} {col_type}")
        except Exception:
            pass

    # Indices for blazing fast multi-dimensional sorting and filtering
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_mtime ON media(mtime DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_sharpness ON media(sharpness DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_rating ON media(rating)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_char_count ON media(character_count)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_hour ON media(hour)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_hue ON media(dominant_hue)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_is_dark ON media(is_dark)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_dhash ON media(dhash)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_fav ON media(is_favorite)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_aspect ON media(aspect_category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_quality ON media(quality_tier)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_captioned ON media(captioned_at)")
    
    # FTS5 virtual table for full-text search over tags
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS media_tags_fts USING fts5(
        path UNINDEXED,
        tags
    )
    """)

    # FTS5 virtual table for natural language search over AI captions
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS media_caption_fts USING fts5(
        path UNINDEXED,
        caption
    )
    """)
    
    # Tag vocabulary frequency cache
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tag_frequencies (
        tag TEXT PRIMARY KEY,
        category TEXT,
        count INTEGER DEFAULT 0
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tag_freq_count ON tag_frequencies(count DESC)")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)
