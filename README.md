<div align="center">
  <h1>🌌 Nexus Media Engine</h1>
  <p><b>The ultimate God-Tier media viewer and slideshow engine.</b></p>
  
  [![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org)
  [![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
  [![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
</div>

<br>

**Nexus Media Engine** is a high-performance, seamless media gallery built for absolute immersion. Originally designed to handle massive local art collections, it evolved into a cinematic slideshow experience featuring zero-latency crossfading, dynamic Ambilight effects, and an interactive audio-visualizer.

If you are tired of standard Windows photo viewers and clunky video players, Nexus 8.0 will redefine how you view your media.

---

## ✨ God-Tier Features

*   🎬 **Zero-Latency Video Crossfade** – Utilizes a dual-video-buffer architecture. While you watch one video, the next is preloaded silently in the background, allowing for perfectly smooth, cinematic transitions without a single millisecond of black screen.
*   🌈 **Dynamic Ambilight Aura** – Real-time canvas-based color extraction analyzes the current media on screen and projects a soft, matching neon glow onto the background, similar to premium smart TVs.
*   🎵 **Audio Spectrum Visualizer** – Drop your MP3s into the `audio/` folder, hit play, and a glowing neon equalizer will pulse perfectly to the beat using the Web Audio API.
*   ✨ **Cinematic Bokeh Particles** – A custom particle engine overlays softly glowing, floating dust particles to give your 2D images and videos stunning 3D depth.
*   🎮 **Gamepad Support** – Fully navigate the gallery, trigger slideshows, and add to favorites using an Xbox or PlayStation controller (HTML5 Gamepad API).
*   🔍 **Free-Cam Pan & Zoom** – Scroll the mouse wheel to zoom up to 10x into any high-res image or video. Click and drag to pan around seamlessly.
*   🎞️ **Interactive Filmstrip** – Hover at the bottom of the player to reveal a sleek, YouTube-style timeline of all your media for instant navigation.
*   ⭐ **Favorites System** – Hit `Y` on your gamepad or click the star icon to instantly save any media to your `FAVORITES/` folder.
*   🗂️ **Smart Video Thumbnails** – Automatically generates lightweight, cached thumbnails for heavy video files using OpenCV to keep the gallery menu butter-smooth.

---

## 🚀 Quick Start (Local Deployment)

This engine is built to run locally on your machine with minimal overhead.

### 1. Prerequisites
You need Python installed on your system.

### 2. Installation
Clone the repository and install the minimal dependencies:
```bash
git clone https://github.com/your-username/nexus-media-engine.git
cd nexus-media-engine
pip install -r requirements.txt
```

### 3. Usage
Simply run the startup script:
```bash
start.bat
```
*(Or run `python app.py` manually)*

The server will start locally and automatically open your default browser to `http://127.0.0.1:5000`.

---

## 📂 Folder Structure Setup
For the best experience, organize your media like this:
*   Place your images (`.jpg`, `.png`, `.webp`) and videos (`.mp4`, `.webm`) into any subfolders within the project directory. The engine will scan and serve them.
*   **Audio**: Create an `audio/` folder and drop your ambient `.mp3` tracks there for the visualizer.
*   **Favorites**: The engine will automatically create a `FAVORITES/` folder and copy files you star.

---

## 🛠️ Tech Stack
*   **Backend**: Python, Flask, OpenCV (for thumbnail generation).
*   **Frontend**: Vanilla HTML5, CSS3 (Glassmorphism), Vanilla JavaScript.
*   **APIs Used**: Canvas API, Web Audio API, Gamepad API.

<div align="center">
  <i>"Не сиди в песочнице. Работай по-взрослому."</i>
</div>
