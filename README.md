<div align="center">
  <h1>🌌 Nexus Media Engine</h1>
  <p><b>The Ultimate God-Tier Hentai & NSFW Media Viewer</b></p>
  
  [![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org)
  [![Flask](https://img.shields.io/badge/Flask-2.0+-green.svg)](https://flask.palletsprojects.com/)
  [![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
</div>

<br>

**Nexus Media Engine** is a high-performance, seamless media gallery built specifically for absolute immersion in adult art and media collections. Designed to handle massive local hentai/NSFW archives, it turns a standard folder of images into a cinematic slideshow experience.

Drop in your art, throw in some ASMR or moans in MP3 format, and watch the engine sync everything together with zero-latency crossfading, dynamic Ambilight effects, and a neon audio-visualizer that pulses to the sound.

If you are tired of standard Windows photo viewers ruining the vibe, Nexus 8.0 will redefine your immersion.

### 🔥 Sneak Peek
<p align="center">
  <img src="assets/menu.png" width="45%" />
  <img src="assets/player.png" width="45%" />
</p>

---

## ✨ God-Tier Immersive Features

*   🎬 **Zero-Latency Video Crossfade** – Utilizes a dual-video-buffer architecture. While you watch one video/image, the next is preloaded silently in the background, allowing for perfectly smooth, cinematic transitions without a single millisecond of black screen.
*   🌈 **Dynamic Ambilight Aura** – Real-time color extraction analyzes the current art on screen and projects a soft, matching neon glow onto the background, making every image pop with its own atmosphere.
*   🎵 **Audio Spectrum Visualizer** – Drop your `.mp3` tracks (ASMR, moans, ambient) into the `audio/` folder, hit play, and a glowing neon equalizer will pulse perfectly to the audio using the Web Audio API.
*   ✨ **Cinematic Bokeh Particles** – A custom particle engine overlays softly glowing, floating dust particles to give your 2D images and videos stunning 3D depth and atmosphere.
*   🎮 **Gamepad Support** – Fully navigate the gallery, trigger slideshows, and add to favorites using an Xbox or PlayStation controller (HTML5 Gamepad API) — play with one hand, literally.
*   🔍 **Free-Cam Pan & Zoom** – Scroll the mouse wheel to zoom up to 10x into any high-res image to inspect the finest details. Click and drag to pan around seamlessly.
*   🎞️ **Interactive Filmstrip** – Hover at the bottom of the player to reveal a sleek, YouTube-style timeline of all your media for instant navigation.
*   ⭐ **Favorites System** – Hit `Y` on your gamepad or click the star icon to instantly save the best art to your `FAVORITES/` folder for later extraction.
*   🗂️ **Smart Video Thumbnails** – Automatically generates lightweight, cached thumbnails for heavy NSFW video files using OpenCV to keep the gallery menu butter-smooth.

---

## 🚀 Quick Start (Local Deployment)

This engine is built to run entirely locally and privately on your machine. Nothing is ever uploaded to the cloud.

### 1. Prerequisites
You need Python installed on your Windows machine.

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

The server will start locally and automatically open your default browser in full-screen mode to `http://127.0.0.1:5000`.

---

## 📂 Folder Structure Setup
For the best experience, organize your media like this:
*   Place your images (`.jpg`, `.png`, `.webp`) and videos (`.mp4`, `.webm`) into any subfolders within the project directory. The engine will scan and serve them locally.
*   **Audio**: Create an `audio/` folder and drop your `.mp3` tracks there for the visualizer to pick them up.
*   **Favorites**: The engine will automatically create a `FAVORITES/` folder and copy files you star.

---

## 🛠️ Tech Stack
*   **Backend**: Python, Flask, OpenCV (for thumbnail generation).
*   **Frontend**: Vanilla HTML5, CSS3 (Glassmorphism), Vanilla JavaScript.
*   **APIs Used**: Canvas API, Web Audio API, Gamepad API.

<div align="center">
  <i>"Не сиди в песочнице. Работай по-взрослому."</i>
</div>
