import os
import random
import mimetypes
import time
import shutil
import hashlib
from datetime import datetime
from flask import Flask, render_template, request, Response, jsonify

try:
    import cv2
except ImportError:
    cv2 = None

app = Flask(__name__)

# Базовая папка при старте
CURRENT_BASE_DIR = r"C:\Users\danat\Pictures\Amazing Stray 3.4 final"

# Директории
GALLERY_ROOT = os.path.dirname(os.path.abspath(__file__))
FAVORITES_DIR = os.path.join(GALLERY_ROOT, "FAVORITES")
THUMBNAIL_DIR = os.path.join(GALLERY_ROOT, "cache", "thumbnails")
AUDIO_DIR = os.path.join(GALLERY_ROOT, "audio")

os.makedirs(FAVORITES_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.mkv'}
mimetypes.add_type('video/webm', '.webm')
mimetypes.add_type('video/mp4', '.mp4')

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
                            "time": stat.st_mtime, # Время изменения для группировки
                            "size": stat.st_size
                        })
    except Exception as e:
        pass # Игнорируем заблокированные системные файлы
    return files_data

def get_subfolders(base_path):
    folders = ["Все медиа", "🔥 ИЗБРАННОЕ"]
    try:
        with os.scandir(base_path) as it:
            for entry in it:
                if entry.is_dir() and not entry.name.startswith('.'):
                    folders.append(entry.name)
    except Exception:
        pass
    return folders

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config')
def api_config():
    global CURRENT_BASE_DIR
    return jsonify({
        "current_dir": CURRENT_BASE_DIR,
        "folders": get_subfolders(CURRENT_BASE_DIR)
    })

@app.route('/api/change_root', methods=['POST'])
def api_change_root():
    global CURRENT_BASE_DIR
    data = request.json
    new_path = data.get("path", "").strip()
    
    if os.path.exists(new_path) and os.path.isdir(new_path):
        CURRENT_BASE_DIR = new_path
        return jsonify({"success": True, "msg": f"Папка изменена на {new_path}"})
    return jsonify({"success": False, "msg": "Указанный путь не существует или это не папка"}), 400

@app.route('/api/playlist')
def api_playlist():
    folder = request.args.get('folder', 'Все медиа')
    sort_mode = request.args.get('sort', 'newest')
    
    search_path = CURRENT_BASE_DIR
    if folder == "🔥 ИЗБРАННОЕ":
        search_path = FAVORITES_DIR
    elif folder != "Все медиа":
        target = os.path.join(CURRENT_BASE_DIR, folder)
        if os.path.exists(target):
            search_path = target

    media_files = fast_scan(search_path)

    # Сортировка
    if sort_mode == "random":
        random.shuffle(media_files)
    elif sort_mode == "newest":
        media_files.sort(key=lambda x: x["time"], reverse=True)
    elif sort_mode == "oldest":
        media_files.sort(key=lambda x: x["time"])
    elif sort_mode == "az":
        media_files.sort(key=lambda x: x["name"].lower())

    return jsonify({"total": len(media_files), "items": media_files})

@app.route('/api/favorite', methods=['POST'])
def api_favorite():
    data = request.json
    path = data.get("path")
    if path and os.path.exists(path):
        filename = os.path.basename(path)
        dest = os.path.join(FAVORITES_DIR, filename)
        if not os.path.exists(dest):
            try:
                shutil.copy2(path, dest)
                return jsonify({"success": True, "msg": "Добавлено в Избранное!"})
            except Exception as e:
                return jsonify({"success": False, "msg": str(e)}), 500
        return jsonify({"success": True, "msg": "Уже в Избранном."})
    return jsonify({"success": False, "msg": "Файл не найден"}), 400

@app.route('/api/audio_playlist')
def api_audio_playlist():
    playlist = []
    if os.path.exists(AUDIO_DIR):
        for f in os.listdir(AUDIO_DIR):
            if f.lower().endswith(('.mp3', '.wav', '.ogg', '.flac', '.m4a')):
                playlist.append(os.path.join(AUDIO_DIR, f))
    
    default_bg = os.path.join(GALLERY_ROOT, "bg_audio.mp3")
    if os.path.exists(default_bg):
        playlist.append(default_bg)
        
    random.shuffle(playlist)
    return jsonify({"playlist": playlist})

def stream_file(path, chunk_size=8192*8): # Увеличен чанк для плавности 4K видео
    with open(path, 'rb') as f:
        while chunk := f.read(chunk_size):
            yield chunk

@app.route('/media/thumbnail')
def serve_thumbnail():
    filepath = request.args.get('path')
    if not filepath or not os.path.exists(filepath):
        return "File not found", 404

    # Генерируем уникальный хэш для кэша
    file_hash = hashlib.md5(filepath.encode('utf-8')).hexdigest()
    thumb_path = os.path.join(THUMBNAIL_DIR, f"{file_hash}.jpg")

    if not os.path.exists(thumb_path):
        if cv2:
            try:
                cap = cv2.VideoCapture(filepath)
                frames_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if frames_count > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, min(int(frames_count * 0.1), frames_count - 1))
                ret, frame = cap.read()
                if ret:
                    h, w = frame.shape[:2]
                    ratio = 300 / float(h)
                    new_dim = (int(w * ratio), 300)
                    resized = cv2.resize(frame, new_dim, interpolation=cv2.INTER_AREA)
                    cv2.imwrite(thumb_path, resized)
                cap.release()
            except Exception as e:
                pass
                
    if os.path.exists(thumb_path):
        return Response(stream_file(thumb_path), mimetype='image/jpeg')
    
    # Fallback to standard stream if thumbnail failed
    return serve_media()

@app.route('/media/stream')
def serve_media():
    filepath = request.args.get('path')
    if not filepath or not os.path.exists(filepath):
        return "File not found", 404

    try:
        file_size = os.path.getsize(filepath)
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
            return rv
        else:
            rv = Response(stream_file(filepath), mimetype=mime_type, direct_passthrough=True)
            rv.headers.add('Content-Length', str(file_size))
            rv.headers.add('Accept-Ranges', 'bytes')
            return rv
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)