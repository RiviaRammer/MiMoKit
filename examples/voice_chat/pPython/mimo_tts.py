import base64
import io
import json
import queue
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import requests


def default_base_url_for_key(api_key: str) -> str:
    if (api_key or "").startswith("tp-"):
        return "https://token-plan-cn.xiaomimimo.com/v1"
    return "https://api.xiaomimimo.com/v1"


def auth_headers_for_key(api_key: str, base_url: str) -> Dict[str, str]:
    if (api_key or "").startswith("tp-") or "token-plan" in (base_url or ""):
        return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return {"api-key": api_key, "Content-Type": "application/json"}


class MiMoTTS:
    MODELS = {
        "standard": "mimo-v2.5-tts",
        "voicedesign": "mimo-v2.5-tts-voicedesign",
        "voiceclone": "mimo-v2.5-tts-voiceclone",
    }

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "mimo-v2.5-tts",
        voice: str = "冰糖",
        voice_design_description: str = "",
        voice_clone_filepath: str = "",
    ):
        self.api_key = api_key
        self.base_url = (base_url or default_base_url_for_key(api_key)).rstrip("/")
        self.model = self.MODELS.get(model, model)
        self.voice = voice
        self.voice_design_description = voice_design_description
        self.voice_clone_filepath = voice_clone_filepath

    def synthesize(self, text: str) -> Dict[str, Any]:
        try:
            body = self._build_body(text, audio_format="wav", stream=False)
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=auth_headers_for_key(self.api_key, self.base_url),
                timeout=60,
            )
            response.raise_for_status()
            choices = response.json().get("choices", [])
            if not choices:
                return {"success": False, "audio_data": None, "error": "API returned no choices"}
            audio_b64 = choices[0].get("message", {}).get("audio", {}).get("data", "")
            if not audio_b64:
                return {"success": False, "audio_data": None, "error": "response did not include audio data"}
            return {"success": True, "audio_data": base64.b64decode(audio_b64), "error": None}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "audio_data": None, "error": self._error_message(exc)}
        except Exception as exc:
            return {"success": False, "audio_data": None, "error": str(exc)}

    def play(self, text: str):
        try:
            import pyaudio
            import wave
        except ImportError:
            raise ImportError("pyaudio is required: pip install pyaudio")

        result = self.synthesize(text)
        if not result.get("success"):
            print(f"[TTS] failed: {result.get('error')}")
            return

        wf = wave.open(io.BytesIO(result["audio_data"]), "rb")
        p = pyaudio.PyAudio()
        stream = p.open(format=p.get_format_from_width(wf.getsampwidth()), channels=wf.getnchannels(), rate=wf.getframerate(), output=True)
        try:
            data = wf.readframes(1024)
            while data:
                stream.write(data)
                data = wf.readframes(1024)
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            wf.close()

    def play_streaming(self, text: str, chunk_frames: int = 1024) -> Dict[str, Any]:
        try:
            import pyaudio
        except ImportError:
            raise ImportError("pyaudio is required: pip install pyaudio")

        try:
            body = self._build_body(text, audio_format="pcm16", stream=True)
        except Exception as exc:
            print(f"[TTS] failed: {exc}")
            return {"success": False, "chunks": 0, "pcm_bytes": 0, "failed": True, "error": str(exc)}

        sample_rate = 24000
        pcm_queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=512)
        state = {"chunks": 0, "pcm_bytes": 0, "failed": False}

        def player():
            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=sample_rate, output=True, frames_per_buffer=chunk_frames)
            try:
                while True:
                    pcm = pcm_queue.get()
                    if pcm is None:
                        break
                    stream.write(pcm)
            finally:
                stream.stop_stream()
                stream.close()
                p.terminate()

        player_thread = threading.Thread(target=player, name="MiMoTTSPlayer", daemon=True)
        player_thread.start()

        try:
            with requests.post(
                f"{self.base_url}/chat/completions",
                json=body,
                headers=auth_headers_for_key(self.api_key, self.base_url),
                stream=True,
                timeout=60,
            ) as response:
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
                    audio_b64 = self._find_audio_b64(event)
                    if not audio_b64:
                        continue
                    pcm = base64.b64decode(audio_b64)
                    if len(pcm) % 2:
                        pcm = pcm[:-1]
                    if pcm:
                        state["chunks"] += 1
                        state["pcm_bytes"] += len(pcm)
                        pcm_queue.put(pcm)
        except requests.exceptions.RequestException as exc:
            state["failed"] = True
            print(f"[TTS] failed: {self._error_message(exc)}")
        finally:
            pcm_queue.put(None)
            player_thread.join()

        return {"success": state["pcm_bytes"] > 0 and not state["failed"], **state}

    def _build_body(self, text: str, audio_format: str, stream: bool) -> Dict[str, Any]:
        audio = {"format": audio_format}
        user_content = ""

        if self.model == "mimo-v2.5-tts":
            audio["voice"] = self.voice
        elif self.model == "mimo-v2.5-tts-voicedesign":
            user_content = self.voice_design_description
            audio["optimize_text_preview"] = True
        elif self.model == "mimo-v2.5-tts-voiceclone":
            audio["voice"] = self._load_voice_clone_data_url()
        else:
            audio["voice"] = self.voice

        body = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": text},
            ],
            "audio": audio,
        }
        if stream:
            body["stream"] = True
        return body

    def _load_voice_clone_data_url(self) -> str:
        path = Path(self.voice_clone_filepath)
        if not path.exists():
            raise FileNotFoundError(f"voice clone file does not exist: {self.voice_clone_filepath}")
        ext = path.suffix.lower()
        if ext == ".wav":
            mime_type = "audio/wav"
        elif ext == ".mp3":
            mime_type = "audio/mpeg"
        else:
            raise ValueError("voice clone file must be .wav or .mp3")
        voice_b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{mime_type};base64,{voice_b64}"

    @staticmethod
    def _find_audio_b64(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            audio = obj.get("audio")
            if isinstance(audio, dict) and isinstance(audio.get("data"), str):
                return audio["data"]
            for value in obj.values():
                found = MiMoTTS._find_audio_b64(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = MiMoTTS._find_audio_b64(item)
                if found:
                    return found
        return None

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
