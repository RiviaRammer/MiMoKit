"""
小米MiMo V2.5 语音识别与对话模块
支持ASR语音识别、TTS语音合成、对话功能
"""

import base64
import json
import os
import queue
import sys
import threading
import time
import wave
import struct
import re
import requests
from typing import Optional, Dict, Any
from pathlib import Path

# Windows终端启用ANSI支持
if sys.platform == "win32":
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

# ==================== 配置区 ====================

# API密钥
try:
    from config import API_KEY as CONFIG_API_KEY
    from config import TTS_VOICE as CONFIG_TTS_VOICE
    from config import SYSTEM_PROMPT as CONFIG_SYSTEM_PROMPT
except ImportError:
    CONFIG_API_KEY = ""
    CONFIG_TTS_VOICE = None
    CONFIG_SYSTEM_PROMPT = None

API_KEY = os.environ.get("XIAOMI_API_KEY") or CONFIG_API_KEY

# TTS音色 (冰糖/茉莉/苏打/白桦/Mia/Chloe/Milo/Dean)
TTS_VOICE = "冰糖"

# 对话系统预设
SYSTEM_PROMPT = "你是一个智能助手，正在通过语音与用户对话。请用简洁的语言回答，适合语音场景，不要使用markdown格式。"

TTS_VOICE = os.environ.get("XIAOMI_TTS_VOICE") or CONFIG_TTS_VOICE or TTS_VOICE
SYSTEM_PROMPT = os.environ.get("XIAOMI_SYSTEM_PROMPT") or CONFIG_SYSTEM_PROMPT or "You are a helpful voice assistant. Reply concisely in spoken Chinese. Do not use Markdown."

# ================================================


def detect_key_type(api_key: str) -> str:
    """Return 'token_plan' for tp-* keys, otherwise 'standard' for sk-* or legacy keys."""
    key = (api_key or "").strip()
    if key.startswith("tp-"):
        return "token_plan"
    return "standard"


def default_base_url_for_key(api_key: str) -> str:
    if detect_key_type(api_key) == "token_plan":
        return "https://token-plan-cn.xiaomimimo.com/v1"
    return "https://api.xiaomimimo.com/v1"


def auth_headers_for_key(api_key: str, base_url: str) -> Dict[str, str]:
    if detect_key_type(api_key) == "token_plan" or "token-plan" in (base_url or ""):
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    return {
        "api-key": api_key,
        "Content-Type": "application/json",
    }


class XiaomiMiMoASR:
    """小米MiMo V2.5 ASR语音识别类"""
    
    # API端点
    DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
    TOKEN_PLAN_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    
    # 默认配置
    DEFAULT_MODEL = "mimo-v2.5-asr"
    DEFAULT_LANGUAGE = "zh"
    MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10MB
    
    # 支持的音频格式
    SUPPORTED_FORMATS = {".wav", ".mp3"}
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        use_token_plan: bool = False
    ):
        """
        初始化ASR实例
        
        Args:
            api_key: MiMo API密钥
            base_url: API基础URL
            model: ASR模型名称
            use_token_plan: 是否使用Token Plan
        """
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif use_token_plan:
            self.base_url = self.TOKEN_PLAN_BASE_URL
        else:
            self.base_url = default_base_url_for_key(api_key)
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        # tp- 开头的密钥使用 Bearer 认证
        if self.api_key.startswith("tp-") or "token-plan" in self.base_url:
            return {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        else:
            return {
                "api-key": self.api_key,
                "Content-Type": "application/json",
            }
    
    def _read_audio_file(self, file_path: str) -> tuple:
        """
        读取音频文件
        
        Returns:
            tuple: (audio_bytes, mime_type)
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"音频文件不存在: {file_path}")
        
        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            raise ValueError(f"不支持的音频格式: {ext}，支持: {self.SUPPORTED_FORMATS}")
        
        mime_map = {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg"
        }
        mime_type = mime_map.get(ext, "audio/wav")
        
        with open(file_path, "rb") as f:
            audio_bytes = f.read()
        
        return audio_bytes, mime_type
    
    def transcribe_file(
        self,
        file_path: str,
        language: str = DEFAULT_LANGUAGE
    ) -> Dict[str, Any]:
        """
        转录音频文件
        
        Args:
            file_path: 音频文件路径
            language: 语言代码 (zh, en, auto)
            
        Returns:
            dict: 包含 success, transcript, error 的结果字典
        """
        try:
            audio_bytes, mime_type = self._read_audio_file(file_path)
        except (FileNotFoundError, ValueError) as e:
            return {
                "success": False,
                "transcript": "",
                "error": str(e)
            }
        
        return self._transcribe_bytes(audio_bytes, mime_type, language)
    
    def transcribe_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/wav",
        language: str = DEFAULT_LANGUAGE
    ) -> Dict[str, Any]:
        """
        转录音频字节数据
        
        Args:
            audio_bytes: 音频字节数据
            mime_type: MIME类型
            language: 语言代码
            
        Returns:
            dict: 转录结果
        """
        return self._transcribe_bytes(audio_bytes, mime_type, language)
    
    def _transcribe_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str,
        language: str
    ) -> Dict[str, Any]:
        """内部转录方法"""
        
        # Base64编码
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
        
        # 检查大小限制
        if len(audio_b64) > self.MAX_AUDIO_SIZE:
            return {
                "success": False,
                "transcript": "",
                "error": f"音频文件太大（最大{self.MAX_AUDIO_SIZE // 1024 // 1024}MB）"
            }
        
        # 构建请求体
        body = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": f"data:{mime_type};base64,{audio_b64}",
                    },
                }],
            }],
            "asr_options": {
                "language": language
            },
        }
        
        # 发送请求
        url = f"{self.base_url}/chat/completions"
        headers = self._get_headers()
        
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            choices = result.get("choices", [])
            
            if choices:
                transcript = choices[0].get("message", {}).get("content", "")
                return {
                    "success": True,
                    "transcript": transcript,
                    "error": None
                }
            
            return {
                "success": False,
                "transcript": "",
                "error": "API返回空结果"
            }
            
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "transcript": "",
                "error": "请求超时"
            }
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = error_detail.get("error", {}).get("message", str(e))
                except:
                    pass
            return {
                "success": False,
                "transcript": "",
                "error": f"API请求失败: {error_msg}"
            }


class MiMoChat:
    """小米MiMo对话模型"""
    
    # 对话模型
    DEFAULT_CHAT_MODEL = "mimo-v2.5-pro"
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        use_token_plan: bool = False,
        system_prompt: str = "你是一个智能助手，请用简洁的语言回答问题。"
    ):
        """
        初始化对话模型
        
        Args:
            api_key: MiMo API密钥
            base_url: API基础URL
            model: 对话模型名称
            use_token_plan: 是否使用Token Plan
            system_prompt: 系统提示词
        """
        self.api_key = api_key
        self.model = model or self.DEFAULT_CHAT_MODEL
        self.system_prompt = system_prompt
        
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif use_token_plan:
            self.base_url = "https://token-plan-cn.xiaomimimo.com/v1"
        else:
            self.base_url = default_base_url_for_key(api_key)
        
        # 对话历史
        self.messages = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        if self.api_key.startswith("tp-") or "token-plan" in self.base_url:
            return {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        else:
            return {
                "api-key": self.api_key,
                "Content-Type": "application/json",
            }
    
    def chat(self, user_message: str, keep_history: bool = True) -> Dict[str, Any]:
        """
        发送对话消息
        
        Args:
            user_message: 用户消息
            keep_history: 是否保持对话历史
            
        Returns:
            dict: 包含 success, reply, error 的结果字典
        """
        # 添加用户消息到历史
        if keep_history:
            self.messages.append({"role": "user", "content": user_message})
        else:
            # 不保持历史，只用当前消息
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": user_message})
        
        # 构建请求体
        body = {
            "model": self.model,
            "messages": self.messages if keep_history else messages,
            "temperature": 0.7,
            "max_tokens": 1024
        }
        
        # 发送请求
        url = f"{self.base_url}/chat/completions"
        headers = self._get_headers()
        
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            choices = result.get("choices", [])
            
            if choices:
                reply = choices[0].get("message", {}).get("content", "")
                # 添加助手回复到历史
                if keep_history:
                    self.messages.append({"role": "assistant", "content": reply})
                return {
                    "success": True,
                    "reply": reply,
                    "error": None
                }
            
            return {
                "success": False,
                "reply": "",
                "error": "API返回空结果"
            }
            
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = error_detail.get("error", {}).get("message", str(e))
                except:
                    pass
            return {
                "success": False,
                "reply": "",
                "error": f"API请求失败: {error_msg}"
            }
    
    def clear_history(self):
        """清空对话历史"""
        self.messages = []
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})


class MiMoTTS:
    """小米MiMo TTS语音合成"""
    
    # TTS模型
    MODELS = {
        "standard": "mimo-v2.5-tts",
        "voicedesign": "mimo-v2.5-tts-voicedesign",
        "voiceclone": "mimo-v2.5-tts-voiceclone"
    }
    
    # 预设声音
    VOICES = {
        "冰糖": {"lang": "zh", "gender": "female", "desc": "中文女声"},
        "茉莉": {"lang": "zh", "gender": "female", "desc": "中文女声"},
        "苏打": {"lang": "zh", "gender": "male", "desc": "中文男声"},
        "白桦": {"lang": "zh", "gender": "male", "desc": "中文男声"},
        "Mia": {"lang": "en", "gender": "female", "desc": "英文女声"},
        "Chloe": {"lang": "en", "gender": "female", "desc": "英文女声"},
        "Milo": {"lang": "en", "gender": "male", "desc": "英文男声"},
        "Dean": {"lang": "en", "gender": "male", "desc": "英文男声"},
    }
    
    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "standard",
        voice: str = "冰糖",
        use_token_plan: bool = False
    ):
        """
        初始化TTS实例
        
        Args:
            api_key: MiMo API密钥
            base_url: API基础URL
            model: TTS模型 (standard/premium/expressive)
            voice: 声音名称
            use_token_plan: 是否使用Token Plan
        """
        self.api_key = api_key
        self.model = self.MODELS.get(model, model)
        self.voice = voice
        
        if base_url:
            self.base_url = base_url.rstrip("/")
        elif use_token_plan:
            self.base_url = "https://token-plan-cn.xiaomimimo.com/v1"
        else:
            self.base_url = default_base_url_for_key(api_key)
    
    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        if self.api_key.startswith("tp-") or "token-plan" in self.base_url:
            return {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        else:
            return {
                "api-key": self.api_key,
                "Content-Type": "application/json",
            }
    
    def synthesize(self, text: str, output_path: str = None) -> Dict[str, Any]:
        """
        合成语音
        
        Args:
            text: 要合成的文本
            output_path: 输出音频文件路径（可选）
            
        Returns:
            dict: 包含 success, audio_data, error 的结果字典
        """
        # 构建请求体（使用chat completions格式）
        body = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": text}
            ],
            "audio": {
                "format": "wav",
                "voice": self.voice
            }
        }
        
        # 发送请求
        url = f"{self.base_url}/chat/completions"
        headers = self._get_headers()
        
        try:
            response = requests.post(
                url,
                json=body,
                headers=headers,
                timeout=60
            )
            response.raise_for_status()
            
            result = response.json()
            choices = result.get("choices", [])
            
            if not choices:
                return {
                    "success": False,
                    "audio_data": None,
                    "error": "API返回空结果"
                }
            
            # 提取音频数据
            msg = choices[0].get("message", {})
            audio_info = msg.get("audio", {})
            audio_b64 = audio_info.get("data", "")
            
            if not audio_b64:
                return {
                    "success": False,
                    "audio_data": None,
                    "error": "响应中没有音频数据"
                }
            
            # 解码音频
            audio_data = base64.b64decode(audio_b64)
            
            # 保存到文件
            if output_path:
                with open(output_path, "wb") as f:
                    f.write(audio_data)
            
            return {
                "success": True,
                "audio_data": audio_data,
                "error": None
            }
            
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = error_detail.get("error", {}).get("message", str(e))
                except:
                    pass
            return {
                "success": False,
                "audio_data": None,
                "error": f"TTS请求失败: {error_msg}"
            }
    
    @staticmethod
    def _find_audio_b64(obj: Any) -> Optional[str]:
        """Find the first audio.data base64 string in a streamed response chunk."""
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

    def play_streaming(
        self,
        text: str,
        start_buffer_seconds: float = 3.0,
        rebuffer_seconds: float = 1.0,
        chunk_frames: int = 1024,
    ) -> Dict[str, Any]:
        """Stream TTS as pcm16 and play while receiving."""
        try:
            import pyaudio
        except ImportError:
            raise ImportError("需要安装pyaudio: pip install pyaudio")

        sample_rate = 24000
        channels = 1
        sample_width = 2
        bytes_per_second = sample_rate * channels * sample_width
        play_chunk_bytes = chunk_frames * sample_width
        start_buffer_bytes = int(start_buffer_seconds * bytes_per_second)
        rebuffer_bytes = int(rebuffer_seconds * bytes_per_second)

        pcm_queue: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=512)
        state = {
            "producer_done": False,
            "failed": False,
            "first_audio_ms": 0,
            "play_start_ms": 0,
            "chunks": 0,
            "pcm_bytes": 0,
            "played_bytes": 0,
            "blocks": 0,
            "underflows": 0,
            "rebuffer": 0,
        }
        t0 = time.perf_counter()

        def now_ms() -> int:
            return int((time.perf_counter() - t0) * 1000)

        def playback_worker():
            p = pyaudio.PyAudio()
            stream = None
            buffer = bytearray()
            input_done = False
            try:
                stream = p.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=sample_rate,
                    output=True,
                    frames_per_buffer=chunk_frames,
                )

                while not input_done and len(buffer) < start_buffer_bytes:
                    item = pcm_queue.get()
                    if item is None:
                        input_done = True
                        break
                    buffer.extend(item)

                state["play_start_ms"] = now_ms()
                print(f"[TTS-PC] Playback start at {state['play_start_ms']} ms, buffered={len(buffer)} bytes")

                while buffer or not input_done:
                    while len(buffer) < play_chunk_bytes and not input_done:
                        state["rebuffer"] += 1
                        while len(buffer) < rebuffer_bytes and not input_done:
                            item = pcm_queue.get()
                            if item is None:
                                input_done = True
                                break
                            buffer.extend(item)

                    if not buffer:
                        if input_done:
                            break
                        state["underflows"] += 1
                        time.sleep(0.002)
                        continue

                    n = min(play_chunk_bytes, len(buffer))
                    n -= n % sample_width
                    if n <= 0:
                        time.sleep(0.001)
                        continue
                    data = bytes(buffer[:n])
                    del buffer[:n]
                    stream.write(data)
                    state["played_bytes"] += len(data)
                    state["blocks"] += 1
            except Exception as exc:
                state["failed"] = True
                print(f"[TTS-PC] Playback failed: {exc}")
            finally:
                if stream is not None:
                    stream.stop_stream()
                    stream.close()
                p.terminate()

        player = threading.Thread(target=playback_worker, name="MiMoTTSStreamPlayer", daemon=True)
        player.start()

        body = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": ""},
                {"role": "assistant", "content": text}
            ],
            "audio": {
                "format": "pcm16",
                "voice": self.voice
            },
            "stream": True
        }

        url = f"{self.base_url}/chat/completions"
        headers = self._get_headers()

        print(f"[TTS-PC] Stream POST start, textLen={len(text)}")
        try:
            with requests.post(url, json=body, headers=headers, stream=True, timeout=60) as response:
                print(f"[TTS-PC] Stream POST code={response.status_code} at {now_ms()} ms")
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
                    except json.JSONDecodeError as exc:
                        print(f"[TTS-PC] Bad SSE JSON: {exc}")
                        continue

                    audio_b64 = self._find_audio_b64(event)
                    if not audio_b64:
                        continue

                    try:
                        pcm = base64.b64decode(audio_b64)
                    except Exception as exc:
                        print(f"[TTS-PC] Base64 decode failed: {exc}")
                        continue

                    if len(pcm) % sample_width:
                        pcm = pcm[:-1]
                    if not pcm:
                        continue

                    if not state["first_audio_ms"]:
                        state["first_audio_ms"] = now_ms()
                        print(f"[TTS-PC] First audio chunk at {state['first_audio_ms']} ms")

                    state["chunks"] += 1
                    state["pcm_bytes"] += len(pcm)
                    pcm_queue.put(pcm)

        except requests.exceptions.RequestException as exc:
            state["failed"] = True
            print(f"[TTS-PC] Stream request failed: {exc}")
        finally:
            state["producer_done"] = True
            pcm_queue.put(None)
            player.join()

        total_ms = now_ms()
        audio_ms = int(state["pcm_bytes"] * 1000 / bytes_per_second)
        ok = state["pcm_bytes"] > 0 and not state["failed"]
        print(
            "[TTS-PC] Stream summary: "
            f"ok={int(ok)} first={state['first_audio_ms']} ms "
            f"playStart={state['play_start_ms']} ms chunks={state['chunks']} "
            f"pcm={state['pcm_bytes']} bytes played={state['played_bytes']} bytes "
            f"blocks={state['blocks']} underflows={state['underflows']} "
            f"rebuffer={state['rebuffer']} audio={audio_ms} ms total={total_ms} ms"
        )
        return {"success": ok, **state, "total_ms": total_ms}

    def play(self, text: str):
        return self.play_wav(text)

    def play_wav(self, text: str):
        """
        合成并播放语音
        
        Args:
            text: 要播放的文本
        """
        try:
            import pyaudio
            import io
        except ImportError:
            raise ImportError("需要安装pyaudio: pip install pyaudio")
        
        # 合成语音
        result = self.synthesize(text)
        
        if not result["success"]:
            print(f"[错误] TTS失败: {result['error']}")
            return
        
        audio_data = result["audio_data"]
        
        # 解析WAV格式
        try:
            wf = wave.open(io.BytesIO(audio_data), 'rb')
            
            p = pyaudio.PyAudio()
            stream = p.open(
                format=p.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True
            )
            
            # 播放音频
            chunk = 1024
            data = wf.readframes(chunk)
            while data:
                stream.write(data)
                data = wf.readframes(chunk)
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            wf.close()
            
        except Exception as e:
            print(f"[错误] 播放音频失败: {e}")
    
    @staticmethod
    def list_voices():
        """列出所有可用声音"""
        print("可用声音:")
        for name, info in MiMoTTS.VOICES.items():
            print(f"  {name} - {info['desc']}")


class AudioRecorder:
    """音频录制器"""
    
    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
    
    def record_to_file(
        self,
        output_path: str,
        duration: int = 5
    ) -> str:
        """
        录制音频到文件
        
        Args:
            output_path: 输出文件路径
            duration: 录制时长（秒）
            
        Returns:
            str: 输出文件路径
        """
        try:
            import pyaudio
        except ImportError:
            raise ImportError("需要安装pyaudio: pip install pyaudio")
        
        p = pyaudio.PyAudio()
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size
        )
        
        print(f"开始录音... ({duration}秒)")
        frames = []
        
        for _ in range(0, int(self.sample_rate / self.chunk_size * duration)):
            data = stream.read(self.chunk_size)
            frames.append(data)
        
        print("录音结束")
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # 保存为WAV文件
        wf = wave.open(output_path, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(self.sample_rate)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        return output_path
    
    def record_with_vad(
        self,
        output_path: str,
        silence_threshold: float = 500,
        max_silence_duration: float = 2.0,
        max_duration: int = 30
    ) -> str:
        """
        使用VAD（语音活动检测）录制音频
        
        Args:
            output_path: 输出文件路径
            silence_threshold: 静音阈值
            max_silence_duration: 最大静音时长（秒）
            max_duration: 最大录制时长（秒）
            
        Returns:
            str: 输出文件路径
        """
        try:
            import pyaudio
            import numpy as np
        except ImportError:
            raise ImportError("需要安装pyaudio和numpy: pip install pyaudio numpy")
        
        p = pyaudio.PyAudio()
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size
        )
        
        print("开始录音... (说话开始，沉默停止)")
        frames = []
        silence_start = None
        start_time = time.time()
        
        while True:
            data = stream.read(self.chunk_size)
            frames.append(data)
            
            # 计算音量
            audio_data = np.frombuffer(data, dtype=np.int16)
            volume = np.abs(audio_data).mean()
            
            current_time = time.time()
            
            # 检测静音
            if volume < silence_threshold:
                if silence_start is None:
                    silence_start = current_time
                elif current_time - silence_start > max_silence_duration:
                    print("检测到静音，停止录音")
                    break
            else:
                silence_start = None
            
            # 检查最大时长
            if current_time - start_time > max_duration:
                print("达到最大录制时长")
                break
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        # 保存为WAV文件
        wf = wave.open(output_path, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
        wf.setframerate(self.sample_rate)
        wf.writeframes(b''.join(frames))
        wf.close()
        
        return output_path


class RealtimeASR:
    """实时语音识别（VAD模式）"""
    
    def __init__(self, asr: XiaomiMiMoASR, chat: MiMoChat = None, tts: MiMoTTS = None, tts_streaming: bool = True):
        self.asr = asr
        self.chat = chat
        self.tts = tts
        self.tts_streaming = tts_streaming
        self.is_running = False
        self.is_paused = False  # 暂停录音标志
        self._threads = []
    
    @staticmethod
    def _pcm_to_wav(pcm_data: bytes, sample_rate: int, channels: int, bits_per_sample: int) -> bytes:
        """将PCM数据转换为WAV格式"""
        data_size = len(pcm_data)
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        
        # WAV文件头
        wav_header = struct.pack('<4sI4s', b'RIFF', 36 + data_size, b'WAVE')
        fmt_chunk = struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, channels, sample_rate, byte_rate, block_align, bits_per_sample)
        data_chunk_header = struct.pack('<4sI', b'data', data_size)
        
        return wav_header + fmt_chunk + data_chunk_header + pcm_data
    
    def start(
        self,
        callback=None,
        language: str = "zh",
        silence_threshold: float = 500,
        silence_duration: float = 2.0,
        min_record_duration: float = 0.5
    ):
        """
        开始实时识别（VAD模式）
        
        Args:
            callback: 回调函数，接收识别结果
            language: 语言代码
            silence_threshold: 静音阈值（音量低于此值认为是静音）
            silence_duration: 静音时长（秒），静音多久后停止录音并发送
            min_record_duration: 最小录音时长（秒），避免太短的噪音
        """
        raise NotImplementedError("This method is overridden by _fixed_realtime_start")
    
    def stop(self):
        """停止实时识别"""
        self.is_running = False
    
    def wait(self):
        """等待直到用户按Ctrl+C"""
        try:
            while self.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
    
    @staticmethod
    def test_noise(duration: int = 5):
        """测试环境噪音水平，帮助确定合适的阈值"""
        try:
            import pyaudio
            import numpy as np
        except ImportError:
            raise ImportError("需要安装pyaudio和numpy")
        
        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=1024
        )
        
        print(f"测试环境噪音 ({duration}秒)...")
        print("请保持安静...")
        
        volumes = []
        for i in range(0, int(16000 / 1024 * duration)):
            data = stream.read(1024, exception_on_overflow=False)
            audio_array = np.frombuffer(data, dtype=np.int16)
            volume = np.abs(audio_array).mean()
            volumes.append(volume)
            print(f"\r当前音量: {volume:.0f}", end="", flush=True)
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        avg_volume = sum(volumes) / len(volumes)
        max_volume = max(volumes)
        
        print(f"\n\n测试结果:")
        print(f"  平均音量: {avg_volume:.0f}")
        print(f"  最大音量: {max_volume:.0f}")
        print(f"  建议阈值: {max(avg_volume * 2, 1500):.0f}")
        
        return avg_volume, max_volume

def _fixed_realtime_start(
    self,
    callback=None,
    language: str = "zh",
    silence_threshold: float = 500,
    silence_duration: float = 2.0,
    min_record_duration: float = 0.5,
    start_duration: float = 0.3,
):
    """Clean realtime recorder used to override the damaged legacy start()."""
    try:
        import pyaudio
        import numpy as np
    except ImportError:
        raise ImportError("需要安装pyaudio和numpy: pip install pyaudio numpy")

    self.is_running = True
    self.is_paused = False
    audio_queue = queue.Queue()
    debug_volume = os.environ.get("MIMO_DEBUG_VOLUME", "").lower() in ("1", "true", "yes", "on")

    def get_volume(data: bytes) -> float:
        audio_array = np.frombuffer(data, dtype=np.int16)
        return float(np.abs(audio_array).mean())

    def record_thread():
        p = None
        stream = None
        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
            )
            print(f"[REC] microphone opened: rate=16000 chunk=1024 threshold={silence_threshold}")

            is_recording = False
            frames = []
            silence_start = None
            over_threshold_start = None
            last_volume_log = 0.0
            last_mic_hint = time.time()
            from collections import deque
            pre_buffer = deque(maxlen=24)  # 缓存最近约1.5秒的音频

            while self.is_running:
                data = stream.read(1024, exception_on_overflow=False)
                if self.is_paused:
                    continue

                volume = get_volume(data)
                now = time.time()
                if now - last_volume_log >= 0.5:
                    if is_recording:
                        record_duration = len(frames) * 1024 / 16000
                        print(f"\r[REC] Recording ({record_duration:.1f}s)", end="", flush=True)
                    elif over_threshold_start is not None:
                        detected_duration = now - over_threshold_start
                        print(f"\r[REC] detected voice ({detected_duration:.1f}s)", end="", flush=True)
                    else:
                        print(f"\r[REC] waiting (threshold: {volume:.0f}/{silence_threshold:.0f})", end="", flush=True)
                    last_volume_log = now
                if not is_recording and volume < 20 and now - last_mic_hint >= 10:
                    print("[MIC] 音量持续很低，如果你正在说话，请检查麦克风是否断开或需要重新插拔。")
                    last_mic_hint = now

                if volume >= silence_threshold:
                    if not is_recording:
                        if over_threshold_start is None:
                            over_threshold_start = now
                        elif now - over_threshold_start >= start_duration:
                            is_recording = True
                            frames = []
                            frames.extend(pre_buffer)  # 添加缓存的音频数据
                            over_threshold_start = None
                            print(f"\n[REC] Recording started (volume={volume:.1f})")
                    if is_recording:
                        frames.append(data)
                        silence_start = None
                else:
                    over_threshold_start = None
                    if is_recording:
                        frames.append(data)
                        if silence_start is None:
                            silence_start = now
                        elif now - silence_start >= silence_duration:
                            record_duration = len(frames) * 1024 / 16000
                            if record_duration >= min_record_duration:
                                pcm_data = b"".join(frames)
                                wav_data = self._pcm_to_wav(pcm_data, 16000, 1, 16)
                                print(f"[REC] recording ended, duration={record_duration:.1f}s, wav={len(wav_data)} bytes")
                                audio_queue.put(wav_data)
                            else:
                                print(f"[REC] dropped short audio, duration={record_duration:.1f}s")
                            is_recording = False
                            frames = []
                            silence_start = None
        except Exception as e:
            print(f"\n[ERROR] record thread: {e}")
            self.is_running = False
        finally:
            if stream is not None:
                stream.stop_stream()
                stream.close()
            if p is not None:
                p.terminate()

    def recognize_thread():
        while self.is_running or not audio_queue.empty():
            try:
                audio_data = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                print("[ASR] sending audio...")
                result = self.asr.transcribe_bytes(audio_data, language=language)
                if not result.get("success"):
                    print(f"[ASR] failed: {result.get('error')}")
                    continue

                transcript = re.sub(r"<[^>]+>", "", result.get("transcript", "")).strip()
                if len(transcript) < 2:
                    print(f"[ASR] ignored short/empty result: {transcript!r}")
                    continue

                print(f"你: {transcript}")
                if callback:
                    callback(transcript)

                if self.chat:
                    print("[CHAT] thinking...")
                    self.is_paused = True  # 暂停录音
                    chat_result = self.chat.chat(transcript)
                    if chat_result.get("success"):
                        reply = chat_result["reply"]
                        print(f"AI: {reply}")
                        print()  # 空行
                        print("-" * 30)
                        if self.tts:
                            self.is_paused = True
                            print("[TTS] playing...")
                            if self.tts_streaming:
                                self.tts.play_streaming(reply)
                            else:
                                self.tts.play(reply)
                            time.sleep(0.3)
                            self.is_paused = False
                    else:
                        print(f"[CHAT] failed: {chat_result.get('error')}")
                        self.is_paused = False  # 恢复录音
            except Exception as e:
                print(f"[ERROR] recognize thread: {e}")
                self.is_paused = False  # 确保恢复录音

    t1 = threading.Thread(target=record_thread, name="RecordThread", daemon=True)
    t2 = threading.Thread(target=recognize_thread, name="RecognizeThread", daemon=True)
    self._threads = [t1, t2]
    t1.start()
    t2.start()

    if self.chat:
        print(f"系统: {SYSTEM_PROMPT}")
    print("等待说话...")
    return t1, t2


RealtimeASR.start = _fixed_realtime_start


def create_asr_from_env() -> XiaomiMiMoASR:
    """从配置创建ASR实例"""
    api_key = os.environ.get("XIAOMI_API_KEY") or API_KEY
    
    base_url = os.environ.get("XIAOMI_BASE_URL")
    use_token_plan = "token-plan" in (base_url or "")
    
    return XiaomiMiMoASR(
        api_key=api_key,
        base_url=base_url,
        use_token_plan=use_token_plan
    )


# 使用示例
if __name__ == "__main__":
    # 创建实例
    asr = XiaomiMiMoASR(api_key=API_KEY)
    chat = MiMoChat(api_key=API_KEY, system_prompt=SYSTEM_PROMPT)
    tts = MiMoTTS(api_key=API_KEY, voice=TTS_VOICE)
    realtime = RealtimeASR(asr, chat=chat, tts=tts)
    
    print("语音对话模式 (按Ctrl+C停止)")
    print("-" * 30)
    
    # 发送初始化消息
    print(f"系统: {INIT_MESSAGE}")
    chat.chat(INIT_MESSAGE)
    
    realtime.start()
    realtime.wait()
    print("\n已停止")
