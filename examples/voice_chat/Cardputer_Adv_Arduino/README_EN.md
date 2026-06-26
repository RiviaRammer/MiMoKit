# Cardputer-Adv Arduino Voice Chat

[中文](README.md) | [English](README_EN.md)

Arduino voice-chat example for M5Stack Cardputer-Adv. The flow is push-to-talk recording, streaming ASR, streaming LLM, and streaming TTS playback.

## Features

- Press `BtnA/G0` to start one voice turn.
- Simple VAD detects speech start and end.
- ASR upload streams base64 directly to the TLS client instead of building one large JSON string.
- ASR, LLM, and TTS responses are read as streaming SSE.
- Cardputer-Adv audio is treated as half-duplex: the speaker is stopped before recording, and the mic is stopped before playback.
- TTS uses a playback queue. The recorded ASR PCM buffer is released before LLM/TTS to reduce jitter on the no-PSRAM device.

## Hardware Notes

Cardputer-Adv uses ESP32-S3FN8 and has no PSRAM. The default recording limit is 5 seconds. With `REC_SAMPLE_RATE` at 12 kHz, the maximum recorded PCM buffer is about 120 KB. That buffer is freed after ASR, and the TTS playback queue is allocated only during playback.

Long TTS replies are still limited by server-side audio generation speed. If the server produces PCM slower than real-time playback, the device can only hide it with deeper buffering.

## Configuration

1. Copy `config_example.h` to `config.h`.
2. Fill in Wi-Fi, `MIMO_API_KEY`, model names, and TTS voice.
3. `config.h` is ignored by `../.gitignore`; do not commit real credentials.

Typical model settings:

```cpp
#define ASR_MODEL "mimo-v2.5-asr"
#define LLM_MODEL "mimo-v2.5-pro"
#define TTS_MODEL "mimo-v2.5-tts"
```

## Arduino Setup

Use M5Stack ESP32 board package `3.2.6`. Version `3.3.7` has shown bad Cardputer-Adv mic capture behavior, returning a nearly constant sample value.

Install the board package:

```powershell
arduino-cli core install m5stack:esp32@3.2.6 --additional-urls https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/arduino/package_m5stack_index.json
```

Recommended board settings:

- Board: `M5Cardputer`
- CPU Frequency: `240MHz (WiFi)`
- Flash Size: `8MB (64Mb)`
- Partition Scheme: `8M with spiffs (3MB APP/1.5MB SPIFFS)`
- PSRAM: `Disabled`

The default partition may fail with `text section exceeds available space`.

Compile example:

```powershell
arduino-cli compile --fqbn "m5stack:esp32:m5stack_cardputer:FlashSize=8M,PartitionScheme=default_8MB" .\examples\voice_chat\Cardputer_Adv_Arduino
```

## Usage

1. Flash the sketch and wait for Wi-Fi.
2. When Ready is shown, press `BtnA/G0`.
3. Start speaking when Listening/Speak now is shown.
4. Recording stops after silence, then ASR, LLM, and TTS run in sequence.

## Debugging

The most useful serial fields are:

- `[ASR] upload done ... free_heap=...`: checks whether the recording buffer is too large.
- `[TTS] request start ... free_heap=... max_alloc=...`: checks whether the TTS queue has enough contiguous heap.
- `[TTS] stream done ... underruns=...`: `underruns=0` means playback did not starve.

If you increase the recording length, watch the ASR upload heap first. Compile-time global RAM is not enough to judge runtime safety.
