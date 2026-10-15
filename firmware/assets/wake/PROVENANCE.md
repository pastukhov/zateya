# Zateya wake model

User-trained model from https://microwakeword.com/train?job=1279, supplied as
`затея.zip` on 2026-10-15. Original manifest and provider README are retained.
The firmware binary is renamed to `zateya.tflite`; `original-manifest.json`
records the original export, not a path used by the firmware build.

SHA-256: `b540d5fb2aef7148a8d8774d16b91b6d49e8673ae2ad5431cfbdc30c0a2702b7`.
60840 bytes; TFLite schema 3. Input int8 [1,3,40], scale 0.10196079,
zero point -128. Output uint8 [1,1], scale 1/256, zero point 0.
Operator/version list: CALL_ONCE/1, VAR_HANDLE/1, RESHAPE/1,
READ_VARIABLE/1, CONCATENATION/2, STRIDED_SLICE/2, ASSIGN_VARIABLE/1,
CONV_2D/3, DEPTHWISE_CONV_2D/3, SPLIT_V/2, FULLY_CONNECTED/4, LOGISTIC/2,
QUANTIZE/1. Inspected directly from the FlatBuffer.

Frontend: 16 kHz, 30 ms window, 10 ms step, 40 features; parameters and
integer feature scaling match ESPHome 2026.9.1 microWakeWord. Runtime pins
esp-tflite-micro 1.3.3~1, esp-nn 1.1.2, esp-micro-speech-features 1.2.3.
Arena from export: 32000 bytes; additional variable arena: 4096 bytes.
Threshold 0.5, mean of 5 probabilities. Initial/reset warm-up is 100 model
invocations (3 seconds); detection is disabled during playback and recording.
The archive has no separate model licence; this is the user's supplied model.
Runtime dependencies retain their upstream licences.

Generated include: `firmware/include/voice_wake_model_data.h`; its bytes must
match the binary above. No server addresses, tokens or audio cues are embedded.
Reference: https://github.com/esphome/esphome/tree/2026.9.1/esphome/components/micro_wake_word
