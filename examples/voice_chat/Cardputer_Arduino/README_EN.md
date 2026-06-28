# Cardputer Voice Chat

[中文](README.md) | [English](README_EN.md)

Arduino voice-chat example for M5Stack Cardputer-Adv. The flow is push-to-talk recording, streaming ASR, streaming LLM, and streaming TTS playback.

## Features

- Press `BtnA/G0` to start one voice turn.
- Simple VAD detects speech start and end.

## Hardware Notes

This project can be used with Cardputer v1.1 and Cardputer-Adv.

Cardputer uses ESP32-S3FN8 and has no PSRAM. The default recording limit is 5 seconds. With `REC_SAMPLE_RATE` at 12 kHz, the maximum recorded PCM buffer is about 120 KB.

Long TTS replies are still limited by server-side audio generation speed. If the server produces audio slower than real-time playback, the device can only reduce the wait with deeper buffering; it cannot eliminate it completely.

## Configuration

1. Copy `config_example.h` to `config.h`.
2. Fill in Wi-Fi, `MIMO_API_KEY`, model names, and TTS voice.

Typical model settings:

```cpp
#define ASR_MODEL "mimo-v2.5-asr"
#define LLM_MODEL "mimo-v2.5-pro"
#define TTS_MODEL "mimo-v2.5-tts"
```

## Arduino Setup

Use M5Stack ESP32 board package `3.2.6`. Version `3.3.7` has shown bad Cardputer mic capture behavior, returning a nearly constant sample value.

Recommended board settings:

- Board: `M5Cardputer`
- CPU Frequency: `240MHz (WiFi)`
- Flash Size: `8MB (64Mb)`
- Partition Scheme: `8M with spiffs (3MB APP/1.5MB SPIFFS)`
- PSRAM: `Disabled`

## Usage

1. Flash the sketch and wait for Wi-Fi.
2. When Ready is shown, press `BtnA/G0`.
3. Start speaking when Listening/Speak now is shown.
4. Recording stops after silence, then ASR, LLM, and TTS run in sequence.
