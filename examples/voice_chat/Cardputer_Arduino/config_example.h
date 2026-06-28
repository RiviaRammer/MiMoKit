#pragma once

// Copy this file to config.h and fill in your values.

#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// Xiaomi MiMo API key. tp-* keys use the token-plan endpoint by default.
#define MIMO_API_KEY "tp-your-key-here"

// Leave empty to auto-select from the API key.
#define MIMO_BASE_URL ""

#define ASR_MODEL "mimo-v2.5-asr"
#define ASR_LANGUAGE "auto"
#define LLM_MODEL "mimo-v2.5-pro"
#define TTS_MODEL "mimo-v2.5-tts"
#define TTS_VOICE "冰糖"

// Keep replies short to reduce MCU memory pressure and TTS latency.
#define SYSTEM_PROMPT "你是一个语音助手，你的回答会通过TTS转成音频。用口语化中文简短回答，不要使用Markdown。"
