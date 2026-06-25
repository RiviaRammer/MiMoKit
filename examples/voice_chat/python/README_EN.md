# Voice Chat Python

[中文](README.md) | [English](README_EN.md)

Python voice chat demo for Xiaomi MiMo. It supports VAD recording, ASR, LLM chat, TTS playback, and an optional wake word.

## Quick Start

```bash
pip install -r requirements.txt
cp config_example.py config.py
python main.py
```

## Configuration

```python
# TTS
TTS_MODEL = "mimo-v2.5-tts"  # mimo-v2.5-tts, mimo-v2.5-tts-voicedesign, mimo-v2.5-tts-voiceclone
TTS_VOICE = "冰糖"
TTS_STREAMING = True
TTS_VOICEDESIGN_DESCRIPTION = "Young female, extreme close-up ..."
TTS_VOICECLONE_FILEPATH = "./xxx.mp3"
```

TTS model behavior:

- `mimo-v2.5-tts`: preset voice, uses `TTS_VOICE`.
- `mimo-v2.5-tts-voicedesign`: text-based voice design, uses `TTS_VOICEDESIGN_DESCRIPTION`.
- `mimo-v2.5-tts-voiceclone`: voice cloning from a local `.mp3` or `.wav`, uses `TTS_VOICECLONE_FILEPATH`.

## LLM Config

`LLM_SYSTEM_PROMPT` is the persistent role/instruction for the whole conversation. It is stored as a `system` message and affects every later turn.

## Wake Word

When wake word mode is enabled, ASR text is sent to the LLM only if it contains `WAKE_WORD` or the session is still awake. After each LLM reply and TTS playback, the awake state is extended by `WAKE_ACTIVE_SECONDS`.

```python
WAKE_WORD_ENABLED = False
WAKE_WORD = "小爱"
WAKE_ACTIVE_SECONDS = 8.0
```
