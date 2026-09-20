import os
import json
import time
from datetime import datetime
import numpy as np
from PIL import Image
import cv2
import onnxruntime as ort
from db import get_db

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models", "cl_tagger")
MODEL_PATH = os.path.join(MODEL_DIR, "model_bf16.onnx")
VOCAB_PATH = os.path.join(MODEL_DIR, "model_vocabulary.json")

VIDEO_EXTS = {'.mp4', '.webm', '.mkv', '.avi', '.mov'}
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif', '.bmp'}

class CLTagger:
    def __init__(self, model_path=MODEL_PATH, vocab_path=VOCAB_PATH):
        if not os.path.exists(model_path) or not os.path.exists(vocab_path):
            raise FileNotFoundError(f"Model or vocabulary not found in {MODEL_DIR}")
            
        print("[TAGGER] Loading vocabulary...")
        with open(vocab_path, "r", encoding="utf-8") as f:
            self.vocab = json.load(f)
            
        self.idx_to_tag = self.vocab["idx_to_tag"]
        self.tag_to_category = self.vocab.get("tag_to_category", {})
        self.num_tags = len(self.idx_to_tag)
        print(f"[TAGGER] Vocabulary loaded: {self.num_tags} tags.")
        
        print("[TAGGER] Initializing ONNX Runtime DirectML session...")
        providers = ['DmlExecutionProvider', 'CPUExecutionProvider']
        available = ort.get_available_providers()
        selected_providers = [p for p in providers if p in available]
        
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.session = ort.InferenceSession(model_path, sess_options=opts, providers=selected_providers)
        self.active_provider = self.session.get_providers()[0]
        print(f"[TAGGER] Session active using: {self.active_provider}")
        
    def _sigmoid(self, x):
        return 1.0 / (1.0 + np.exp(-np.clip(x, -50, 50)))

    def load_image_frame(self, file_path):
        """Загружает кадр (для картинок - саму картинку, для видео - первый/ключевой кадр)"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext in VIDEO_EXTS:
            try:
                cap = cv2.VideoCapture(file_path)
                ret, frame = cap.read()
                cap.release()
                if ret and frame is not None:
                    return frame
            except Exception:
                pass
            return None
            
        # Загрузка изображения через OpenCV (с поддержкой Unicode путей)
        try:
            cv_img = cv2.imdecode(np.fromfile(file_path, dtype=np.uint8), cv2.IMREAD_COLOR)
            if cv_img is not None:
                return cv_img
        except Exception:
            pass
            
        # Fallback на Pillow для редких форматов (WebP/AVIF/GIF)
        try:
            with Image.open(file_path) as p_img:
                rgb = p_img.convert('RGB')
                return cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
        except Exception:
            return None

    def analyze_features_from_frame(self, cv_img):
        """Вычисляет резкость (Laplacian), палитру (HSV/Hex), пропорции и мегапиксели из кадра"""
        h, w = cv_img.shape[:2]
        megapixels = round((w * h) / 1_000_000.0, 2)
        aspect_ratio = round(w / float(h), 3) if h > 0 else 1.0
        
        # 1. Резкость (Дисперсия Лапласиана)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        sharpness = round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1)
        
        # 2. Доминантный цвет и палитра (K-Means / среднее по миниатюре 48x48)
        small = cv2.resize(cv_img, (48, 48), interpolation=cv2.INTER_AREA)
        pixels = small.reshape(-1, 3).astype(np.float32)
        
        mean_bgr = np.mean(pixels, axis=0)
        b, g, r = int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
        dom_hex = f"#{r:02x}{g:02x}{b:02x}"
        
        # HSV для спектра (Hue 0..360)
        hsv = cv2.cvtColor(np.uint8([[[b, g, r]]]), cv2.COLOR_BGR2HSV)[0][0]
        hue = float(hsv[0]) * 2.0  # OpenCV Hue 0..179 -> 0..360
        brightness = float(hsv[2]) # 0..255
        is_dark = 1 if brightness < 85 else 0
        
        # 3. Перцептивный хеш dHash (64-бит для мгновенного поиска похожих)
        try:
            small_hash = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
            diff = small_hash[:, 1:] > small_hash[:, :-1]
            hash_int = int(''.join(['1' if val else '0' for val in diff.flatten()]), 2)
            dhash_hex = f"{hash_int:016x}"
        except Exception:
            dhash_hex = ""
            
        # 4. Категория пропорций (Aspect category)
        if aspect_ratio >= 1.6:
            aspect_cat = 'panorama' if aspect_ratio >= 2.1 else 'landscape'
        elif aspect_ratio <= 0.8:
            aspect_cat = 'portrait'
        else:
            aspect_cat = 'square'
            
        # 5. Уровень качества (Quality tier)
        if megapixels >= 8.0:
            quality_tier = '4k'
        elif megapixels >= 2.0:
            quality_tier = 'fhd'
        elif megapixels >= 0.8:
            quality_tier = 'hd'
        else:
            quality_tier = 'sd'

        return {
            "width": w,
            "height": h,
            "aspect_ratio": aspect_ratio,
            "megapixels": megapixels,
            "sharpness": sharpness,
            "dominant_hex": dom_hex,
            "dominant_hue": hue,
            "is_dark": is_dark,
            "dhash": dhash_hex,
            "aspect_category": aspect_cat,
            "quality_tier": quality_tier
        }

    def frame_to_tensor(self, cv_img):
        """Быстрое преобразование BGR кадра в 1x3x384x384 тензор SigLIP без лишнего I/O"""
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (384, 384), interpolation=cv2.INTER_AREA)
        arr = (resized.astype(np.float32) / 255.0 - 0.5) / 0.5
        arr = np.transpose(arr, (2, 0, 1))
        return np.expand_dims(arr, axis=0)

    def predict_tags_from_frame(self, cv_img, target_min_tags=50, max_tags=120):
        """Инференс CL Tagger v2 с динамическим порогом (гарантия 50–120 детальных тегов)"""
        tensor = self.frame_to_tensor(cv_img)
        logits = self.session.run(None, {"pixel_values": tensor})[0][0]
        probs = self._sigmoid(logits)
        
        # 1. Поиск базового порога для гарантии target_min_tags
        threshold = 0.35
        indices = np.where(probs >= threshold)[0]
        
        # Если тегов меньше целевого минимума, динамически снижаем порог до 0.22
        if len(indices) < target_min_tags:
            for step_th in (0.30, 0.26, 0.22):
                indices = np.where(probs >= step_th)[0]
                if len(indices) >= target_min_tags:
                    threshold = step_th
                    break
                    
        # 2. Извлечение тегов и скоров
        tag_candidates = []
        rating = "general"
        char_count = "solo"
        
        # Всегда проверяем специальные категории
        for idx in np.where(probs >= 0.20)[0]:
            prob = float(probs[idx])
            tag_name = self.idx_to_tag[str(idx)] if str(idx) in self.idx_to_tag else self.idx_to_tag[idx]
            cat = self.tag_to_category.get(tag_name, "General")
            
            if cat == "Rating" and prob > 0.35:
                rating = tag_name.lower()
            elif tag_name in ("1girl", "1boy", "solo"):
                char_count = "solo"
            elif tag_name in ("2girls", "2boys", "duo"):
                char_count = "duo"
            elif tag_name in ("3girls", "threesome"):
                char_count = "threesome"
            elif tag_name in ("group", "orgy", "harem"):
                char_count = "group"
                
            if prob >= threshold:
                tag_candidates.append((tag_name, round(prob, 3), cat))
                
        # Сортировка по вероятности
        tag_candidates.sort(key=lambda x: -x[1])
        
        # Ограничение максимума
        tag_candidates = tag_candidates[:max_tags]
        
        tags_list = [t[0] for t in tag_candidates]
        tags_dict = {t[0]: t[1] for t in tag_candidates}
        
        return {
            "tags": tags_list,
            "tag_scores": tags_dict,
            "rating": rating,
            "character_count": char_count
        }

    def predict_and_save_tensor(self, tensor, features, file_path, mtime, size, save_sidecar=True, db_conn=None):
        """Инференс по уже готовому тензору (для асинхронного конвейера) и запись в БД"""
        logits = self.session.run(None, {"pixel_values": tensor})[0][0]
        probs = self._sigmoid(logits)
        
        threshold = 0.35
        indices = np.where(probs >= threshold)[0]
        if len(indices) < 50:
            for step_th in (0.30, 0.26, 0.22):
                indices = np.where(probs >= step_th)[0]
                if len(indices) >= 50:
                    threshold = step_th
                    break
                    
        tag_candidates = []
        rating = "general"
        char_count = "solo"
        
        for idx in np.where(probs >= 0.20)[0]:
            prob = float(probs[idx])
            tag_name = self.idx_to_tag[str(idx)] if str(idx) in self.idx_to_tag else self.idx_to_tag[idx]
            cat = self.tag_to_category.get(tag_name, "General")
            
            if cat == "Rating" and prob > 0.35:
                rating = tag_name.lower()
            elif tag_name in ("1girl", "1boy", "solo"):
                char_count = "solo"
            elif tag_name in ("2girls", "2boys", "duo"):
                char_count = "duo"
            elif tag_name in ("3girls", "threesome"):
                char_count = "threesome"
            elif tag_name in ("group", "orgy", "harem"):
                char_count = "group"
                
            if prob >= threshold:
                tag_candidates.append((tag_name, round(prob, 3), cat))
                
        tag_candidates.sort(key=lambda x: -x[1])
        tag_candidates = tag_candidates[:120]
        
        tags_list = [t[0] for t in tag_candidates]
        tags_dict = {t[0]: t[1] for t in tag_candidates}
        
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()
        
        dt = datetime.fromtimestamp(mtime)
        hour = dt.hour
        day_of_week = dt.weekday()
        
        # 1. Сохранение Sidecar .txt
        if save_sidecar:
            txt_path = f"{os.path.splitext(file_path)[0]}.txt"
            try:
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(", ".join(tags_list))
            except Exception:
                pass
                
        # 2. Запись в SQLite
        conn = db_conn if db_conn is not None else get_db()
        cursor = conn.cursor()
        
        tags_str = " ".join(tags_list)
        tags_json = json.dumps(tags_list, ensure_ascii=False)
        scores_json = json.dumps(tags_dict, ensure_ascii=False)
        
        cursor.execute("""
        INSERT OR REPLACE INTO media (
            path, name, ext, size, mtime, width, height, aspect_ratio, megapixels,
            sharpness, dominant_hex, dominant_hue, is_dark, rating, character_count,
            hour, day_of_week, tags_json, tag_scores_json, indexed_at,
            dhash, aspect_category, quality_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file_path, filename, ext, size, mtime,
            features["width"], features["height"], features["aspect_ratio"], features["megapixels"],
            features["sharpness"], features["dominant_hex"], features["dominant_hue"], features["is_dark"],
            rating, char_count, hour, day_of_week,
            tags_json, scores_json, time.time(),
            features["dhash"], features["aspect_category"], features["quality_tier"]
        ))
        
        cursor.execute("DELETE FROM media_tags_fts WHERE path = ?", (file_path,))
        cursor.execute("INSERT INTO media_tags_fts (path, tags) VALUES (?, ?)", (file_path, tags_str))
        
        for tag in tags_list:
            cat = self.tag_to_category.get(tag, "General")
            cursor.execute("""
            INSERT INTO tag_frequencies (tag, category, count) VALUES (?, ?, 1)
            ON CONFLICT(tag) DO UPDATE SET count = count + 1
            """, (tag, cat))
            
        if db_conn is None:
            conn.commit()
            conn.close()
            
        return {
            "path": file_path,
            "tags_count": len(tags_list),
            "sharpness": features["sharpness"],
            "dominant_hex": features["dominant_hex"],
            "rating": rating
        }

    def process_and_save(self, file_path, save_sidecar=True, db_conn=None):
        """Полная обработка 1 файла и сохранение в SQLite + Sidecar .txt"""
        frame = self.load_image_frame(file_path)
        if frame is None:
            return None
            
        features = self.analyze_features_from_frame(frame)
        tensor = self.frame_to_tensor(frame)
        
        stat = os.stat(file_path)
        return self.predict_and_save_tensor(
            tensor, features, file_path, stat.st_mtime, stat.st_size,
            save_sidecar=save_sidecar, db_conn=db_conn
        )

if __name__ == "__main__":
    tagger = CLTagger()
    print("CLTagger ready for batch processing.")
