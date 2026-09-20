import os
import sys
import re
import time
import threading
from PIL import Image
import torch
from transformers import AutoProcessor, AutoModelForCausalLM, MarianTokenizer, MarianMTModel

import db

if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = True

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "florence2_promptgen")

_model = None
_processor = None
_translator_model = None
_translator_tok = None
_model_lock = threading.Lock()
_worker_thread = None
_stop_event = threading.Event()

_status = {
    "is_running": False,
    "total": 0,
    "captioned": 0,
    "pending": 0,
    "current_path": "",
    "last_title": "",
    "last_caption": "",
    "last_duration": 0.0,
    "errors": 0
}

CLEAN_PATTERNS = [
    re.compile(r'^(a\s+)?(black\s+and\s+white\s+)?(line\s+)?(drawing|sketch|illustration|artwork|picture|image|photo)\s+(of|featuring|depicting|with|showing)\s+', re.IGNORECASE),
    re.compile(r'^(a\s+)?(digital\s+)?(illustration|drawing|artwork|image|photo|picture|painting)\s+(of|featuring|depicting|with|showing)\s+', re.IGNORECASE),
    re.compile(r'^(an\s+)?anime(-style)?\s+(drawing|illustration|artwork|image|picture)\s+(of|featuring|depicting|with|showing)\s+', re.IGNORECASE),
    re.compile(r'^(a\s+)?(comic\s+strip|comic\s+book\s+page|comic\s+panel|manga\s+page|manga\s+panel)\s+(of|featuring|depicting|with|showing)\s+', re.IGNORECASE),
    re.compile(r'^(a\s+)?comic\s+(featuring|of|depicting|with|showing)\s+', re.IGNORECASE),
    re.compile(r'^(a\s+)?simple\s+(drawing|sketch|illustration)\s+(of|featuring|with)\s+', re.IGNORECASE),
    re.compile(r'^(a\s+)?(close-up|full\s+shot|wide\s+shot)\s+of\s+', re.IGNORECASE),
]

def clean_boilerplate(text: str) -> str:
    t = text.strip()
    for pat in CLEAN_PATTERNS:
        t = pat.sub('', t).strip()
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    return t

def extract_title_en(clean_desc: str) -> str:
    sents = re.split(r'(?<=[.!?])\s+', clean_desc)
    first_sent = sents[0].strip().rstrip('. ')
    
    # If first sentence is long, strip action/location clauses to isolate main subject
    if len(first_sent) > 70:
        m = re.search(r',\s+(standing|sitting|lying|walking|running|holding|wearing|dressed in|surrounded by|posing|looking|placed)\b', first_sent, re.IGNORECASE)
        if m and m.start() > 20:
            first_sent = first_sent[:m.start()].strip()
        else:
            comma_idx = first_sent.find(',')
            if 25 < comma_idx < 80:
                first_sent = first_sent[:comma_idx].strip()
            elif len(first_sent) > 100:
                cut = first_sent[:95].rfind(' ')
                if cut > 30:
                    first_sent = first_sent[:cut].strip()

    return first_sent.strip(' .,;:-—')

def get_model():
    global _model, _processor
    if _model is not None:
        return _model, _processor

    with _model_lock:
        if _model is not None:
            return _model, _processor

        device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        
        print(f"[Captioner] Loading Florence-2 model on {device} ({dtype})...")
        t0 = time.time()
        
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            trust_remote_code=True,
            dtype=dtype
        ).to(device)

        # Crucial: tie encoder and decoder embed_tokens to shared weights from safetensors
        if hasattr(model, "language_model"):
            lm = model.language_model
            if hasattr(lm, "model") and hasattr(lm.model, "shared"):
                lm.model.encoder.embed_tokens.weight = lm.model.shared.weight
                lm.model.decoder.embed_tokens.weight = lm.model.shared.weight

        model.eval()
        processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
        
        _model = model
        _processor = processor
        print(f"[Captioner] Florence-2 ready in {time.time()-t0:.2f}s on {device}!")
        return _model, _processor

def get_translator():
    global _translator_model, _translator_tok
    if _translator_model is not None:
        return _translator_model, _translator_tok

    with _model_lock:
        if _translator_model is not None:
            return _translator_model, _translator_tok

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[Captioner] Loading MarianMT en-ru on {device}...")
        t0 = time.time()
        
        tok = MarianTokenizer.from_pretrained("Helsinki-NLP/opus-mt-en-ru")
        model = MarianMTModel.from_pretrained("Helsinki-NLP/opus-mt-en-ru").to(device)
        if device == "cuda":
            model = model.half()
        model.eval()

        _translator_model = model
        _translator_tok = tok
        print(f"[Captioner] MarianMT ready in {time.time()-t0:.2f}s on {device}!")
        return _translator_model, _translator_tok

RU_REPLACEMENTS = [
    (re.compile(r'\bчестн(ой|ая|ую|ом|ыми)\s+кож(ей|а|у|е|ами)\b', re.IGNORECASE), r'светл\1 кож\2'),
    (re.compile(r'\bв\s+(двух\s+)?булочк(ах|е)\b', re.IGNORECASE), r'в \1пучк\2'),
    (re.compile(r'\bв\s+двух\s+булках\b', re.IGNORECASE), 'в двух пучках'),
    (re.compile(r'\bс\s+мягким\s+щупальцем\b', re.IGNORECASE), 'с мягким затенением'),
    (re.compile(r'\bвыраженийе\b', re.IGNORECASE), 'выражении'),
    (re.compile(r'\b(в\s+)?(черных|белых|красных)?\s*тонг(ах)?\b', re.IGNORECASE), r'\1\2 стрингах'),
]

def clean_russian_translation(text: str) -> str:
    res = text
    for pat, repl in RU_REPLACEMENTS:
        res = pat.sub(repl, res)
    return res

def translate_to_russian(texts: list[str]) -> list[str]:
    model, tok = get_translator()
    device = next(model.parameters()).device
    batch = tok(texts, return_tensors="pt", padding=True, truncation=True, max_length=256).to(device)
    with torch.inference_mode():
        gen = model.generate(**batch, max_length=256, num_beams=1)
    decoded = tok.batch_decode(gen, skip_special_tokens=True)
    return [clean_russian_translation(t) for t in decoded]

def generate_caption_and_title(image_path: str) -> tuple[str, str]:
    """Generates an honest Russian title and 2-3 sentence description."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    model, processor = get_model()
    device = next(model.parameters()).device
    dtype = next(model.parameters()).dtype

    with Image.open(image_path) as raw_img:
        image = raw_img.convert("RGB")
        w, h = image.width, image.height

    # 1. Short title (<CAPTION>)
    raw_in1 = processor(text="<CAPTION>", images=image, return_tensors="pt")
    in1 = {k: v.to(device=device, dtype=dtype if torch.is_floating_point(v) else None) for k, v in raw_in1.items()}
    with torch.no_grad():
        out1 = model.generate(
            input_ids=in1["input_ids"],
            pixel_values=in1["pixel_values"],
            max_new_tokens=40,
            do_sample=False,
            num_beams=1,
            use_cache=False
        )
    raw_title = processor.post_process_generation(processor.batch_decode(out1, skip_special_tokens=False)[0], task="<CAPTION>", image_size=(w, h)).get("<CAPTION>", "").strip()

    # 2. Detailed description (<DETAILED_CAPTION>)
    raw_in2 = processor(text="<DETAILED_CAPTION>", images=image, return_tensors="pt")
    in2 = {k: v.to(device=device, dtype=dtype if torch.is_floating_point(v) else None) for k, v in raw_in2.items()}
    with torch.no_grad():
        out2 = model.generate(
            input_ids=in2["input_ids"],
            pixel_values=in2["pixel_values"],
            max_new_tokens=110,
            do_sample=False,
            num_beams=1,
            use_cache=False
        )
    raw_desc = processor.post_process_generation(processor.batch_decode(out2, skip_special_tokens=False)[0], task="<DETAILED_CAPTION>", image_size=(w, h)).get("<DETAILED_CAPTION>", "").strip()

    # Clean English template fluff
    clean_title = clean_boilerplate(raw_title)
    clean_desc = clean_boilerplate(raw_desc)

    # Fast GPU translation of both items in 1 batch
    ru_results = translate_to_russian([clean_title, clean_desc])
    ru_title = ru_results[0].strip(' .')
    ru_desc = ru_results[1].strip()

    if ru_title and ru_title[0].islower():
        ru_title = ru_title[0].upper() + ru_title[1:]
    if ru_desc and ru_desc[0].islower():
        ru_desc = ru_desc[0].upper() + ru_desc[1:]

    return ru_title, ru_desc

def caption_batch(paths: list[str]) -> list[dict]:
    """Generates and saves Russian title and caption for a batch of files in database."""
    valid_items = []
    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext in ('.mp4', '.webm', '.mkv', '.avi'):
            continue
        if not os.path.exists(p):
            try:
                c = db.get_db()
                c.execute("UPDATE media SET caption_model = 'missing' WHERE path = ?", (p,))
                c.commit()
                c.close()
            except Exception:
                pass
            continue
        try:
            with Image.open(p) as raw_img:
                w, h = raw_img.width, raw_img.height
                if max(w, h) > 1024:
                    raw_img.thumbnail((1024, 1024), Image.Resampling.BILINEAR)
                img = raw_img.convert("RGB")
                valid_items.append((p, img, (w, h)))
        except Exception as e:
            print(f"[Captioner Error opening] {p}: {e}")
            try:
                c = db.get_db()
                c.execute("UPDATE media SET caption_model = 'error' WHERE path = ?", (p,))
                c.commit()
                c.close()
            except Exception:
                pass

    if not valid_items:
        return []

    model, processor = get_model()
    device = next(model.parameters()).device
    dtype = next(model.parameters()).dtype

    images = [item[1] for item in valid_items]
    sizes = [item[2] for item in valid_items]
    file_paths = [item[0] for item in valid_items]

    t0 = time.time()
    prompts = ["<DETAILED_CAPTION>"] * len(images)
    raw_in = processor(text=prompts, images=images, return_tensors="pt", padding=True)
    inputs = {k: v.to(device=device, dtype=dtype if torch.is_floating_point(v) else None) for k, v in raw_in.items()}

    with torch.inference_mode():
        out = model.generate(
            input_ids=inputs["input_ids"],
            pixel_values=inputs["pixel_values"],
            max_new_tokens=95,
            do_sample=False,
            num_beams=1,
            use_cache=False
        )

    decoded = processor.batch_decode(out, skip_special_tokens=False)
    
    titles_en = []
    descs_en = []
    for i, dec in enumerate(decoded):
        parsed = processor.post_process_generation(dec, task="<DETAILED_CAPTION>", image_size=sizes[i]).get("<DETAILED_CAPTION>", "").strip()
        clean = clean_boilerplate(parsed)
        title_en = extract_title_en(clean)
        titles_en.append(title_en)
        descs_en.append(clean)

    # Fast GPU translation of titles + descriptions in 1 batch
    all_ru = translate_to_russian(titles_en + descs_en)
    n = len(file_paths)
    ru_titles = all_ru[:n]
    ru_descs = all_ru[n:]
    
    duration = time.time() - t0
    per_img_duration = round(duration / n, 2)

    results = []
    conn = db.get_db()
    cursor = conn.cursor()
    now = time.time()

    for i in range(n):
        path = file_paths[i]
        title = ru_titles[i].strip(' .,;:-—')
        desc = ru_descs[i].strip()
        if title and title[0].islower():
            title = title[0].upper() + title[1:]
        if desc and desc[0].islower():
            desc = desc[0].upper() + desc[1:]

        cursor.execute("""
            UPDATE media 
            SET title = ?, caption = ?, caption_model = 'florence2-ru', captioned_at = ?
            WHERE path = ?
        """, (title, desc, now, path))

        cursor.execute("DELETE FROM media_caption_fts WHERE path = ?", (path,))
        fts_text = f"{title}\n{desc}"
        cursor.execute("INSERT INTO media_caption_fts (path, caption) VALUES (?, ?)", (path, fts_text))

        results.append({
            "success": True,
            "path": path,
            "title": title,
            "caption": desc,
            "duration": per_img_duration
        })

    conn.commit()
    conn.close()
    return results

def caption_single_media(path: str) -> dict:
    """Generates and saves Russian title and caption for a single file in database."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.mp4', '.webm', '.mkv', '.avi'):
        return {"success": False, "path": path, "title": "", "caption": "", "duration": 0, "error": "Video skipped"}

    res = caption_batch([path])
    if res:
        return res[0]
    return {"success": False, "path": path, "title": "", "caption": "", "duration": 0, "error": "Processing failed"}

def update_status():
    global _status
    conn = db.get_db()
    total = conn.execute("SELECT COUNT(*) FROM media WHERE ext NOT IN ('.mp4', '.webm', '.mkv', '.avi')").fetchone()[0]
    captioned = conn.execute("SELECT COUNT(*) FROM media WHERE caption_model = 'florence2-ru'").fetchone()[0]
    conn.close()

    _status["total"] = total
    _status["captioned"] = captioned
    _status["pending"] = max(0, total - captioned)

def get_captioner_status() -> dict:
    update_status()
    return dict(_status)

def _worker_loop():
    global _status
    _status["is_running"] = True
    print("[Captioner] Background Russian auto-captioner worker started (random gap-filling mode).")

    BATCH_SIZE = 4

    while not _stop_event.is_set():
        update_status()
        conn = db.get_db()
        # Random gap-filling: picks random uncaptioned images across all folders, with favorites first
        rows = conn.execute("""
            SELECT path FROM media 
            WHERE (caption_model IS NULL OR caption_model != 'florence2-ru')
              AND (caption_model IS NULL OR (caption_model != 'error' AND caption_model != 'missing'))
              AND ext NOT IN ('.mp4', '.webm', '.mkv', '.avi')
            ORDER BY is_favorite DESC, RANDOM()
            LIMIT 100
        """).fetchall()
        conn.close()

        if not rows:
            print("[Captioner] All images captioned in Russian! Sleeping 30s...")
            _status["is_running"] = False
            for _ in range(30):
                if _stop_event.is_set():
                    break
                time.sleep(1)
            continue

        _status["is_running"] = True

        paths = [r["path"] for r in rows]
        
        for i in range(0, len(paths), BATCH_SIZE):
            if _stop_event.is_set():
                break
            chunk = paths[i:i+BATCH_SIZE]
            _status["current_path"] = chunk[0]
            try:
                res_list = caption_batch(chunk)
                for res in res_list:
                    _status["last_title"] = res["title"]
                    _status["last_caption"] = res["caption"]
                    _status["last_duration"] = res["duration"]
                    _status["captioned"] += 1
                    _status["pending"] = max(0, _status["total"] - _status["captioned"])
                    print(f"[AI RU] ({res['duration']}s) {res['title']} -> {res['caption'][:50]}...")
            except Exception as e:
                _status["errors"] += len(chunk)
                print(f"[Captioner Error in batch]: {e}")
                try:
                    c = db.get_db()
                    for p in chunk:
                        c.execute("UPDATE media SET caption_model = 'error' WHERE path = ?", (p,))
                    c.commit()
                    c.close()
                except Exception:
                    pass
            time.sleep(0.01)

    _status["is_running"] = False
    print("[Captioner] Background automated worker stopped.")

def start_captioner():
    global _worker_thread
    if _worker_thread is not None and _worker_thread.is_alive():
        return False
    _stop_event.clear()
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="FlorenceRuCaptioner")
    _worker_thread.start()
    return True

def stop_captioner():
    _stop_event.set()
    return True

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Florence-2 Russian Title & Captioner")
    parser.add_argument("--test", type=str, help="Caption a single image and exit")
    parser.add_argument("--count", type=int, default=3, help="Caption N images in Russian")
    parser.add_argument("--daemon", action="store_true", help="Run continuous Russian auto-captioner")
    args = parser.parse_args()

    if args.test:
        print("Testing Russian caption on:", args.test)
        res = caption_single_media(args.test)
        print("Title:", res["title"])
        print("Caption:", res["caption"])
        print("Duration:", res["duration"])
    elif args.daemon:
        start_captioner()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_captioner()
    else:
        print(f"Captioning {args.count} images in Russian...")
        conn = db.get_db()
        rows = conn.execute("""
            SELECT path FROM media 
            WHERE (caption_model IS NULL OR caption_model != 'florence2-ru')
              AND ext NOT IN ('.mp4', '.webm')
            ORDER BY is_favorite DESC, mtime DESC LIMIT ?
        """, (args.count,)).fetchall()
        conn.close()
        for r in rows:
            res = caption_single_media(r["path"])
            print(f"[{res['duration']}s] {os.path.basename(r['path'])}")
            print(f"  НАЗВАНИЕ: {res['title']}")
            print(f"  ОПИСАНИЕ: {res['caption']}\n")
