import webview
import ctypes
import win32gui
import urllib.request
import time
import subprocess

def get_workerw():
    progman = win32gui.FindWindow("Progman", None)
    # Send message to progman to spawn WorkerW
    win32gui.SendMessageTimeout(progman, 0x052C, 0, 0, 0, 1000)

    workerw = [None]
    def enum_windows(hwnd, lParam):
        p = win32gui.FindWindowEx(hwnd, 0, "SHELLDLL_DefView", None)
        if p != 0:
            workerw[0] = win32gui.FindWindowEx(0, hwnd, "WorkerW", None)
        return True

    win32gui.EnumWindows(enum_windows, 0)
    return workerw[0]

def set_wallpaper_mode(window):
    # Wait for the window to be created
    time.sleep(2)
    # The title passed to create_window
    hwnd = win32gui.FindWindow(None, "Nexus Media Engine - Wallpaper")
    if hwnd:
        workerw = get_workerw()
        if workerw:
            # Set parent to WorkerW so it sits behind desktop icons
            win32gui.SetParent(hwnd, workerw)
            
            # Maximize the window to cover the screen
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            win32gui.SetWindowPos(hwnd, 0, 0, 0, width, height, 0x0040)
            print("Successfully pinned to Desktop!")
        else:
            print("WorkerW not found!")
    else:
        print("Window not found!")

if __name__ == '__main__':
    # Ensure Flask server is running
    server_process = None
    try:
        urllib.request.urlopen("http://127.0.0.1:5000", timeout=2)
        print("Server is running.")
    except:
        print("Starting Flask server in background...")
        server_process = subprocess.Popen(["python", "app.py"])
        time.sleep(2)

    # Create the webview window
    window = webview.create_window(
        'Nexus Media Engine - Wallpaper',
        'http://127.0.0.1:5000',
        frameless=True,
        fullscreen=True,
        easy_drag=False
    )

    # Run the pinning script shortly after webview starts
    webview.start(set_wallpaper_mode, window, private_mode=False)

    if server_process:
        server_process.terminate()
