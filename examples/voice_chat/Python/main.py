import config
from mimo_asr import RealtimeASR, XiaomiMiMoASR
from mimo_llm import MiMoChat
from mimo_tts import MiMoTTS


def build_clients():
    asr = XiaomiMiMoASR(
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
        model=config.ASR_MODEL,
        streaming=config.ASR_STREAMING,
    )
    chat = MiMoChat(
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
        model=config.LLM_MODEL,
        system_prompt=config.LLM_SYSTEM_PROMPT,
    )
    tts = MiMoTTS(
        api_key=config.API_KEY,
        base_url=config.BASE_URL,
        model=config.TTS_MODEL,
        voice=config.TTS_VOICE,
        voice_design_description=config.TTS_VOICEDESIGN_DESCRIPTION,
        voice_clone_filepath=config.TTS_VOICECLONE_FILEPATH,
    )
    return asr, chat, tts


def chat_mode():
    asr, chat, tts = build_clients()
    realtime = RealtimeASR(
        asr,
        chat=chat,
        tts=tts,
        tts_streaming=config.TTS_STREAMING,
        wake_word_enabled=config.WAKE_WORD_ENABLED,
        wake_word=config.WAKE_WORD,
        wake_active_seconds=config.WAKE_ACTIVE_SECONDS,
    )

    print("Voice chat mode. Press Ctrl+C to stop.")
    print(f"ASR model={config.ASR_MODEL}, language={config.ASR_LANGUAGE}, streaming={config.ASR_STREAMING}")
    print("-" * 30)

    realtime.start(
        language=config.ASR_LANGUAGE,
        silence_threshold=config.SILENCE_THRESHOLD,
        silence_duration=config.SILENCE_DURATION,
        min_record_duration=config.MIN_RECORD_DURATION,
        start_duration=config.START_DURATION,
    )
    realtime.wait()
    print("\nStopped.")


def noise_mode():
    RealtimeASR.test_noise(duration=5)


def main():
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else "chat"
    if command == "noise":
        noise_mode()
    else:
        chat_mode()


if __name__ == "__main__":
    main()
