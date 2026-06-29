import base64
import json
import queue
import re
import struct
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests


def default_base_url_for_key(api_key: str) -> str:
    if (api_key or "").startswith("tp-"):
        return "https://token-plan-cn.xiaomimimo.com/v1"
    return "https://api.xiaomimimo.com/v1"


def auth_headers_for_key(api_key: str, base_url: str) -> Dict[str, str]:
    if (api_key or "").startswith("tp-") or "token-plan" in (base_url or ""):
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return {"api-key": api_key, "Content-Type": "application/json"}


class XiaomiMiMoASR:
    DEFAULT_MODEL = "mimo-v2.5-asr"
    DEFAULT_LANGUAGE = "zh"
    MAX_AUDIO_SIZE = 10 * 1024 * 1024
    SUPPORTED_FORMATS = {".wav", ".mp3"}

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        streaming: bool = False,
        print_streaming_chunks: bool = False,
    ):
        self.api_key = api_key
        self.base_url = (base_url or default_base_url_for_key(api_key)).rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.streaming = streaming
        self.print_streaming_chunks = print_streaming_chunks

    def _get_headers(self) -> Dict[str, str]:
        return auth_headers_for_key(self.api_key, self.base_url)

    def transcribe_file(self, file_path: str, language: str = DEFAULT_LANGUAGE, streaming: Optional[bool] = None) -> Dict[str, Any]:
        try:
            audio_bytes, mime_type = self._read_audio_file(file_path)
        except (FileNotFoundError, ValueError) as exc:
            return {"success": False, "transcript": "", "error": str(exc)}
        return self.transcribe_bytes(audio_bytes, mime_type=mime_type, language=language, streaming=streaming)

    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/wav",
        language: str = DEFAULT_LANGUAGE,
        streaming: Optional[bool] = None,
    ) -> Dict[str, Any]:
        use_streaming = self.streaming if streaming is None else streaming
        if use_streaming:
            return self.transcribe_bytes_streamed(audio_bytes, mime_type=mime_type, language=language)
        return self.transcribe_bytes_once(audio_bytes, mime_type=mime_type, language=language)

    def transcribe_bytes_once(self, audio_bytes: bytes, mime_type: str = "audio/wav", language: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        try:
            body = self._build_request_body(audio_bytes, mime_type, language, stream=False)
            response = requests.post(f"{self.base_url}/chat/completions", json=body, headers=self._get_headers(), timeout=60)
            response.raise_for_status()
            choices = response.json().get("choices", [])
            if not choices:
                return {"success": False, "transcript": "", "error": "API returned no choices"}
            transcript = choices[0].get("message", {}).get("content", "")
            return {"success": True, "transcript": self._clean_text(transcript), "error": None}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "transcript": "", "error": self._error_message(exc)}
        except Exception as exc:
            return {"success": False, "transcript": "", "error": str(exc)}

    def iter_transcript_chunks(self, audio_bytes: bytes, mime_type: str = "audio/wav", language: str = DEFAULT_LANGUAGE) -> Iterable[str]:
        body = self._build_request_body(audio_bytes, mime_type, language, stream=True)
        with requests.post(
            f"{self.base_url}/chat/completions",
            json=body,
            headers=self._get_headers(),
            stream=True,
            timeout=60,
        ) as response:
            response.encoding = "utf-8"
            response.raise_for_status()
            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line.strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                text = self._extract_text_delta(event)
                if text:
                    yield text

    def transcribe_bytes_streamed(self, audio_bytes: bytes, mime_type: str = "audio/wav", language: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        try:
            chunks = []
            for chunk in self.iter_transcript_chunks(audio_bytes, mime_type=mime_type, language=language):
                if self.print_streaming_chunks:
                    print(chunk, end="", flush=True)
                chunks.append(chunk)
            if chunks and self.print_streaming_chunks:
                print()
            return {"success": True, "transcript": self._clean_text("".join(chunks)), "error": None}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "transcript": "", "error": self._error_message(exc)}
        except Exception as exc:
            return {"success": False, "transcript": "", "error": str(exc)}

    def _build_request_body(self, audio_bytes: bytes, mime_type: str, language: str, stream: bool) -> Dict[str, Any]:
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        if len(audio_b64) > self.MAX_AUDIO_SIZE:
            raise ValueError(f"audio file is too large; max base64 size is {self.MAX_AUDIO_SIZE} bytes")
        body = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "input_audio", "input_audio": {"data": f"data:{mime_type};base64,{audio_b64}"}}],
                }
            ],
            "asr_options": {"language": language},
        }
        if stream:
            body["stream"] = True
        return body

    def _read_audio_file(self, file_path: str) -> tuple[bytes, str]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"audio file does not exist: {file_path}")
        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"unsupported audio format: {ext}; supported: {sorted(self.SUPPORTED_FORMATS)}")
        return path.read_bytes(), "audio/mpeg" if ext == ".mp3" else "audio/wav"

    @staticmethod
    def _extract_text_delta(event: Dict[str, Any]) -> str:
        choices = event.get("choices") or []
        if not choices:
            return ""
        choice = choices[0]
        delta = choice.get("delta") or {}
        if isinstance(delta.get("content"), str):
            return delta["content"]
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(choice.get("text"), str):
            return choice["text"]
        return ""

    @staticmethod
    def _clean_text(text: str) -> str:
        return re.sub(r"<[^>]+>", "", text or "").strip()

    @staticmethod
    def _error_message(exc: requests.exceptions.RequestException) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return f"API request failed: {exc}"
        try:
            detail = response.json()
            message = detail.get("error", {}).get("message") or str(exc)
        except Exception:
            message = str(exc)
        return f"API request failed: {message}"


class RealtimeASR:
    def __init__(
        self,
        asr: XiaomiMiMoASR,
        chat=None,
        tts=None,
        tts_streaming: bool = True,
        wake_word_enabled: bool = False,
        wake_word: str = "",
        wake_active_seconds: float = 8.0,
    ):
        self.asr = asr
        self.chat = chat
        self.tts = tts
        self.tts_streaming = tts_streaming
        self.wake_word_enabled = wake_word_enabled
        self.wake_word = wake_word
        self.wake_active_seconds = wake_active_seconds
        self.wake_active_until = 0.0
        self.is_running = False
        self.is_paused = False
        self._threads = []

    def start(
        self,
        callback=None,
        language: str = "zh",
        silence_threshold: float = 500,
        silence_duration: float = 2.0,
        min_record_duration: float = 0.5,
        start_duration: float = 0.3,
    ):
        try:
            import numpy as np
            import pyaudio
        except ImportError:
            raise ImportError("pyaudio and numpy are required: pip install pyaudio numpy")

        self.is_running = True
        audio_queue = queue.Queue()

        def volume(data: bytes) -> float:
            return float(abs(np.frombuffer(data, dtype=np.int16)).mean())

        def record_thread():
            p = pyaudio.PyAudio()
            stream = None
            try:
                stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
                print(f"[REC] microphone ready, threshold={silence_threshold}")
                is_recording = False
                frames = []
                silence_start = None
                over_threshold_start = None
                last_log = 0.0
                pre_buffer = deque(maxlen=24)
                while self.is_running:
                    data = stream.read(1024, exception_on_overflow=False)
                    if self.is_paused:
                        is_recording = False
                        frames = []
                        silence_start = None
                        over_threshold_start = None
                        pre_buffer.clear()
                        continue
                    level = volume(data)
                    now = time.time()
                    if now - last_log > 0.5:
                        if is_recording:
                            duration = len(frames) * 1024 / 16000
                            print(f"\r[REC] recording ({duration:.1f}s) volume={level:.0f}", end="", flush=True)
                        elif over_threshold_start is not None:
                            detected_duration = now - over_threshold_start
                            print(
                                f"\r[REC] detected voice ({detected_duration:.1f}s) "
                                f"(threshold: {level:.0f}/{silence_threshold:.0f})",
                                end="",
                                flush=True,
                            )
                        else:
                            print(
                                f"\r[REC] waiting (threshold: {level:.0f}/{silence_threshold:.0f})",
                                end="",
                                flush=True,
                            )
                        last_log = now
                    if not is_recording:
                        pre_buffer.append(data)
                    if level >= silence_threshold:
                        if not is_recording:
                            if over_threshold_start is None:
                                over_threshold_start = now
                            elif now - over_threshold_start >= start_duration:
                                is_recording = True
                                frames = list(pre_buffer)
                                silence_start = None
                                over_threshold_start = None
                                print("\n[REC] recording started")
                        if is_recording:
                            frames.append(data)
                    else:
                        over_threshold_start = None
                        if is_recording:
                            frames.append(data)
                            silence_start = silence_start or now
                            if now - silence_start >= silence_duration:
                                duration = len(frames) * 1024 / 16000
                                if duration >= min_record_duration:
                                    audio_queue.put(self._pcm_to_wav(b"".join(frames), 16000, 1, 16))
                                    print(f"\n[REC] recording ended, duration={duration:.1f}s")
                                else:
                                    print(f"\n[REC] dropped short audio, duration={duration:.1f}s")
                                is_recording = False
                                frames = []
                                silence_start = None
            except Exception as exc:
                print(f"\n[ERROR] record thread: {exc}")
                self.is_running = False
            finally:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                p.terminate()

        def recognize_thread():
            while self.is_running or not audio_queue.empty():
                try:
                    audio_data = audio_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                print("\n[ASR] sending audio...")
                result = self.asr.transcribe_bytes(audio_data, language=language)
                if not result.get("success"):
                    print(f"[ASR] failed: {result.get('error')}")
                    continue
                transcript = result.get("transcript", "").strip()
                if len(transcript) < 2:
                    print(f"[ASR] ignored short result: {transcript!r}")
                    continue
                print(f"You: {transcript}")
                if callback:
                    callback(transcript)
                if self.chat:
                    if self._should_send_to_llm(transcript):
                        self._reply(transcript)
                    else:
                        print(f"[WAKE] ignored. Say '{self.wake_word}' to wake me.")

        self._threads = [
            threading.Thread(target=record_thread, name="RecordThread", daemon=True),
            threading.Thread(target=recognize_thread, name="RecognizeThread", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        print("Waiting for speech...")
        return self._threads

    def _reply(self, transcript: str):
        self.is_paused = True
        try:
            print("[CHAT] thinking...")
            result = self.chat.chat(transcript)
            if not result.get("success"):
                print(f"[CHAT] failed: {result.get('error')}")
                return
            reply = result.get("reply", "")
            print(f"AI: {reply}")
            if self.tts and reply:
                print("[TTS] playing...")
                if self.tts_streaming:
                    self.tts.play_streaming(reply)
                else:
                    self.tts.play(reply)
            self._extend_wake_state()
        finally:
            time.sleep(0.3)
            self.is_paused = False

    def _should_send_to_llm(self, transcript: str) -> bool:
        if not self.wake_word_enabled:
            return True
        if self.wake_word and self.wake_word in transcript:
            self._extend_wake_state()
            print(f"[WAKE] activated for {self.wake_active_seconds:.1f}s")
            return True
        if time.time() < self.wake_active_until:
            return True
        return False

    def _extend_wake_state(self):
        if self.wake_word_enabled:
            self.wake_active_until = time.time() + self.wake_active_seconds

    def stop(self):
        self.is_running = False

    def wait(self):
        try:
            while self.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int, bits_per_sample: int) -> bytes:
        data_size = len(pcm_data)
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        wav_header = struct.pack("<4sI4s", b"RIFF", 36 + data_size, b"WAVE")
        fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample)
        data_chunk = struct.pack("<4sI", b"data", data_size)
        return wav_header + fmt_chunk + data_chunk + pcm_data

    @staticmethod
    def test_noise(duration: int = 5):
        try:
            import numpy as np
            import pyaudio
        except ImportError:
            raise ImportError("pyaudio and numpy are required: pip install pyaudio numpy")
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
        volumes = []
        print(f"Testing ambient noise for {duration}s. Keep quiet.")
        try:
            for _ in range(0, int(16000 / 1024 * duration)):
                data = stream.read(1024, exception_on_overflow=False)
                level = float(abs(np.frombuffer(data, dtype=np.int16)).mean())
                volumes.append(level)
                print(f"\rvolume={level:.0f}", end="", flush=True)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
        avg = sum(volumes) / len(volumes)
        peak = max(volumes)
        print(f"\navg={avg:.0f}, peak={peak:.0f}, suggested threshold={max(avg * 2, 1500):.0f}")
        return avg, peak
