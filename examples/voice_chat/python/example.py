"""
小米MiMo 语音对话示例

使用方法:
  python example.py        - 语音对话模式
  python example.py noise  - 测试环境噪音
"""

import sys
import os
from xiaomi_mimo_asr import (
    XiaomiMiMoASR, MiMoChat, MiMoTTS, RealtimeASR,
    API_KEY, TTS_VOICE, SYSTEM_PROMPT
)
from config import SILENCE_THRESHOLD, SILENCE_DURATION, MIN_RECORD_DURATION, START_DURATION, TTS_STREAMING


def get_api_config():
    api_key = os.environ.get("XIAOMI_API_KEY") or API_KEY
    base_url = os.environ.get("XIAOMI_BASE_URL") or None
    return api_key, base_url


def chat_mode():
    """语音对话模式"""
    # 创建实例
    api_key, base_url = get_api_config()
    asr = XiaomiMiMoASR(api_key=api_key, base_url=base_url)
    chat = MiMoChat(api_key=api_key, base_url=base_url, system_prompt=SYSTEM_PROMPT)
    tts = MiMoTTS(api_key=api_key, base_url=base_url, voice=TTS_VOICE)
    realtime = RealtimeASR(asr, chat=chat, tts=tts, tts_streaming=TTS_STREAMING)
    
    print("语音对话模式 (按Ctrl+C停止)")
    print("-" * 30)
    
    # 开始对话
    realtime.start(
        silence_threshold=SILENCE_THRESHOLD,
        silence_duration=SILENCE_DURATION,
        min_record_duration=MIN_RECORD_DURATION,
        start_duration=START_DURATION
    )
    realtime.wait()
    print("\n已停止")


def noise_mode():
    """测试环境噪音"""
    RealtimeASR.test_noise(duration=5)


def tts_mode():
    text = " ".join(sys.argv[2:]).strip()
    if not text:
        text = "脉冲星是一种特殊的中子星。它高速自转，并像宇宙中的灯塔一样发出规律的脉冲信号。"
    api_key, base_url = get_api_config()
    tts = MiMoTTS(api_key=api_key, base_url=base_url, voice=TTS_VOICE)
    tts.play(text)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "noise":
        noise_mode()
    elif len(sys.argv) > 1 and sys.argv[1] == "tts":
        tts_mode()
    else:
        chat_mode()
