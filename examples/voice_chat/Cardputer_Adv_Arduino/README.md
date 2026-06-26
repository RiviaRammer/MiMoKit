# Cardputer-Adv Arduino 语音对话

[中文](README.md) | [English](README_EN.md)

这是面向 M5Stack Cardputer-Adv 的 Arduino 语音对话示例。流程为按键录音、流式 ASR、流式 LLM、流式 TTS 播放。

## 特性

- 按 `BtnA/G0` 开始一轮语音输入。
- 使用简单 VAD 自动判断语音开始和结束。
- ASR 上传采用流式 base64 写入，避免构造超大 JSON 字符串。
- ASR、LLM、TTS 响应均按 SSE 流式读取。
- Cardputer-Adv 音频按半双工处理：录音前关闭扬声器，播放前关闭麦克风。
- TTS 使用播放队列缓冲，并在 ASR 完成后释放录音 PCM，降低无 PSRAM 设备上的播放抖动。

## 硬件与限制

Cardputer-Adv 使用 ESP32-S3FN8，没有 PSRAM。当前默认录音上限为 5 秒，`REC_SAMPLE_RATE` 为 12 kHz，录音 PCM 最大约 120 KB。ASR 完成后会释放这块内存，TTS 阶段再申请播放队列。

长文本 TTS 仍受服务端实时生成速度影响。如果服务端音频产出慢于实际播放速度，设备侧只能通过更深缓冲缓解，无法完全消除等待。

## 配置

1. 复制 `config_example.h` 为 `config.h`。
2. 填写 Wi-Fi、`MIMO_API_KEY`、模型和 TTS voice。
3. `config.h` 已被 `../.gitignore` 忽略，不要提交真实密钥。

常用模型配置：

```cpp
#define ASR_MODEL "mimo-v2.5-asr"
#define LLM_MODEL "mimo-v2.5-pro"
#define TTS_MODEL "mimo-v2.5-tts"
```

## Arduino 环境

建议使用 M5Stack ESP32 board package `3.2.6`。`3.3.7` 在 Cardputer-Adv 麦克风采集上曾出现固定采样值问题。

安装 board package：

```powershell
arduino-cli core install m5stack:esp32@3.2.6 --additional-urls https://m5stack.oss-cn-shenzhen.aliyuncs.com/resource/arduino/package_m5stack_index.json
```

建议板卡设置：

- Board: `M5Cardputer`
- CPU Frequency: `240MHz (WiFi)`
- Flash Size: `8MB (64Mb)`
- Partition Scheme: `8M with spiffs (3MB APP/1.5MB SPIFFS)`
- PSRAM: `Disabled`

默认分区的 APP 空间偏小，可能出现 `text section exceeds available space`。

编译示例：

```powershell
arduino-cli compile --fqbn "m5stack:esp32:m5stack_cardputer:FlashSize=8M,PartitionScheme=default_8MB" .\examples\voice_chat\Cardputer_Adv_Arduino
```

## 运行

1. 烧录后等待 Wi-Fi 连接。
2. 屏幕显示 Ready 后按 `BtnA/G0`。
3. 看到 Listening/Speak now 后开始说话。
4. 静音超过阈值后自动停止录音，进入 ASR、LLM、TTS。

## 调试重点

串口中最关键的是这些字段：

- `[ASR] upload done ... free_heap=...`：判断录音上限是否过大。
- `[TTS] request start ... free_heap=... max_alloc=...`：判断 TTS 队列是否有足够连续内存。
- `[TTS] stream done ... underruns=...`：`underruns=0` 表示播放阶段没有欠载。

如果要继续增加录音长度，优先观察 ASR 上传阶段剩余 heap。不要只看编译时的全局 RAM。
