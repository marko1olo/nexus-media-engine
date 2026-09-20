import os
import sys
import time
import threading
from datetime import datetime
from db import get_db, DB_PATH
from tagger import CLTagger, IMAGE_EXTS, VIDEO_EXTS

SUPPORTED_EXTENSIONS = IMAGE_EXTS | VIDEO_EXTS

class ScannerManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(ScannerManager, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self):
        self.is_running = False
        self.stop_requested = False
        self.tagger = None
        self.thread = None
        
        # Статистика
        self.total_files = 0
        self.indexed_files = 0
        self.remaining_files = 0
        self.processed_in_session = 0
        self.error_count = 0
        self.current_file = ""
        self.start_time = 0.0
        self.elapsed_sec = 0.0
        self.fps = 0.0
        self.eta_sec = 0.0
        self.percent = 0.0
        self.current_dir = ""
        try:
            conn = get_db()
            self.indexed_files = conn.execute("SELECT count(*) FROM media").fetchone()[0]
            conn.close()
        except Exception:
            pass

    def get_tagger(self):
        if self.tagger is None:
            self.tagger = CLTagger()
        return self.tagger

    def get_status(self):
        if self.is_running and self.start_time > 0:
            self.elapsed_sec = round(time.time() - self.start_time, 1)
            if self.elapsed_sec > 0 and self.processed_in_session > 0:
                self.fps = round(self.processed_in_session / self.elapsed_sec, 2)
                if self.fps > 0 and self.remaining_files > 0:
                    self.eta_sec = round(self.remaining_files / self.fps)
                else:
                    self.eta_sec = 0
            if self.total_files > 0:
                self.percent = round((self.indexed_files / float(self.total_files)) * 100.0, 1)

        return {
            "is_running": self.is_running,
            "total_files": self.total_files,
            "indexed_files": self.indexed_files,
            "remaining_files": self.remaining_files,
            "processed_in_session": self.processed_in_session,
            "percent": self.percent,
            "fps": self.fps,
            "current_file": self.current_file,
            "elapsed_sec": self.elapsed_sec,
            "eta_sec": self.eta_sec,
            "error_count": self.error_count,
            "current_dir": self.current_dir
        }

    def start(self, directory=r"C:\Users\Admin\Pictures\Amazing Stray 3.4 final", save_sidecar=True, batch_size=20):
        with self._lock:
            if self.is_running:
                return False, "Сканирование уже запущено."
            self.is_running = True
            self.stop_requested = False
            self.current_dir = directory
            self.processed_in_session = 0
            self.error_count = 0
            self.start_time = time.time()
            
            self.thread = threading.Thread(
                target=self._run_scan_worker,
                args=(directory, save_sidecar, batch_size),
                daemon=True
            )
            self.thread.start()
            return True, "Сканирование успешно запущено в фоне."

    def stop(self):
        with self._lock:
            if not self.is_running:
                return False, "Сканирование не запущено."
            self.stop_requested = True
            return True, "Остановка запрошена..."

    def _run_scan_worker(self, directory, save_sidecar, batch_size):
        print(f"[SCANNER] Starting deep crawler on: {directory}")
        try:
            tagger = self.get_tagger()
        except Exception as e:
            print(f"[SCANNER ERROR] Failed to initialize tagger: {e}")
            self.is_running = False
            return

        # 1. Загрузка уже проиндексированных путей и mtime из SQLite
        conn = get_db()
        indexed_map = {}
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT path, mtime FROM media")
            for row in cursor.fetchall():
                indexed_map[row[0]] = row[1]
        except Exception as e:
            print(f"[SCANNER ERROR] Failed to query existing media: {e}")
        finally:
            conn.close()

        # 2. Быстрый сбор всех файлов в директории (включая все подпапки)
        all_candidates = []
        try:
            for root, dirs, files in os.walk(directory):
                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        fpath = os.path.join(root, fname)
                        try:
                            mtime = os.path.getmtime(fpath)
                            all_candidates.append((fpath, fname, mtime))
                        except Exception:
                            pass
        except Exception as e:
            print(f"[SCANNER ERROR] Scan dir error: {e}")

        self.total_files = len(all_candidates)
        
        # 3. Фильтрация задач (только новые или измененные)
        tasks = []
        for path, name, mtime in all_candidates:
            if path not in indexed_map or abs(indexed_map[path] - mtime) > 1.0:
                tasks.append((path, name))

        self.indexed_files = self.total_files - len(tasks)
        self.remaining_files = len(tasks)
        print(f"[SCANNER] Total: {self.total_files}, Already indexed: {self.indexed_files}, To process: {self.remaining_files}")

        if not tasks:
            print("[SCANNER] Everything is up to date!")
            self.is_running = False
            return

        # 4. Высокоскоростной асинхронный конвейер (Producer: CPU/диск -> Consumer: GPU DirectML)
        from queue import Queue, Empty
        task_queue = Queue(maxsize=16)
        
        def producer_worker():
            for file_path, file_name in tasks:
                if self.stop_requested:
                    break
                try:
                    frame = tagger.load_image_frame(file_path)
                    if frame is None:
                        continue
                    features = tagger.analyze_features_from_frame(frame)
                    tensor = tagger.frame_to_tensor(frame)
                    stat = os.stat(file_path)
                    task_queue.put((file_path, file_name, stat.st_mtime, stat.st_size, features, tensor))
                except Exception:
                    pass
            task_queue.put(None)

        producer_thread = threading.Thread(target=producer_worker, daemon=True)
        producer_thread.start()

        db_conn = get_db()
        batch_counter = 0
        try:
            while True:
                if self.stop_requested:
                    break
                try:
                    item = task_queue.get(timeout=1.0)
                except Empty:
                    if not producer_thread.is_alive():
                        break
                    continue

                if item is None:
                    break

                file_path, file_name, mtime, size, features, tensor = item
                self.current_file = file_name
                try:
                    res = tagger.predict_and_save_tensor(
                        tensor, features, file_path, mtime, size,
                        save_sidecar=save_sidecar, db_conn=db_conn
                    )
                    if res:
                        self.indexed_files += 1
                        self.remaining_files -= 1
                        self.processed_in_session += 1
                        batch_counter += 1
                    else:
                        self.error_count += 1
                except Exception as ex:
                    self.error_count += 1
                    print(f"[SCANNER] Error tagging {file_name}: {ex}")

                # Пакетный коммит транзакции каждые batch_size файлов
                if batch_counter >= batch_size:
                    db_conn.commit()
                    batch_counter = 0

            if batch_counter > 0:
                db_conn.commit()

        finally:
            db_conn.close()
            producer_thread.join(timeout=2.0)
            self.is_running = False
            self.stop_requested = False
            print(f"[SCANNER] Finished session. Processed: {self.processed_in_session}, Errors: {self.error_count}")

def run_cli():
    import argparse
    parser = argparse.ArgumentParser(description="High-Speed DirectML Media Scanner & Tagger")
    parser.add_argument("--dir", default=r"C:\Users\Admin\Pictures\Amazing Stray 3.4 final", help="Target media folder")
    parser.add_argument("--batch", type=int, default=20, help="DB commit batch size")
    parser.add_argument("--no-sidecar", action="store_true", help="Don't write .txt sidecars")
    args = parser.parse_args()

    scanner = ScannerManager()
    started, msg = scanner.start(directory=args.dir, save_sidecar=not args.no_sidecar, batch_size=args.batch)
    print(msg)
    if not started:
        return

    try:
        while scanner.is_running:
            time.sleep(1.0)
            st = scanner.get_status()
            eta_min = round(st['eta_sec'] / 60, 1)
            print(f"\r[{st['indexed_files']}/{st['total_files']}] {st['percent']}% | {st['fps']} fps | ETA: {eta_min}m | {st['current_file'][:40]}", end="", flush=True)
        print("\nScan completed.")
    except KeyboardInterrupt:
        print("\nStopping scanner...")
        scanner.stop()
        while scanner.is_running:
            time.sleep(0.2)
        print("Scanner stopped safely.")

if __name__ == "__main__":
    run_cli()
