# API
API_KEY = "tp-your-key-here"
BASE_URL = None


# ASR
ASR_MODEL = "mimo-v2.5-asr"
ASR_LANGUAGE = "auto"  # zh, en, auto
ASR_STREAMING = True


# LLM
LLM_MODEL = "mimo-v2.5-pro"
# Persistent role/instruction for the whole conversation.
LLM_SYSTEM_PROMPT = "你是一个语音助手，你的回答会通过TTS api转化为音频。用口语化的中文简短回答。请勿使用 Markdown 格式。"


# TTS
TTS_MODEL = "mimo-v2.5-tts"  # mimo-v2.5-tts, mimo-v2.5-tts-voicedesign, mimo-v2.5-tts-voiceclone
TTS_STREAMING = True
# for mimo-v2.5-tts
TTS_VOICE = "冰糖"
# for mimo-v2.5-tts-voicedesign
TTS_VOICEDESIGN_DESCRIPTION = "young woman in her mid-20s, warm and confident."
# for mimo-v2.5-tts-voiceclone
TTS_VOICECLONE_FILEPATH = "./xxx.mp3"


# Wake word
WAKE_WORD_ENABLED = False
WAKE_WORD = "小爱"
WAKE_ACTIVE_SECONDS = 8.0


# Voice activity detection
SILENCE_THRESHOLD = 800.0
SILENCE_DURATION = 2.0
MIN_RECORD_DURATION = 0.8
START_DURATION = 0.25
