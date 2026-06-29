# Tab5 Arduino Voice Chat

Arduino voice-chat example for M5Stack Tab5. This version follows the Cardputer-Adv flow: tap-to-talk recording, streaming ASR, streaming LLM, and streaming TTS playback.

## Differences from Cardputer-Adv

- Tab5 has no G0/BtnA start button, so a screen tap starts a turn.
- During recording, tap the screen again to cancel after speech has started.
- During TTS playback, tap the screen to interrupt the current reply and automatically enter the next recording turn.

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

Recommended board:

- Board: `M5Tab5`
- PSRAM: `Enabled`
- Partition Scheme: `Default (2 x 6.5 MB app, 3.6 MB SPIFFS)`

## Usage

1. Flash the sketch and wait for Wi-Fi.
2. When Ready is shown, tap the screen.
3. Start speaking when Listening/Speak now is shown.
4. Recording stops after silence, then ASR, LLM, and TTS run in sequence.
