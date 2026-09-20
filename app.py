import os
import io
import json
import random
import mimetypes
import time
import hashlib
import re
from collections import Counter
from datetime import datetime
from flask import Flask, render_template, request, Response, jsonify, send_file
from PIL import Image, ImageOps

from db import get_db, init_db
from scanner import ScannerManager, SUPPORTED_EXTENSIONS

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# Инициализация БД при старте
try:
    init_db()
except Exception:
    pass
scanner_manager = ScannerManager()
CURRENT_BASE_DIR = r"C:\Users\Admin\Pictures\Amazing Stray 3.4 final"
try:
    scanner_manager.start(directory=CURRENT_BASE_DIR)
except Exception:
    pass

_captioner_started = False

def ensure_captioner_started():
    global _captioner_started
    if not _captioner_started:
        _captioner_started = True
        try:
            import captioner
            started = captioner.start_captioner()
            if started:
                print("[SERVER] Florence-2 auto-captioner background worker started automatically.")
        except Exception as e:
            print("[SERVER] Could not auto-start captioner:", e)

# Unconditionally ensure captioner runs 24/7
ensure_captioner_started()

BACKGROUND_AUDIO = "bg_audio.mp3"

ALLOWED_EXTENSIONS = SUPPORTED_EXTENSIONS
mimetypes.add_type('video/webm', '.webm')
mimetypes.add_type('video/mp4', '.mp4')

def detect_media_group(filename: str) -> dict:
    """Определяет группу медиа (Pixiv multi-page, Manga/CG series, Booru) и номер страницы"""
    name_no_ext, ext = os.path.splitext(filename)
    
    # 1. Pixiv multi-page pattern: e.g. 100261801_p0_master1200, 100340305_p1-School Wolf, 102213410-hash_p10_master1200
    m_pixiv = re.search(r'(?:^|[\s_-])(?:illust_)?(\d{6,12})(?:-[a-f0-9]+)?_p(\d+)(?:[_\-](.+))?$', name_no_ext, re.IGNORECASE)
    if not m_pixiv:
        m_pixiv = re.search(r'^(.+?)_p(\d+)(?:[_\-](.+))?$', name_no_ext, re.IGNORECASE)
        
    if m_pixiv:
        illust_id = m_pixiv.group(1)
        page = int(m_pixiv.group(2))
        sub = m_pixiv.group(3) or ""
        sub_clean = re.sub(r'(?:master|square|custom)?\d+$', '', sub).strip(' _-')
        return {
            "group_type": "pixiv",
            "group_id": f"pixiv_{illust_id}",
            "raw_id": illust_id,
            "page": page,
            "sub": sub_clean,
            "label": f"Pixiv #{illust_id} (p.{page})"
        }

    # 2. Booru post pattern: e.g. yande.re 1015798 animal_ears...
    m_yande = re.match(r'^yande\.re\s+(\d+)\s*(.*)', name_no_ext, re.IGNORECASE)
    if m_yande:
        post_id = m_yande.group(1)
        sub = m_yande.group(2)
        m_page = re.search(r'\s*\((\d+)\)$', sub)
        page = int(m_page.group(1)) if m_page else 0
        return {
            "group_type": "booru",
            "group_id": f"yandere_{post_id}",
            "raw_id": post_id,
            "page": page,
            "sub": sub,
            "label": f"Yande.re #{post_id}"
        }

    # 3. Numbered manga / comic / CG series: e.g. "Title - 01", "Page (2)", "Chapter 03"
    m_series = re.match(r'^(.*?)(?:[ _\-\(\[\{]+)(\d{1,4})(?:[ _\-\)\]\}]*)$', name_no_ext)
    if m_series:
        prefix = m_series.group(1).strip(' _-')
        page = int(m_series.group(2))
        if len(prefix) >= 3 and not prefix.isdigit() and prefix.lower() not in ('sample', 'image', 'img', 'photo', 'picture', 'file', 'download'):
            return {
                "group_type": "series",
                "group_id": f"series_{prefix.lower()}",
                "raw_id": prefix,
                "page": page,
                "sub": "",
                "label": f"{prefix} (#{page})"
            }

    return {
        "group_type": "single",
        "group_id": None,
        "raw_id": None,
        "page": 0,
        "sub": "",
        "label": ""
    }

def fast_scan(directory):
    """Сверхбыстрое сканирование директории с кэшированием дат (Enterprise-level)"""
    files_data = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    files_data.extend(fast_scan(entry.path))
                elif entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in ALLOWED_EXTENSIONS:
                        stat = entry.stat()
                        files_data.append({
                            "path": entry.path,
                            "name": entry.name,
                            "ext": ext,
                            "time": stat.st_mtime,
                            "size": stat.st_size,
                            "sharpness": 0,
                            "dominant_hex": "#1a1a1a",
                            "tags": []
                        })
    except Exception:
        pass
    return files_data

def get_subfolders(base_path):
    folders = ["Все медиа"]
    try:
        with os.scandir(base_path) as it:
            for entry in it:
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append(entry.name)
    except Exception:
        pass
    return folders

def build_media_query(args):
    """Строит динамический SQL запрос для многомерной фильтрации"""
    conditions = []
    params = []
    
    tags = args.get('tags', '').strip()
    if tags:
        raw_tokens = [t.strip().replace(' ', '_') for t in tags.split(',') if t.strip()]
        pos_tags = []
        neg_tags = []
        cyrillic_terms = []
        for t in raw_tokens:
            if re.search(r'[\u0400-\u04FF]', t):
                cyrillic_terms.append(t.replace('_', ' ').lstrip('-'))
            elif t.startswith('-') and len(t) > 1:
                neg_tags.append(t[1:].replace('"', ''))
            else:
                pos_tags.append(t.replace('"', ''))
                
        if pos_tags:
            pos_query = " ".join([f'"{pt}"' for pt in pos_tags])
            conditions.append("media.path IN (SELECT path FROM media_tags_fts WHERE tags MATCH ?)")
            params.append(pos_query)

        if neg_tags:
            neg_query = " OR ".join([f'"{nt}"' for nt in neg_tags])
            conditions.append("media.path NOT IN (SELECT path FROM media_tags_fts WHERE tags MATCH ?)")
            params.append(neg_query)

        if cyrillic_terms:
            for term in cyrillic_terms:
                c_tokens = [w for w in term.replace('"', '').split() if w]
                if c_tokens:
                    c_fts = " AND ".join([f'"{w}"*' for w in c_tokens])
                    conditions.append("""(
                        media.path IN (SELECT path FROM media_caption_fts WHERE caption MATCH ?)
                        OR media.title LIKE ?
                        OR media.caption LIKE ?
                    )""")
                    params.extend([c_fts, f"%{term}%", f"%{term}%"])

    # Поиск по AI названию и описанию (FTS5 + LIKE)
    caption_q = args.get('caption', '').strip()
    if caption_q:
        clean_tokens = [t for t in caption_q.replace('"', '').split() if t]
        if clean_tokens:
            fts_query = " AND ".join([f'"{t}"*' for t in clean_tokens])
            conditions.append("""(
                media.path IN (SELECT path FROM media_caption_fts WHERE caption MATCH ?)
                OR media.title LIKE ?
                OR media.caption LIKE ?
            )""")
            params.extend([fts_query, f"%{caption_q}%", f"%{caption_q}%"])

    # Наличие AI описания
    has_caption = args.get('has_caption')
    if has_caption == '1':
        conditions.append("(media.caption IS NOT NULL AND media.caption != '')")
    elif has_caption == '0':
        conditions.append("(media.caption IS NULL OR media.caption = '')")
            
    # Резкость
    min_sharp = args.get('min_sharpness', type=float)
    if min_sharp is not None and min_sharp > 0:
        conditions.append("media.sharpness >= ?")
        params.append(min_sharp)
        
    # Тёмное / Светлое
    is_dark = args.get('is_dark')
    if is_dark in ('0', '1'):
        conditions.append("media.is_dark = ?")
        params.append(int(is_dark))
        
    # Цветовой оттенок (Hue 0..360)
    hue_preset = args.get('hue')
    if hue_preset:
        hue_ranges = {
            'red': [(0, 25), (335, 360)],
            'orange': [(25, 45)],
            'yellow': [(45, 75)],
            'green': [(75, 160)],
            'cyan': [(160, 200)],
            'blue': [(200, 255)],
            'purple': [(255, 295)],
            'pink': [(295, 335)]
        }
        ranges = hue_ranges.get(hue_preset.lower())
        if ranges:
            range_clauses = []
            for low, high in ranges:
                range_clauses.append("(media.dominant_hue >= ? AND media.dominant_hue <= ?)")
                params.extend([low, high])
            conditions.append("(" + " OR ".join(range_clauses) + ")")
            
    # Число персонажей
    char_count = args.get('character_count')
    if char_count and char_count != 'all':
        conditions.append("media.character_count = ?")
        params.append(char_count)
        
    # Рейтинг
    rating = args.get('rating')
    if rating and rating != 'all':
        conditions.append("media.rating = ?")
        params.append(rating)
        
    # Время суток (Циркадный фильтр)
    hour_slot = args.get('time_slot')
    if hour_slot:
        slots = {
            'night': (0, 5),
            'morning': (6, 11),
            'day': (12, 17),
            'evening': (18, 23)
        }
        if hour_slot in slots:
            h_start, h_end = slots[hour_slot]
            conditions.append("media.hour >= ? AND media.hour <= ?")
            params.extend([h_start, h_end])
            
    # Пропорции (Aspect category)
    aspect = args.get('aspect')
    if aspect and aspect != 'all':
        conditions.append("media.aspect_category = ?")
        params.append(aspect)

    # Уровень качества (Quality tier: 4k, fhd, hd, sd)
    quality = args.get('quality')
    if quality and quality != 'all':
        conditions.append("media.quality_tier = ?")
        params.append(quality)

    # Избранное (Favorites)
    fav = args.get('favorite')
    if fav in ('1', 'true'):
        conditions.append("media.is_favorite = 1")

    # Тип файла (фото/видео)
    media_type = args.get('type')
    if media_type == 'video':
        conditions.append("media.ext IN ('.mp4', '.webm', '.mkv', '.avi')")
    elif media_type == 'image':
        conditions.append("media.ext NOT IN ('.mp4', '.webm', '.mkv', '.avi')")

    # Группировка по альбомам Pixiv / Сериям
    group_filter = args.get('group')
    if group_filter == 'pixiv':
        conditions.append("media.name LIKE '%/_p%' ESCAPE '/'")
    elif group_filter == 'series':
        conditions.append("(media.name NOT LIKE '%/_p%' ESCAPE '/' AND (media.name LIKE '% 01.%' OR media.name LIKE '% 02.%' OR media.name LIKE '%_01.%' OR media.name LIKE '%_02.%' OR media.name LIKE '% (1).%' OR media.name LIKE '% (2).%'))")
    elif group_filter == 'multi':
        conditions.append("(media.name LIKE '%/_p%' ESCAPE '/' OR media.name LIKE '% (1).%' OR media.name LIKE '% (2).%' OR media.name LIKE '% 01.%')")

    # Прямой поиск альбома Pixiv по ID (например pixiv:100261801)
    pixiv_id = args.get('pixiv_id')
    if pixiv_id:
        conditions.append("media.name LIKE ? ESCAPE '/'")
        params.append(f"%{pixiv_id}%/_p%")
        
    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_clause, params

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config')
def api_config():
    global CURRENT_BASE_DIR
    conn = get_db()
    indexed_count = 0
    tag_count = 0
    fav_count = 0
    try:
        indexed_count = conn.execute("SELECT count(*) FROM media").fetchone()[0]
        tag_count = conn.execute("SELECT count(*) FROM tag_frequencies").fetchone()[0]
        fav_count = conn.execute("SELECT count(*) FROM media WHERE is_favorite = 1").fetchone()[0]
    except Exception:
        pass
    finally:
        conn.close()

    return jsonify({
        "current_dir": CURRENT_BASE_DIR,
        "folders": get_subfolders(CURRENT_BASE_DIR),
        "stats": {
            "indexed_files": indexed_count,
            "unique_tags": tag_count,
            "favorite_files": fav_count
        },
        "scanner": scanner_manager.get_status()
    })

@app.route('/api/change_root', methods=['POST'])
def api_change_root():
    global CURRENT_BASE_DIR
    data = request.json or {}
    new_path = data.get("path", "").strip()
    
    if os.path.exists(new_path) and os.path.isdir(new_path):
        CURRENT_BASE_DIR = new_path
        return jsonify({"success": True, "msg": f"Папка изменена на {new_path}"})
    return jsonify({"success": False, "msg": "Указанный путь не существует или это не папка"}), 400

@app.route('/api/scanner/start', methods=['POST'])
def api_scanner_start():
    batch_size = request.args.get('batch', 20, type=int)
    ok, msg = scanner_manager.start(directory=CURRENT_BASE_DIR, batch_size=batch_size)
    return jsonify({"success": ok, "msg": msg, "status": scanner_manager.get_status()})

@app.route('/api/scanner/stop', methods=['POST'])
def api_scanner_stop():
    ok, msg = scanner_manager.stop()
    return jsonify({"success": ok, "msg": msg, "status": scanner_manager.get_status()})

@app.route('/api/scanner/status')
def api_scanner_status():
    return jsonify(scanner_manager.get_status())

@app.route('/api/tags/suggest')
def api_tags_suggest():
    raw_q = request.args.get('q', '').strip()
    if not raw_q:
        return jsonify([])
        
    conn = get_db()
    results = []
    try:
        cursor = conn.cursor()
        # 1. Если запрос содержит кириллицу - ищем по русским AI названиям и описаниям
        if re.search(r'[\u0400-\u04FF]', raw_q):
            cursor.execute("""
                SELECT title, COUNT(*) as cnt FROM media 
                WHERE title LIKE ? AND title != ''
                GROUP BY title
                ORDER BY cnt DESC LIMIT 10
            """, (f"%{raw_q}%",))
            for r in cursor.fetchall():
                results.append({"tag": r[0], "category": "Title", "count": r[1], "type": "title"})

            if len(results) < 5:
                words = [w for w in raw_q.split() if len(w) >= 2]
                if words:
                    fts_q = " AND ".join([f'"{w}"*' for w in words])
                    try:
                        cursor.execute("""
                            SELECT title, COUNT(*) FROM media
                            WHERE path IN (SELECT path FROM media_caption_fts WHERE caption MATCH ? LIMIT 30)
                              AND title != ''
                            GROUP BY title
                            ORDER BY COUNT(*) DESC LIMIT 8
                        """, (fts_q,))
                        seen = {res["tag"] for res in results}
                        for r in cursor.fetchall():
                            if r[0] and r[0] not in seen:
                                results.append({"tag": r[0], "category": "Caption", "count": r[1], "type": "caption"})
                                seen.add(r[0])
                    except Exception:
                        pass
        # 2. Если запрос - числовой ID альбома Pixiv
        elif raw_q.isdigit() and len(raw_q) >= 4:
            cursor.execute("""
                SELECT name, COUNT(*) FROM media 
                WHERE name LIKE ? 
                GROUP BY substr(name, 1, 35)
                LIMIT 5
            """, (f"%{raw_q}%",))
            for r in cursor.fetchall():
                results.append({"tag": f"pixiv:{raw_q}", "category": "Pixiv", "count": r[1], "type": "pixiv"})
        # 3. Англоязычные теги WD14
        else:
            query = raw_q.lower().replace(' ', '_')
            cursor.execute("""
            SELECT tag, category, count FROM tag_frequencies 
            WHERE tag LIKE ? 
            ORDER BY count DESC LIMIT 15
            """, (f"{query}%",))
            for r in cursor.fetchall():
                results.append({"tag": r[0], "category": r[1], "count": r[2], "type": "tag"})
            if len(results) < 5:
                cursor.execute("""
                SELECT tag, category, count FROM tag_frequencies 
                WHERE tag LIKE ? AND tag NOT LIKE ?
                ORDER BY count DESC LIMIT 10
                """, (f"%_{query}%", f"{query}%"))
                for r in cursor.fetchall():
                    results.append({"tag": r[0], "category": r[1], "count": r[2], "type": "tag"})
    except Exception:
        pass
    finally:
        conn.close()
    return jsonify(results)

@app.route('/api/tags/cloud')
def api_tags_cloud():
    """Возвращает динамическое облако тегов с поддержкой фильтра по категориям"""
    where_clause, params = build_media_query(request.args)
    cat_filter = request.args.get('category', '').strip()
    
    conn = get_db()
    cloud = []
    try:
        cursor = conn.cursor()
        if not where_clause:
            # Общий топ тегов
            if cat_filter and cat_filter != 'all':
                cursor.execute("""
                SELECT tag, category, count FROM tag_frequencies 
                WHERE category = ? 
                ORDER BY count DESC LIMIT 80
                """, (cat_filter,))
            else:
                cursor.execute("""
                SELECT tag, category, count FROM tag_frequencies 
                WHERE category NOT IN ('Meta', 'Rating') 
                ORDER BY count DESC LIMIT 80
                """)
            for r in cursor.fetchall():
                cloud.append({"tag": r[0], "category": r[1], "count": r[2]})
        else:
            # Динамический подсчет по выборке
            cursor.execute(f"SELECT tags_json FROM media {where_clause} LIMIT 250", params)
            counter = Counter()
            for row in cursor.fetchall():
                try:
                    tags = json.loads(row[0])
                    counter.update(tags)
                except Exception:
                    pass
            exclude = {'general', 'sensitive', 'questionable', 'explicit', 'solo', 'duo', 'group'}
            top_common = [(t, c) for t, c in counter.most_common(120) if t not in exclude]
            
            if top_common:
                placeholders = ",".join("?" * len(top_common))
                tag_names = [t[0] for t in top_common]
                cursor.execute(f"SELECT tag, category FROM tag_frequencies WHERE tag IN ({placeholders})", tag_names)
                cat_map = {r[0]: r[1] for r in cursor.fetchall()}
                for t, c in top_common:
                    t_cat = cat_map.get(t, "General")
                    if cat_filter and cat_filter != 'all' and t_cat.lower() != cat_filter.lower():
                        continue
                    cloud.append({"tag": t, "category": t_cat, "count": c})
                    if len(cloud) >= 80:
                        break
    except Exception:
        pass
    finally:
        conn.close()
    return jsonify(cloud)

@app.route('/api/tags/related')
def api_tags_related():
    """Возвращает сопутствующие и семантически похожие теги (со-встречаемость в коллекции)"""
    raw_query = request.args.get('tag', '').strip()
    limit = min(request.args.get('limit', 50, type=int), 100)
    
    if not raw_query:
        return jsonify({"error": "Tag parameter required"}), 400
        
    conn = get_db()
    related = []
    sample_count = 0
    clean_tag = raw_query.lower()
    
    try:
        cursor = conn.cursor()
        
        # 1. Если запрос на русском языке — ищем кадры по полнотекстовому описанию Florence-2
        if re.search(r'[\u0400-\u04FF]', raw_query):
            words = [w for w in raw_query.split() if len(w) >= 2]
            if words:
                fts_q = " AND ".join([f'"{w}"*' for w in words])
                cursor.execute("""
                    SELECT tags_json FROM media 
                    WHERE path IN (SELECT path FROM media_caption_fts WHERE caption MATCH ? LIMIT 350)
                """, (fts_q,))
            else:
                cursor.execute("SELECT tags_json FROM media WHERE title LIKE ? LIMIT 350", (f"%{raw_query}%",))
        else:
            # 2. Англоязычный тег: ищем варианты с подчеркиванием и пробелом
            t_under = clean_tag.replace(' ', '_')
            t_space = clean_tag.replace('_', ' ')
            cursor.execute("""
                SELECT tags_json FROM media 
                WHERE tags_json LIKE ? OR tags_json LIKE ? 
                LIMIT 350
            """, (f'%"{t_under}"%', f'%"{t_space}"%'))
            
        counter = Counter()
        rows = cursor.fetchall()
        sample_count = len(rows)
        
        ignore_tags = {
            clean_tag, clean_tag.replace(' ', '_'), clean_tag.replace('_', ' '),
            'general', 'sensitive', 'questionable', 'explicit',
            'highres', 'absurdres', 'lowres', 'bad quality', 'normal quality'
        }
        
        for row in rows:
            try:
                tags = json.loads(row[0])
                for t in tags:
                    t_norm = t.lower()
                    if t_norm not in ignore_tags:
                        counter[t] += 1
            except Exception:
                pass
                
        most_common = counter.most_common(limit)
        if most_common:
            placeholders = ",".join("?" * len(most_common))
            tag_names = [t[0] for t in most_common]
            cursor.execute(f"SELECT tag, category, count FROM tag_frequencies WHERE tag IN ({placeholders})", tag_names)
            meta_map = {r[0]: {"category": r[1], "global_count": r[2]} for r in cursor.fetchall()}
            
            for t, co_cnt in most_common:
                meta = meta_map.get(t, {"category": "General", "global_count": co_cnt})
                corr_pct = round((co_cnt / max(sample_count, 1)) * 100, 1)
                related.append({
                    "tag": t,
                    "category": meta["category"],
                    "co_occurrence": co_cnt,
                    "global_count": meta["global_count"],
                    "correlation_pct": corr_pct
                })
                
        by_cat = {}
        for item in related:
            c_name = item["category"]
            if c_name not in by_cat:
                by_cat[c_name] = []
            by_cat[c_name].append(item)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
        
    return jsonify({
        "query": raw_query,
        "sample_count": sample_count,
        "related": related,
        "by_category": by_cat
    })

@app.route('/api/tags/gems')
def api_tags_gems():
    """Возвращает скрытые жемчужины: выразительные, интересные теги со средней частотой (самородки)"""
    conn = get_db()
    gems = []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tag, category, count FROM tag_frequencies 
            WHERE category IN ('Character', 'General') 
              AND count BETWEEN 8 AND 1500
              AND tag NOT LIKE '%quality%' AND tag NOT LIKE '%res%' AND tag NOT LIKE '%censor%'
            ORDER BY RANDOM() LIMIT 50
        """)
        for r in cursor.fetchall():
            gems.append({"tag": r[0], "category": r[1], "count": r[2]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify(gems)

@app.route('/api/playlist')
def api_playlist():
    where_clause, params = build_media_query(request.args)
    sort_mode = request.args.get('sort', 'newest')
    limit = min(request.args.get('limit', 200, type=int), 1000)
    offset = max(request.args.get('offset', 0, type=int), 0)
    
    order_clause = "ORDER BY media.mtime DESC"
    if sort_mode == "random":
        order_clause = "ORDER BY RANDOM()"
    elif sort_mode == "sharpness":
        order_clause = "ORDER BY media.sharpness DESC"
    elif sort_mode == "megapixels":
        order_clause = "ORDER BY media.megapixels DESC"
    elif sort_mode == "hue":
        order_clause = "ORDER BY media.dominant_hue ASC"
    elif sort_mode == "oldest":
        order_clause = "ORDER BY media.mtime ASC"
    elif sort_mode == "az":
        order_clause = "ORDER BY media.name ASC"
    elif sort_mode == "captioned":
        order_clause = "ORDER BY (media.caption IS NOT NULL AND media.caption != '') DESC, media.captioned_at DESC, media.mtime DESC"
    elif sort_mode == "title":
        order_clause = "ORDER BY (media.title IS NOT NULL AND media.title != '') DESC, media.title ASC, media.name ASC"
    elif sort_mode == "pixiv":
        order_clause = "ORDER BY (media.name LIKE '%/_p%' ESCAPE '/') DESC, media.name ASC"

    conn = get_db()
    total = 0
    items = []
    
    try:
        cursor = conn.cursor()
        # Общий счетчик для пагинации
        count_query = f"SELECT count(*) FROM media {where_clause}"
        total = cursor.execute(count_query, params).fetchone()[0]
        
        # Если база пустая или еще не проиндексирована, fallback на быстрый скан папки
        if total == 0 and not where_clause:
            media_files = fast_scan(CURRENT_BASE_DIR)
            if sort_mode == "random":
                random.shuffle(media_files)
            elif sort_mode == "newest":
                media_files.sort(key=lambda x: x["time"], reverse=True)
            elif sort_mode == "oldest":
                media_files.sort(key=lambda x: x["time"])
            elif sort_mode == "az":
                media_files.sort(key=lambda x: x["name"].lower())
            return jsonify({
                "total": len(media_files),
                "items": media_files[offset:offset+limit],
                "from_db": False
            })

        # Основной запрос
        data_query = f"""
        SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
               sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
               hour, tags_json, is_favorite, aspect_category, quality_tier, dhash, caption, title
        FROM media {where_clause} {order_clause} LIMIT ? OFFSET ?
        """
        cursor.execute(data_query, params + [limit, offset])
        for row in cursor.fetchall():
            tags_preview = []
            try:
                full_tags = json.loads(row[16])
                tags_preview = full_tags[:12] # Первые 12 тегов для превью карточки
            except Exception:
                pass
                
            item_group = detect_media_group(row[1])
            items.append({
                "path": row[0],
                "name": row[1],
                "ext": row[2],
                "size": row[3],
                "time": row[4],
                "width": row[5],
                "height": row[6],
                "aspect_ratio": row[7],
                "megapixels": row[8],
                "sharpness": row[9],
                "dominant_hex": row[10],
                "dominant_hue": row[11],
                "is_dark": row[12],
                "rating": row[13],
                "character_count": row[14],
                "hour": row[15],
                "tags": tags_preview,
                "is_favorite": row[17] or 0,
                "aspect_category": row[18] or 'portrait',
                "quality_tier": row[19] or 'hd',
                "dhash": row[20] or '',
                "caption": row[21] or '',
                "title": row[22] or '',
                "group_type": item_group["group_type"],
                "group_id": item_group["group_id"],
                "group_raw_id": item_group["raw_id"],
                "group_page": item_group["page"],
                "group_label": item_group["label"]
            })
    except Exception as e:
        print("[API ERROR] /api/playlist:", e)
    finally:
        conn.close()

    return jsonify({
        "total": total,
        "items": items,
        "from_db": True,
        "limit": limit,
        "offset": offset
    })

@app.route('/api/media/details')
def api_media_details():
    filepath = request.args.get('path')
    if not filepath:
        return jsonify({"error": "No path provided"}), 400
        
    conn = get_db()
    detail = None
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
               sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
               hour, day_of_week, tags_json, tag_scores_json, is_favorite,
               aspect_category, quality_tier, dhash, caption, caption_model, captioned_at, title
        FROM media WHERE path = ?
        """, (filepath,))
        row = cursor.fetchone()
        if row:
            tags = json.loads(row[17])
            tag_scores = json.loads(row[18])
            tag_categories = {}
            if tags:
                try:
                    placeholders = ','.join(['?'] * len(tags))
                    cursor.execute(f"SELECT tag, category FROM tag_frequencies WHERE tag IN ({placeholders})", tags)
                    for tr in cursor.fetchall():
                        tag_categories[tr[0]] = tr[1]
                except Exception:
                    pass

            detail = {
                "path": row[0], "name": row[1], "ext": row[2], "size": row[3],
                "mtime": row[4], "width": row[5], "height": row[6], "aspect_ratio": row[7],
                "megapixels": row[8], "sharpness": row[9], "dominant_hex": row[10],
                "dominant_hue": row[11], "is_dark": row[12], "rating": row[13],
                "character_count": row[14], "hour": row[15], "day_of_week": row[16],
                "tags": tags,
                "tag_scores": tag_scores,
                "tag_categories": tag_categories,
                "is_favorite": row[19] or 0,
                "aspect_category": row[20] or 'portrait',
                "quality_tier": row[21] or 'hd',
                "dhash": row[22] or '',
                "caption": row[23] or '',
                "caption_model": row[24] or '',
                "captioned_at": row[25] or 0,
                "title": row[26] or ''
            }
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

    if detail is None:
        return jsonify({"error": "Media not found in DB"}), 404
    return jsonify(detail)

@app.route('/api/media/favorite', methods=['POST'])
def api_media_favorite():
    """Переключает статус 'Избранное' (⭐) для файла"""
    data = request.json or {}
    filepath = data.get('path')
    if not filepath:
        return jsonify({"error": "No path provided"}), 400

    conn = get_db()
    new_status = 0
    try:
        cursor = conn.cursor()
        row = cursor.execute("SELECT is_favorite FROM media WHERE path = ?", (filepath,)).fetchone()
        if row is not None:
            curr = row[0] or 0
            new_status = 1 if curr == 0 else 0
            cursor.execute("UPDATE media SET is_favorite = ? WHERE path = ?", (new_status, filepath))
            conn.commit()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

    return jsonify({"success": True, "path": filepath, "is_favorite": new_status})

@app.route('/api/media/batch_favorite', methods=['POST'])
def api_media_batch_favorite():
    """Пакетная установка статуса 'Избранное' для списка путей"""
    data = request.json or {}
    paths = data.get('paths', [])
    action = data.get('action', 'add')
    if not paths:
        return jsonify({"error": "No paths provided"}), 400
    
    val = 1 if action == 'add' else 0
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.executemany("UPDATE media SET is_favorite = ? WHERE path = ?", [(val, p) for p in paths])
        conn.commit()
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"success": True, "count": len(paths), "is_favorite": val})

@app.route('/api/media/caption', methods=['POST'])
def api_media_caption():
    """Генерация честного нейро-описания для конкретного медиафайла через Florence-2"""
    data = request.json or {}
    filepath = data.get('path')
    if not filepath:
        return jsonify({"error": "No path provided"}), 400
    try:
        import captioner
        res = captioner.caption_single_media(filepath)
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/media/edit_caption', methods=['POST'])
def api_media_edit_caption():
    """Ручное сохранение отредактированного названия и описания медиафайла"""
    data = request.json or {}
    filepath = data.get('path')
    title = (data.get('title') or '').strip()
    caption = (data.get('caption') or '').strip()
    if not filepath:
        return jsonify({"error": "No path provided"}), 400

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE media 
            SET title = ?, caption = ?, caption_model = COALESCE(caption_model, 'manual'), captioned_at = ?
            WHERE path = ?
        """, (title, caption, time.time(), filepath))

        cur.execute("DELETE FROM media_caption_fts WHERE path = ?", (filepath,))
        fts_text = f"{title}\n{caption}"
        cur.execute("INSERT INTO media_caption_fts (path, caption) VALUES (?, ?)", (filepath, fts_text))
        conn.commit()
        return jsonify({"success": True, "path": filepath, "title": title, "caption": caption})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/captioner/status')
def api_captioner_status():
    """Телеметрия фонового генератора описаний"""
    try:
        import captioner
        return jsonify(captioner.get_captioner_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/captioner/start', methods=['POST'])
def api_captioner_start():
    """Запуск фонового генератора описаний"""
    try:
        import captioner
        captioner.start_captioner()
        return jsonify({"success": True, "status": captioner.get_captioner_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/captioner/stop', methods=['POST'])
def api_captioner_stop():
    """Остановка фонового генератора описаний"""
    try:
        import captioner
        captioner.stop_captioner()
        return jsonify({"success": True, "status": captioner.get_captioner_status()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/similar')
def api_similar():
    """Мгновенный поиск визуально похожих изображений через dHash Hamming distance"""
    filepath = request.args.get('path')
    if not filepath:
        return jsonify({"error": "No path provided"}), 400

    conn = get_db()
    similar_items = []
    try:
        cursor = conn.cursor()
        row = cursor.execute("SELECT dhash FROM media WHERE path = ?", (filepath,)).fetchone()
        target_dhash_str = row[0] if (row and row[0]) else ''
        if not target_dhash_str:
            try:
                import cv2
                import numpy as np
                img = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    from PIL import Image
                    with Image.open(filepath) as p_img:
                        rgb = p_img.convert('RGB')
                        img = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
                if img is not None:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    small_hash = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
                    diff = small_hash[:, 1:] > small_hash[:, :-1]
                    hash_int = int(''.join(['1' if val else '0' for val in diff.flatten()]), 2)
                    target_dhash_str = f'{hash_int:016x}'
                    cursor.execute("UPDATE media SET dhash = ? WHERE path = ?", (target_dhash_str, filepath))
                    conn.commit()
            except Exception:
                pass

        if not target_dhash_str:
            return jsonify({"total": 0, "items": [], "msg": "Could not compute dhash for target"}), 200

        try:
            target_dhash_int = int(target_dhash_str, 16)
        except ValueError:
            return jsonify({"total": 0, "items": []}), 200

        cursor.execute("""
        SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
               sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
               hour, tags_json, is_favorite, aspect_category, quality_tier, dhash,
               caption, title
        FROM media WHERE dhash != '' AND path != ?
        """, (filepath,))

        candidates = []
        for r in cursor.fetchall():
            cand_dhash_str = r[20]
            try:
                cand_dhash_int = int(cand_dhash_str, 16)
                # Hamming distance через XOR popcount (0..64)
                dist = bin(target_dhash_int ^ cand_dhash_int).count('1')
                candidates.append((dist, r))
            except Exception:
                pass

        # Сортируем по близости
        candidates.sort(key=lambda x: x[0])
        top_candidates = candidates[:32]

        for dist, r in top_candidates:
            sim_percent = max(0, min(100, int(round((1.0 - dist / 64.0) * 100))))
            tags_preview = []
            try:
                tags_preview = json.loads(r[16])[:10]
            except Exception:
                pass

            similar_items.append({
                "path": r[0], "name": r[1], "ext": r[2], "size": r[3],
                "time": r[4], "width": r[5], "height": r[6], "aspect_ratio": r[7],
                "megapixels": r[8], "sharpness": r[9], "dominant_hex": r[10],
                "dominant_hue": r[11], "is_dark": r[12], "rating": r[13],
                "character_count": r[14], "hour": r[15], "tags": tags_preview,
                "is_favorite": r[17] or 0, "aspect_category": r[18] or 'portrait',
                "quality_tier": r[19] or 'hd', "dhash": r[20] or '',
                "caption": r[21] or '', "title": r[22] or '',
                "distance": dist, "similarity": sim_percent
            })
    except Exception as e:
        print("[API ERROR] /api/similar:", e)
    finally:
        conn.close()

    return jsonify({"total": len(similar_items), "items": similar_items})

@app.route('/api/sequence')
def api_sequence():
    """Поиск манга/комикс/CG серии и альбомов Pixiv с естественной числовой сортировкой страниц"""
    filepath = request.args.get('path')
    if not filepath:
        return jsonify({"error": "No path provided"}), 400

    filename = os.path.basename(filepath)
    name_no_ext = os.path.splitext(filename)[0]
    
    group = detect_media_group(filename)
    conn = get_db()
    items = []
    try:
        cursor = conn.cursor()
        if group["group_type"] == "pixiv":
            raw_id = group["raw_id"]
            cursor.execute("""
            SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
                   sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
                   hour, tags_json, is_favorite, aspect_category, quality_tier, dhash,
                   caption, title
            FROM media 
            WHERE name LIKE ? ESCAPE '/'
            LIMIT 250
            """, (f"%{raw_id}%/_p%",))
        elif group["group_type"] == "series":
            raw_id = group["raw_id"]
            cursor.execute("""
            SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
                   sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
                   hour, tags_json, is_favorite, aspect_category, quality_tier, dhash,
                   caption, title
            FROM media 
            WHERE name LIKE ?
            LIMIT 250
            """, (f"{raw_id}%",))
        else:
            # Fallback к удалению хвостовых цифр
            prefix = re.sub(r'[\s_\-\(\[\{]*\d+[\s_\-\)\]\}]*$', '', name_no_ext).strip()
            if len(prefix) < 3:
                prefix = name_no_ext[:6]
            cursor.execute("""
            SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
                   sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
                   hour, tags_json, is_favorite, aspect_category, quality_tier, dhash,
                   caption, title
            FROM media WHERE name LIKE ? LIMIT 150
            """, (f"{prefix}%",))

        for r in cursor.fetchall():
            tags_preview = []
            try:
                tags_preview = json.loads(r[16])[:8]
            except Exception:
                pass
            item_group = detect_media_group(r[1])
            items.append({
                "path": r[0], "name": r[1], "ext": r[2], "size": r[3],
                "time": r[4], "width": r[5], "height": r[6], "aspect_ratio": r[7],
                "megapixels": r[8], "sharpness": r[9], "dominant_hex": r[10],
                "dominant_hue": r[11], "is_dark": r[12], "rating": r[13],
                "character_count": r[14], "hour": r[15], "tags": tags_preview,
                "is_favorite": r[17] or 0, "aspect_category": r[18] or 'portrait',
                "quality_tier": r[19] or 'hd', "dhash": r[20] or '',
                "caption": r[21] or '', "title": r[22] or '',
                "group_type": item_group["group_type"],
                "group_id": item_group["group_id"],
                "group_raw_id": item_group["raw_id"],
                "group_page": item_group["page"],
                "group_label": item_group["label"]
            })

        # Естественная сортировка страниц по возрастанию: p0, p1, p2... p10
        items.sort(key=lambda x: (x["group_page"], x["name"].lower()))
    except Exception as e:
        print("[API ERROR] /api/sequence:", e)
    finally:
        conn.close()

    return jsonify({
        "total": len(items),
        "items": items,
        "group_type": group["group_type"],
        "group_id": group["group_id"],
        "group_raw_id": group["raw_id"],
        "group_label": group["label"]
    })

@app.route('/api/duplicates')
def api_duplicates():
    """Находит группы/кластеры почти одинаковых кадров (Hamming distance <= threshold)"""
    threshold = request.args.get('threshold', 6, type=int)
    max_clusters = request.args.get('limit', 30, type=int)
    
    conn = get_db()
    flat_items = []
    cluster_id = 1
    try:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT path, name, ext, size, mtime, width, height, aspect_ratio, megapixels, 
               sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count, 
               hour, tags_json, is_favorite, aspect_category, quality_tier, dhash,
               caption, title
        FROM media 
        WHERE dhash IS NOT NULL AND length(dhash) = 16
        ORDER BY mtime DESC
        """)
        raw_rows = cursor.fetchall()
        
        parsed = []
        for r in raw_rows:
            try:
                tags_data = json.loads(r[16]) if r[16] else []
                tags_preview = [t[0] for t in tags_data[:8]] if isinstance(tags_data, list) else []
            except Exception:
                tags_preview = []
            parsed.append({
                "path": r[0], "name": r[1], "ext": r[2], "size": r[3],
                "time": r[4], "width": r[5], "height": r[6], "aspect_ratio": r[7],
                "megapixels": r[8], "sharpness": r[9], "dominant_hex": r[10],
                "dominant_hue": r[11], "is_dark": r[12], "rating": r[13],
                "character_count": r[14], "hour": r[15], "tags": tags_preview,
                "is_favorite": r[17] or 0, "aspect_category": r[18] or 'portrait',
                "quality_tier": r[19] or 'hd', "dhash": r[20] or '',
                "caption": r[21] or '', "title": r[22] or '',
                "_int_hash": int(r[20], 16)
            })

        visited = set()
        for i in range(len(parsed)):
            if i in visited:
                continue
            group = [parsed[i]]
            visited.add(i)

            h1 = parsed[i]["_int_hash"]
            # Сравниваем в скользящем окне
            for j in range(i + 1, min(i + 400, len(parsed))):
                if j in visited:
                    continue
                dist = (h1 ^ parsed[j]["_int_hash"]).bit_count()
                if dist <= threshold:
                    visited.add(j)
                    item_copy = dict(parsed[j])
                    item_copy["similarity"] = round((1.0 - dist / 64.0) * 100, 1)
                    group.append(item_copy)

            if len(group) >= 2:
                group[0]["similarity"] = 100.0
                for item in group:
                    item["cluster_id"] = cluster_id
                    item.pop("_int_hash", None)
                    flat_items.append(item)
                cluster_id += 1
                if cluster_id > max_clusters:
                    break

        return jsonify({
            "total_clusters": cluster_id - 1,
            "total": len(flat_items),
            "items": flat_items
        })
    except Exception as e:
        print("[API ERROR] /api/duplicates:", e)
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route('/api/matrix')
def api_matrix():
    """Генерирует на лету постер-коллаж (3x3, 4x4, 5x5) из текущей выборки"""
    grid_str = request.args.get('grid', '3x3')
    if grid_str == '4x4':
        cols, rows = 4, 4
        tile_size = 384
    elif grid_str == '5x5':
        cols, rows = 5, 5
        tile_size = 300
    else:
        cols, rows = 3, 3
        tile_size = 512
        
    count = cols * rows
    where_clause, params = build_media_query(request.args)
    sort_mode = request.args.get('sort', 'random')
    
    order_clause = "ORDER BY RANDOM()"
    if sort_mode == "sharpness":
        order_clause = "ORDER BY media.sharpness DESC"
    elif sort_mode == "newest":
        order_clause = "ORDER BY media.mtime DESC"

    conn = get_db()
    image_paths = []
    try:
        cursor = conn.cursor()
        ext_filter = "media.ext NOT IN ('.mp4', '.webm', '.mkv', '.avi')"
        if where_clause:
            full_where = f"{where_clause} AND {ext_filter}"
        else:
            full_where = f"WHERE {ext_filter}"

        query = f"""
        SELECT path FROM media 
        {full_where}
        {order_clause} LIMIT ?
        """
        cursor.execute(query, params + [count])
        image_paths = [r[0] for r in cursor.fetchall()]
    except Exception:
        pass
    finally:
        conn.close()

    if not image_paths:
        return "No images found for matrix", 404

    # Создание постера
    border = 6
    canvas_w = cols * tile_size + (cols + 1) * border
    canvas_h = rows * tile_size + (rows + 1) * border
    canvas = Image.new('RGB', (canvas_w, canvas_h), (12, 12, 12))

    for idx, path in enumerate(image_paths):
        c = idx % cols
        r = idx // cols
        x = border + c * (tile_size + border)
        y = border + r * (tile_size + border)
        try:
            with Image.open(path) as img:
                img = ImageOps.fit(img.convert('RGB'), (tile_size, tile_size), Image.Resampling.LANCZOS)
                canvas.paste(img, (x, y))
        except Exception:
            pass

    buf = io.BytesIO()
    canvas.save(buf, format='JPEG', quality=92)
    buf.seek(0)
    return send_file(buf, mimetype='image/jpeg', as_attachment=False, download_name=f"matrix_{grid_str}.jpg")

def stream_file(path, chunk_size=8192*8):
    with open(path, 'rb') as f:
        while chunk := f.read(chunk_size):
            yield chunk

@app.route('/media/stream')
def serve_media():
    filepath = request.args.get('path')
    if not filepath or not os.path.exists(filepath):
        return "File not found", 404

    try:
        file_size = os.path.getsize(filepath)
        mtime = int(os.path.getmtime(filepath))
        etag = f'"{mtime}-{file_size}"'

        if request.headers.get('If-None-Match') == etag:
            return Response(status=304)

        mime_type, _ = mimetypes.guess_type(filepath)
        if not mime_type:
            mime_type = 'application/octet-stream'

        range_header = request.headers.get('Range', None)
        if range_header:
            byte_range = range_header.replace('bytes=', '').split('-')
            start = int(byte_range[0])
            end = int(byte_range[1]) if byte_range[1] else file_size - 1
            length = end - start + 1
            with open(filepath, 'rb') as f:
                f.seek(start)
                data = f.read(length)
            rv = Response(data, 206, mimetype=mime_type, direct_passthrough=True)
            rv.headers.add('Content-Range', f'bytes {start}-{end}/{file_size}')
            rv.headers.add('Accept-Ranges', 'bytes')
            rv.headers.add('Cache-Control', 'public, max-age=604800')
            rv.headers.add('ETag', etag)
            return rv
        else:
            rv = Response(stream_file(filepath), mimetype=mime_type, direct_passthrough=True)
            rv.headers.add('Content-Length', str(file_size))
            rv.headers.add('Accept-Ranges', 'bytes')
            rv.headers.add('Cache-Control', 'public, max-age=604800')
            rv.headers.add('ETag', etag)
            return rv
    except Exception as e:
        return str(e), 500

THUMB_DIR = os.path.join(os.path.dirname(__file__), ".thumbnails")
try:
    os.makedirs(THUMB_DIR, exist_ok=True)
except Exception:
    pass

@app.route('/media/thumb')
def serve_thumbnail():
    """Сверхбыстрая выдача легковесных WebP миниатюр для плавного скролла 144Hz"""
    filepath = request.args.get('path')
    if not filepath or not os.path.exists(filepath):
        return "File not found", 404

    ext = os.path.splitext(filepath)[1].lower()
    if ext in ('.mp4', '.webm', '.mkv', '.avi'):
        return serve_media()

    try:
        file_size = os.path.getsize(filepath)
        mtime = int(os.path.getmtime(filepath))
        thumb_hash = hashlib.md5(f"{filepath}:{mtime}:{file_size}".encode('utf-8')).hexdigest()
        thumb_path = os.path.join(THUMB_DIR, f"{thumb_hash}.webp")

        if request.headers.get('If-None-Match') == f'"{thumb_hash}"':
            return Response(status=304)

        if not os.path.exists(thumb_path):
            with Image.open(filepath) as img:
                img = ImageOps.exif_transpose(img)
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                # 380px идеально подходит под сетку 140-360px
                img.thumbnail((380, 380), Image.Resampling.BILINEAR)
                img.save(thumb_path, format="WEBP", quality=82, method=4)

        rv = send_file(thumb_path, mimetype='image/webp')
        rv.headers['Cache-Control'] = 'public, max-age=2592000, immutable'
        rv.headers['ETag'] = f'"{thumb_hash}"'
        return rv
    except Exception:
        return serve_media()

@app.route('/audio')
def serve_audio():
    if os.path.exists(BACKGROUND_AUDIO):
        return Response(stream_file(BACKGROUND_AUDIO), mimetype="audio/mpeg")
    return "No audio", 404

_captioner_started = False

def ensure_captioner_started():
    global _captioner_started
    if not _captioner_started:
        _captioner_started = True
        try:
            import captioner
            started = captioner.start_captioner()
            if started:
                print("[SERVER] Florence-2 auto-captioner background worker started automatically.")
        except Exception as e:
            print("[SERVER] Could not auto-start captioner:", e)

@app.before_request
def _auto_start_captioner():
    ensure_captioner_started()

if __name__ == '__main__':
    ensure_captioner_started()
    app.run(host='0.0.0.0', port=5000, threaded=True)