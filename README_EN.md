# MiMoKit

[中文](README.md) | [English](README_EN.md)

Based on Xiaomi MiMo Large Language Model

Supports:

- ASR (Automatic Speech Recognition)
- Chat (Text Conversation)
- TTS (Text-to-Speech)
- PC, Linux, Embedded Devices (M5Stack, ESP32, etc.)

---

## API Key

This project does not provide servers. You need to use your own API Key.
Please support this project by using my Xiaomi MiMo invitation link. Both of us will receive experience credits:
Invitation Code: G7PJPS
Registration: https://platform.xiaomimimo.com?ref=G7PJPS

---

## Project Goal

MiMoKit provides a collection of ready-to-run Agent examples.

---

## Project Structure

```text
MiMoKit/
│
├─ examples/                 # Example projects
│  │
│  ├─ voice_chat/            # Voice chat assistant
│  └─ ssh_agent/             # SSH operations assistant
│
└─ docs/                     # Documentation
```

---

## Examples and Devices

Each example can contain multiple platform implementations.

For example:

```text
voice_chat/
├─ python/
├─ m5stack_tab5/
└─ m5stack_CardputerAdv/
```

The development logic remains consistent; the only differences are the running devices and hardware interfaces.

---

## Example List

| Example | Description |
|---------|-------------|
| voice_chat | Speech recognition + LLM + TTS |
| ssh_agent | Voice-controlled Linux server |

More Agent examples will be added continuously.
