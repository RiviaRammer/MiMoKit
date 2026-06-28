# Cardputer 语音对话

[中文](README.md) | [English](README_EN.md)

这是面向 M5Stack Cardputer 的 Arduino 语音对话示例。流程为按键录音、流式 ASR、流式 LLM、流式 TTS 播放。

## 特性

- 按 `BtnA/G0` 开始一轮语音输入。
- 使用简单 VAD 自动判断语音开始和结束。

## 硬件与限制

本项目可用于Cardputer v1.1、 Cardputer-Adv。

Cardputer 使用 ESP32-S3FN8，没有 PSRAM。当前默认录音上限为 5 秒，`REC_SAMPLE_RATE` 为 12 kHz，录音 PCM 最大约 120 KB。

长文本 TTS 仍受服务端实时生成速度影响。如果服务端音频产出慢于实际播放速度，设备侧只能通过更深缓冲缓解，无法完全消除等待。

## 配置

1. 复制 `config_example.h` 为 `config.h`。
2. 填写 Wi-Fi、`MIMO_API_KEY`、模型和 TTS voice。

常用模型配置：

```cpp
#define ASR_MODEL "mimo-v2.5-asr"
#define LLM_MODEL "mimo-v2.5-pro"
#define TTS_MODEL "mimo-v2.5-tts"
```

## Arduino 环境

建议使用 M5Stack ESP32 board package `3.2.6`。`3.3.7` 在 Cardputer 麦克风采集上曾出现固定采样值问题。

建议板卡设置：

- Board: `M5Cardputer`
- CPU Frequency: `240MHz (WiFi)`
- Flash Size: `8MB (64Mb)`
- Partition Scheme: `8M with spiffs (3MB APP/1.5MB SPIFFS)`
- PSRAM: `Disabled`

## 运行

1. 烧录后等待 Wi-Fi 连接。
2. 屏幕显示 Ready 后按 `BtnA/G0`。
3. 看到 Listening/Speak now 后开始说话。
4. 静音超过阈值后自动停止录音，进入 ASR、LLM、TTS。