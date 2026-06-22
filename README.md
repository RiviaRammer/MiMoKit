# MiMoKit

[中文](README.md) | [English](README_EN.md)

基于小米 MiMo 大模型

支持：

- ASR（语音识别）
- Chat（文本对话）
- TTS（语音合成）
- PC、Linux、嵌入式设备接入（M5Stack、ESP32 等）

---

## API Key

本项目不提供服务器，你需要使用自己的API Key  
希望你可以支持本项目，使用我的Xiaomi MiMo邀请链接，我们都可以获得体验金：  
邀请码：G7PJPS  
注册：https://platform.xiaomimimo.com?ref=G7PJPS  

---

## 项目目标

MiMoKit 提供一系列可直接运行的 Agent 示例。

---

## 项目结构

```text
MiMoKit/
│
├─ examples/                 # 示例工程
│  │
│  ├─ voice_chat/            # 语音对话助手
│  └─ ssh_agent/             # SSH运维助手
│
└─ docs/                     # 文档
```

---

## Example 与设备

每个 Example 下可以包含多个平台实现。

例如：

```text
voice_chat/
├─ python/
├─ m5stack_tab5/
└─ m5stack_CardputerAdv/
```

开发逻辑保持一致,区别仅在于运行设备和硬件接口。

---

## 示例列表

| 示例 | 说明 |
|--------|--------|
| voice_chat | 语音识别 + 大模型 + TTS |
| ssh_agent | 语音控制 Linux 服务器 |

后续将持续增加更多 Agent 示例。
