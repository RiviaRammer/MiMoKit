# Tab5 Arduino 语音对话

[中文](README.md) | [English](README_EN.md)

这是面向 M5Stack Tab5 的 Arduino 语音对话示例。流程沿用 Cardputer 版本：点按开始录音、流式 ASR、流式 LLM、流式 TTS 播放。

## 与 Cardputer-Adv 的差异

- Tab5 没有 G0/BtnA 启动按钮，改为点按屏幕开始一轮对话。
- 录音中检测到语音后，可再次点按屏幕取消本次录音。
- TTS 播放中点按屏幕会打断当前播报，并自动进入下一轮录音。

## 配置

1. 复制 `config_example.h` 为 `config.h`。
2. 填写 Wi-Fi、`MIMO_API_KEY`、模型名和 TTS voice。

常用模型配置：

```cpp
#define ASR_MODEL "mimo-v2.5-asr"
#define LLM_MODEL "mimo-v2.5-pro"
#define TTS_MODEL "mimo-v2.5-tts"
```

## Arduino 环境

推荐板卡：

- Board: `M5Tab5`
- PSRAM: `Enabled`
- Partition Scheme: `Default (2 x 6.5 MB app, 3.6 MB SPIFFS)`

## 运行

1. 烧录后等待 Wi-Fi 连接。
2. 屏幕显示 Ready 后点按屏幕。
3. 看到 Listening/Speak now 后开始说话。
4. 静音超过阈值后自动停止录音，并进入 ASR、LLM、TTS。
