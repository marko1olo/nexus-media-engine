# 🎛️ Nexus Media Engine — Web Audio API DSP & 60 FPS FFT Spectrum

[![Live Demo](https://img.shields.io/badge/Live_Showcase-GitHub_Pages-a855f7?style=for-the-badge&logo=github)](https://marko1olo.github.io/nexus-media-engine/)
[![PWA Ready](https://img.shields.io/badge/PWA-Installable-22c55e?style=for-the-badge&logo=pwa)](https://marko1olo.github.io/nexus-media-engine/manifest.json)
[![AI Index](https://img.shields.io/badge/LLM_Search-llms.txt-38bdf8?style=for-the-badge)](https://marko1olo.github.io/nexus-media-engine/llms.txt)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?style=for-the-badge&logo=typescript)](https://www.typescriptlang.org/)
[![Web Audio](https://img.shields.io/badge/Web_Audio-API_DSP-00f5a0?style=for-the-badge)](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API)

A high-performance digital signal processing (DSP) synthesizer and real-time audio visualization workbench built on the native Web Audio API, featuring multi-oscillator polyphony, BiquadFilter parametric EQ racks, ADSR envelope shaping, and 60 FPS GPU-accelerated FFT spectral analyzers.

---

## 🏛️ Audio Signal Processing Graph

```mermaid
graph LR
    Osc[Multi-Wave Oscillator Node] --> ADSR[GainNode / ADSR Envelope]
    ADSR --> Biquad[BiquadFilterNode EQ Rack]
    Biquad --> Pan[StereoPannerNode 3D Spatial]
    Pan --> Comp[DynamicsCompressorNode]
    Comp --> FFT[AnalyserNode 2048-bin FFT]
    FFT --> Dest[AudioDestination (Speakers)]
    FFT --> Canvas[60 FPS FFT Canvas Visualizer]
```

---

## 🔬 Core Capabilities

1. **Polyphonic Multi-Wave Synth:** Sine, Triangle, Square, and Sawtooth oscillators with pitch glide and detune modulation.
2. **Parametric Biquad EQ:** Real-time Lowpass, Highpass, Bandpass, Notch, and Peaking filter algorithms.
3. **ADSR Envelope Generator:** Attack, Decay, Sustain, Release timing curve shaper.
4. **Spectral Analyzer:** 2048-sample FFT frequency bin renderer with phosphor decay and logarithmic pitch scaling.

---

### 👨‍💻 Lead Architect
**Адольф Петушков (Adolf Petushkov)** — High-Concurrency Systems & Audio DSP Engineering.  
GitHub: [@marko1olo](https://github.com/marko1olo)
