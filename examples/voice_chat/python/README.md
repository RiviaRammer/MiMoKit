# Voice Chat Python

[中文](README.md) | [English](README_EN.md)

这是 Xiaomi MiMo 的 Python 语音对话示例，支持麦克风 VAD 录音、ASR、LLM 对话、TTS 播放和可选唤醒词。

## 快速开始

```bash
pip install -r requirements.txt
cp config_example.py config.py
python main.py
```

`python main.py noise` 可用于测试环境噪音，辅助调整 `SILENCE_THRESHOLD`。

## 配置

```python
# TTS
TTS_MODEL = "mimo-v2.5-tts"  # mimo-v2.5-tts, mimo-v2.5-tts-voicedesign, mimo-v2.5-tts-voiceclone
TTS_VOICE = "冰糖"
TTS_STREAMING = True
TTS_VOICEDESIGN_DESCRIPTION = "Young female, extreme close-up ..."
TTS_VOICECLONE_FILEPATH = "./xxx.mp3"
```

TTS 三种模型的配置含义：

- `mimo-v2.5-tts`：使用预置音色，读取 `TTS_VOICE`。
- `mimo-v2.5-tts-voicedesign`：使用文本设计音色，读取 `TTS_VOICEDESIGN_DESCRIPTION`。
- `mimo-v2.5-tts-voiceclone`：使用音色复刻，读取 `TTS_VOICECLONE_FILEPATH`，支持 `.mp3` 或 `.wav`。

## LLM 配置

`LLM_SYSTEM_PROMPT` 是系统提示词，用来定义整段对话的长期规则和角色设定，例如“用简洁中文回答，不要使用 Markdown”。它会作为 `system` 消息保留在会话历史里，影响后续每一轮对话。

## 唤醒词

启用唤醒词后，只有 ASR 文本包含 `WAKE_WORD`，或当前仍处于唤醒状态时，才会把 ASR 文本发送给 LLM。每次 LLM 回复并完成 TTS 播放后，唤醒状态会继续维持 `WAKE_ACTIVE_SECONDS` 秒。

```python
WAKE_WORD_ENABLED = False
WAKE_WORD = "小爱"
WAKE_ACTIVE_SECONDS = 8.0
```
