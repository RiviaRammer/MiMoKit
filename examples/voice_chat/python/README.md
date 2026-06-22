# Voice Chat Python 实现

[中文](README.md) | [English](README_EN.md)

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置API Key

```bash
cp config_example.py config.py
```

编辑 `config.py`，填写从 [Xiaomi MiMo控制台](https://platform.xiaomimimo.com) 获得的API Key。

### 3. 运行程序

```bash
# 语音对话模式
python example.py

# 测试环境噪音
python example.py noise
```


## 配置说明

在 `config.py` 中可以调整以下参数：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `API_KEY` | Xiaomi MiMo API Key | - |
| `TTS_VOICE` | TTS语音角色 | "冰糖" |
| `SYSTEM_PROMPT` | 系统提示词 | 智能助手提示词 |
| `SILENCE_THRESHOLD` | 静音阈值 | 800 |
| `SILENCE_DURATION` | 静音时长（秒） | 2.0 |
| `MIN_RECORD_DURATION` | 最小录音时长（秒） | 0.5 |
| `START_DURATION` | 开始录音持续时间（秒） | 0.1 |
| `TTS_STREAMING` | 是否使用流式播放 | True |

---

## 文件结构

```text
python/
├── example.py              # 主程序入口
├── xiaomi_mimo_asr.py      # 核心库（ASR、Chat、TTS）
├── config.py               # 配置文件（需要创建）
├── config_example.py       # 配置示例
├── requirements.txt        # 依赖列表
└── README.md               # 说明文档
```

---

## 使用说明

1. **语音对话**：运行 `python example.py`，开始语音对话
2. **噪音测试**：运行 `python example.py noise`，测试环境噪音水平
3. **停止程序**：按 `Ctrl+C` 停止程序
