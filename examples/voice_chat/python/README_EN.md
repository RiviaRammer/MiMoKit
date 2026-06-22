# Voice Chat Python Implementation

[中文](README.md) | [English](README_EN.md)

---

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Key

```bash
cp config_example.py config.py
```

Edit `config.py` and fill in the API Key obtained from [Xiaomi MiMo Console](https://platform.xiaomimimo.com).

### 3. Run the Program

```bash
# Voice chat mode
python example.py

# Test environment noise
python example.py noise
```

## Configuration

You can adjust the following parameters in `config.py`:

| Parameter | Description | Default Value |
|-----------|-------------|---------------|
| `API_KEY` | Xiaomi MiMo API Key | - |
| `TTS_VOICE` | TTS voice role | "冰糖" |
| `SYSTEM_PROMPT` | System prompt | Smart assistant prompt |
| `SILENCE_THRESHOLD` | Silence threshold | 800 |
| `SILENCE_DURATION` | Silence duration (seconds) | 2.0 |
| `MIN_RECORD_DURATION` | Minimum recording duration (seconds) | 0.5 |
| `START_DURATION` | Start recording duration (seconds) | 0.1 |
| `TTS_STREAMING` | Whether to use streaming playback | True |

---

## File Structure

```text
python/
├── example.py              # Main program entry
├── xiaomi_mimo_asr.py      # Core library (ASR, Chat, TTS)
├── config.py               # Configuration file (needs to be created)
├── config_example.py       # Configuration example
├── requirements.txt        # Dependencies list
└── README.md               # Documentation
```

---

## Usage Instructions

1. **Voice Chat**: Run `python example.py` to start voice chat
2. **Noise Test**: Run `python example.py noise` to test environment noise level
3. **Stop Program**: Press `Ctrl+C` to stop the program
