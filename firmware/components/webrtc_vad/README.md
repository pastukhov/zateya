# WebRTC VAD

Portable C sources from https://github.com/wiseman/py-webrtcvad,
tag 2.0.10, commit bb429dac1a686807c69b916f03dd843fa10b0927.
Full upstream MIT/BSD licence is in LICENSE; per-file notices retained.
Only local change in upstream C headers: Xtensa little-endian 32-bit
architecture detection in webrtc/typedefs.h. CMake and library.json are
Zateya integration files. No Python extension is included.
The adapter uses 16 kHz mono PCM16, 10 ms frames, aggressiveness 2.
