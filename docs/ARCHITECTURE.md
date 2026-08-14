# Nexus Media Engine — Architecture Specification

## 1. Audio Processing Graph
Built on native Web Audio API nodes with 32-bit floating point precision at 48 kHz.

```mermaid
graph LR
    Source[OscillatorNode / AudioBufferSource] --> Biquad[BiquadFilterNode Multi-Type EQ]
    Biquad --> ADSR[GainNode Envelope Shaper]
    ADSR --> Panner[StereoPannerNode 3D Spatial]
    Panner --> Comp[DynamicsCompressorNode]
    Comp --> Analyser[AnalyserNode 2048 FFT]
    Analyser --> Output[AudioContext Destination]
```

## 2. FFT Spectral Analyzer Formula
Frequency bin resolution: $\Delta f = \frac{f_s}{N} = \frac{48000}{2048} \approx 23.44\text{ Hz/bin}$.
