#include <M5Cardputer.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <mbedtls/base64.h>
#include <stdarg.h>

#include "config.h"

static constexpr uint32_t REC_SAMPLE_RATE = 12000;
static constexpr uint32_t TTS_SAMPLE_RATE = 24000;
static constexpr size_t REC_BLOCK_SAMPLES = 320;
static constexpr uint32_t MAX_RECORD_SECONDS = 5;
static constexpr size_t MAX_PCM_BYTES = REC_SAMPLE_RATE * 2 * MAX_RECORD_SECONDS;
static constexpr int32_t MIN_SILENCE_THRESHOLD = 120;
static constexpr int32_t MAX_SILENCE_THRESHOLD = 450;
static constexpr int32_t SILENCE_THRESHOLD_MULTIPLIER = 3;
static constexpr int32_t WARMUP_NOISE_REJECT_LEVEL = 250;
static constexpr uint32_t WARMUP_MS = 500;
static constexpr uint32_t START_VOICE_MS = 200;
static constexpr uint32_t PRE_ROLL_MS = 500;
static constexpr uint32_t SILENCE_MS = 1100;
static constexpr uint32_t POST_SPEECH_PAD_MS = 250;
static constexpr uint32_t MIN_SPEECH_MS = 550;
static constexpr bool MIC_DEBUG = false;
static constexpr uint32_t MIC_DEBUG_INTERVAL_MS = 200;
static constexpr int SPEAKER_CHANNEL = 0;
static constexpr uint8_t TTS_VOLUME = 180;
static constexpr size_t PRE_ROLL_BLOCKS = (REC_SAMPLE_RATE * PRE_ROLL_MS / 1000 + REC_BLOCK_SAMPLES - 1) / REC_BLOCK_SAMPLES;
static constexpr size_t TTS_QUEUE_SAMPLES = 512;
static constexpr size_t TTS_SPEAKER_SAMPLES = 2048;
static constexpr size_t TTS_SPEAKER_BUFFERS = 3;
static constexpr uint8_t TTS_QUEUE_CHUNKS = 96;
static constexpr uint8_t TTS_START_QUEUE_CHUNKS = 72;
static constexpr uint8_t TTS_RESUME_QUEUE_CHUNKS = 48;
static constexpr size_t TTS_B64_BUF_SIZE = 2048;
static constexpr bool TTS_CHUNK_DEBUG = false;
static int16_t ttsSpeakerBuffers[TTS_SPEAKER_BUFFERS][TTS_SPEAKER_SAMPLES];
static int16_t ttsSpeakerAccum[TTS_SPEAKER_SAMPLES];
static uint8_t ttsDecodeBuffer[((TTS_B64_BUF_SIZE + 3) / 4) * 3 + 4];
static int16_t preRollBlocks[PRE_ROLL_BLOCKS][REC_BLOCK_SAMPLES];

struct TtsPlaybackContext {
  QueueHandle_t freeQueue = nullptr;
  QueueHandle_t filledQueue = nullptr;
  int16_t* queueBuffers = nullptr;
  uint16_t* queueSamples = nullptr;
  uint8_t queueChunks = TTS_QUEUE_CHUNKS;
  uint8_t startQueueChunks = TTS_START_QUEUE_CHUNKS;
  uint8_t resumeQueueChunks = TTS_RESUME_QUEUE_CHUNKS;
  volatile bool producerDone = false;
  volatile bool failed = false;
  volatile bool taskDone = false;
  uint32_t playedBytes = 0;
  uint32_t playBlocks = 0;
  uint32_t underruns = 0;
};

struct JsonStringSlice {
  int start = -1;
  int len = 0;
  bool has_escape = false;
};

static uint8_t* g_pcm = nullptr;
static size_t g_pcm_len = 0;
static String g_base_url;
static String g_host;
static String g_prefix;
static bool g_token_plan_auth = false;
static int32_t g_silence_threshold = MIN_SILENCE_THRESHOLD;

static void logf(const char* tag, const char* fmt, ...) {
  char msg[256];
  va_list args;
  va_start(args, fmt);
  vsnprintf(msg, sizeof(msg), fmt, args);
  va_end(args);
  Serial.printf("[%lums]%s %s", (unsigned long)millis(), tag, msg);
}

static void resetPcmBuffer() {
  g_pcm_len = 0;
}

static void releasePcmBuffer() {
  if (g_pcm) {
    free(g_pcm);
    g_pcm = nullptr;
  }
  g_pcm_len = 0;
}

static bool ensurePcmBuffer() {
  if (g_pcm) return true;
  g_pcm = (uint8_t*)malloc(MAX_PCM_BYTES);
  if (!g_pcm) {
    Serial.printf("[RAM] PCM alloc failed bytes=%u free_heap=%lu min_free=%lu\n",
                  (unsigned)MAX_PCM_BYTES,
                  (unsigned long)ESP.getFreeHeap(),
                  (unsigned long)ESP.getMinFreeHeap());
    return false;
  }
  Serial.printf("[RAM] PCM buffer allocated bytes=%u free_heap=%lu\n",
                (unsigned)MAX_PCM_BYTES,
                (unsigned long)ESP.getFreeHeap());
  return true;
}

static void configureCardputerAdvMic() {
  auto mic_cfg = M5Cardputer.Mic.config();
  mic_cfg.sample_rate = REC_SAMPLE_RATE;
  mic_cfg.left_channel = 1;
  mic_cfg.stereo = 0;
  mic_cfg.over_sampling = 1;
  mic_cfg.noise_filter_level = 0;
  mic_cfg.magnification = 64;
  mic_cfg.dma_buf_len = 256;
  mic_cfg.dma_buf_count = 8;
  M5Cardputer.Mic.config(mic_cfg);

  Serial.printf("[MicCfg] din=%d bck=%d ws=%d mck=%d port=%d rate=%lu left=%u channel=%d stereo=%d os=%u mag=%u dma_len=%u dma_count=%u\n",
                mic_cfg.pin_data_in,
                mic_cfg.pin_bck,
                mic_cfg.pin_ws,
                mic_cfg.pin_mck,
                (int)mic_cfg.i2s_port,
                (unsigned long)mic_cfg.sample_rate,
                (unsigned)mic_cfg.left_channel,
                (int)mic_cfg.input_channel,
                mic_cfg.stereo,
                mic_cfg.over_sampling,
                mic_cfg.magnification,
                (unsigned)mic_cfg.dma_buf_len,
                (unsigned)mic_cfg.dma_buf_count);
}

static String jsonEscape(const String& s) {
  String out;
  out.reserve(s.length() + 16);
  for (size_t i = 0; i < s.length(); ++i) {
    char c = s[i];
    if (c == '\\' || c == '"') {
      out += '\\';
      out += c;
    } else if (c == '\n') {
      out += "\\n";
    } else if (c == '\r') {
      out += "\\r";
    } else if (c == '\t') {
      out += "\\t";
    } else {
      out += c;
    }
  }
  return out;
}

static String jsonUnescape(String s) {
  s.replace("\\n", "\n");
  s.replace("\\r", "\r");
  s.replace("\\t", "\t");
  s.replace("\\\"", "\"");
  s.replace("\\/", "/");
  s.replace("\\\\", "\\");
  return s;
}

static void drawStatus(const String& title, const String& line1 = "", const String& line2 = "") {
  auto& d = M5Cardputer.Display;
  d.fillScreen(TFT_BLACK);
  d.setFont(&fonts::efontCN_14);
  d.setTextSize(1);
  d.setTextWrap(true);
  d.setTextScroll(false);
  d.setTextColor(TFT_WHITE, TFT_BLACK);
  d.setCursor(4, 8);
  d.println(title);
  d.setTextColor(TFT_GREEN, TFT_BLACK);
  d.setCursor(4, 34);
  d.println(line1);
  d.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  d.setCursor(4, 78);
  d.println(line2);
}

static bool parseBaseUrl(const String& base) {
  String url = base;
  url.trim();
  if (url.length() == 0) {
    url = String(MIMO_API_KEY).startsWith("tp-") ? "https://token-plan-cn.xiaomimimo.com/v1" : "https://api.xiaomimimo.com/v1";
  }
  if (!url.startsWith("https://")) return false;
  url.remove(0, 8);
  int slash = url.indexOf('/');
  g_host = slash >= 0 ? url.substring(0, slash) : url;
  g_prefix = slash >= 0 ? url.substring(slash) : "";
  if (g_prefix.endsWith("/")) g_prefix.remove(g_prefix.length() - 1);
  g_base_url = "https://" + g_host + g_prefix;
  g_token_plan_auth = String(MIMO_API_KEY).startsWith("tp-") || g_host.indexOf("token-plan") >= 0;
  return g_host.length() > 0;
}

static bool connectTls(WiFiClientSecure& client) {
  client.setInsecure();
  client.setTimeout(65000);
  uint32_t start_ms = millis();
  bool ok = client.connect(g_host.c_str(), 443);
  logf("[NET]", "connect host=%s ok=%d cost=%lums free_heap=%lu\n",
       g_host.c_str(),
       ok ? 1 : 0,
       (unsigned long)(millis() - start_ms),
       (unsigned long)ESP.getFreeHeap());
  return ok;
}

static void writeAuthHeaders(WiFiClientSecure& client) {
  if (g_token_plan_auth) {
    client.printf("Authorization: Bearer %s\r\n", MIMO_API_KEY);
  } else {
    client.printf("api-key: %s\r\n", MIMO_API_KEY);
  }
}

static bool skipHttpHeaders(WiFiClientSecure& client, int* status = nullptr, bool* chunked = nullptr) {
  if (chunked) *chunked = false;
  String line = client.readStringUntil('\n');
  line.trim();
  if (status) {
    int first = line.indexOf(' ');
    *status = first > 0 ? line.substring(first + 1, first + 4).toInt() : 0;
  }
  while (client.connected() || client.available()) {
    line = client.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) return true;
    if (chunked) {
      String lower = line;
      lower.toLowerCase();
      if (lower.startsWith("transfer-encoding:") && lower.indexOf("chunked") >= 0) {
        *chunked = true;
      }
    }
  }
  return false;
}

struct HttpBodyReader {
  explicit HttpBodyReader(WiFiClientSecure& c, bool is_chunked) : client(c), chunked(is_chunked) {}

  int read() {
    if (!chunked) return client.read();

    while (!done) {
      if (chunk_remaining > 0) {
        int ch = readByte();
        if (ch < 0) return -1;
        --chunk_remaining;
        if (chunk_remaining == 0) need_chunk_crlf = true;
        return ch;
      }

      if (need_chunk_crlf) {
        if (readByte() < 0 || readByte() < 0) {
          done = true;
          return -1;
        }
        need_chunk_crlf = false;
      }

      int32_t next_size = readChunkSize();
      if (next_size < 0) return -1;
      if (next_size == 0) {
        consumeTrailers();
        done = true;
        return -1;
      }
      chunk_remaining = (size_t)next_size;
    }
    return -1;
  }

  WiFiClientSecure& client;
  bool chunked = false;
  bool done = false;
  size_t chunk_remaining = 0;
  bool need_chunk_crlf = false;

 private:
  int readByte() {
    uint32_t start_ms = millis();
    while (client.connected() || client.available()) {
      int ch = client.read();
      if (ch >= 0) return ch;
      if (millis() - start_ms > 65000) return -1;
      delay(1);
    }
    return -1;
  }

  int32_t readChunkSize() {
    int32_t size = 0;
    bool have_digit = false;
    bool in_extension = false;
    uint32_t start_ms = millis();

    while (client.connected() || client.available()) {
      int ch = client.read();
      if (ch < 0) {
        if (millis() - start_ms > 65000) return -1;
        delay(1);
        continue;
      }
      if (ch == '\r') continue;
      if (ch == '\n') return have_digit ? size : -1;
      if (ch == ';') {
        in_extension = true;
        continue;
      }
      if (in_extension) continue;

      int value = -1;
      if (ch >= '0' && ch <= '9') value = ch - '0';
      else if (ch >= 'a' && ch <= 'f') value = ch - 'a' + 10;
      else if (ch >= 'A' && ch <= 'F') value = ch - 'A' + 10;
      else return -1;
      have_digit = true;
      size = (size << 4) | value;
    }
    return -1;
  }

  void consumeTrailers() {
    int prev = 0;
    uint32_t start_ms = millis();
    while (client.connected() || client.available()) {
      int ch = client.read();
      if (ch < 0) {
        if (millis() - start_ms > 1000) return;
        delay(1);
        continue;
      }
      if (prev == '\r' && ch == '\n') return;
      prev = ch;
    }
  }
};

static String extractJsonStringAfter(const String& payload, const String& marker) {
  int pos = payload.indexOf(marker);
  if (pos < 0) return "";
  pos += marker.length();
  int end = pos;
  bool escaped = false;
  while (end < (int)payload.length()) {
    char c = payload[end];
    if (escaped) {
      escaped = false;
    } else if (c == '\\') {
      escaped = true;
    } else if (c == '"') {
      break;
    }
    ++end;
  }
  return jsonUnescape(payload.substring(pos, end));
}

static String extractJsonStringValueAt(const String& payload, int quote_pos) {
  if (quote_pos < 0 || quote_pos >= (int)payload.length() || payload[quote_pos] != '"') return "";
  int pos = quote_pos + 1;
  int end = pos;
  bool escaped = false;
  while (end < (int)payload.length()) {
    char c = payload[end];
    if (escaped) {
      escaped = false;
    } else if (c == '\\') {
      escaped = true;
    } else if (c == '"') {
      break;
    }
    ++end;
  }
  return jsonUnescape(payload.substring(pos, end));
}

static String extractJsonStringByKey(const String& payload, const char* key, int start = 0) {
  int pos = payload.indexOf(key, start);
  if (pos < 0) return "";
  int colon = payload.indexOf(':', pos + strlen(key));
  if (colon < 0) return "";
  int value = colon + 1;
  while (value < (int)payload.length() && isspace((unsigned char)payload[value])) ++value;
  if (value >= (int)payload.length() || payload[value] != '"') return "";
  return extractJsonStringValueAt(payload, value);
}

static String extractTextDelta(const String& payload) {
  String text = extractJsonStringAfter(payload, "\"content\":\"");
  if (text.length()) return text;
  text = extractJsonStringByKey(payload, "\"content\"");
  if (text.length()) return text;
  text = extractJsonStringAfter(payload, "\"text\":\"");
  if (text.length()) return text;
  return extractJsonStringByKey(payload, "\"text\"");
}

static bool findJsonStringSliceByKey(const String& payload, const char* key, int start_pos, JsonStringSlice& slice) {
  int key_pos = payload.indexOf(key, start_pos);
  if (key_pos < 0) return false;
  int colon = payload.indexOf(':', key_pos + strlen(key));
  if (colon < 0) return false;
  int value = colon + 1;
  while (value < (int)payload.length() && isspace((unsigned char)payload[value])) ++value;
  if (value >= (int)payload.length() || payload[value] != '"') return false;

  int pos = value + 1;
  bool escaped = false;
  bool has_escape = false;
  while (pos < (int)payload.length()) {
    char c = payload[pos];
    if (escaped) {
      escaped = false;
    } else if (c == '\\') {
      escaped = true;
      has_escape = true;
    } else if (c == '"') {
      slice.start = value + 1;
      slice.len = pos - slice.start;
      slice.has_escape = has_escape;
      return slice.len > 0;
    }
    ++pos;
  }
  return false;
}

static bool findAudioDataSlice(const String& payload, JsonStringSlice& slice) {
  int audio_pos = payload.indexOf("\"audio\"");
  if (audio_pos < 0) return false;
  if (!findJsonStringSliceByKey(payload, "\"data\"", audio_pos, slice)) return false;
  return slice.len >= 64;
}

static bool readSse(WiFiClientSecure& client, std::function<void(const String&)> onPayload) {
  uint32_t start_ms = millis();
  uint32_t first_payload_ms = 0;
  uint32_t payload_count = 0;
  int status = 0;
  bool chunked = false;
  if (!skipHttpHeaders(client, &status, &chunked) || status < 200 || status >= 300) {
    logf("[HTTP]", "status=%d header_fail cost=%lums\n", status, (unsigned long)(millis() - start_ms));
    return false;
  }
  logf("[HTTP]", "status=%d headers cost=%lums chunked=%d\n", status, (unsigned long)(millis() - start_ms), chunked ? 1 : 0);
  HttpBodyReader body(client, chunked);
  String line;
  line.reserve(49152);
  while (!body.done && (client.connected() || client.available())) {
    line = "";
    uint32_t line_start_ms = millis();
    while (!body.done && (client.connected() || client.available())) {
      int ch = body.read();
      if (ch < 0) {
        if (millis() - line_start_ms > 65000) break;
        delay(1);
        continue;
      }
      line_start_ms = millis();
      if (ch == '\n') break;
      if (ch != '\r') line += (char)ch;
    }
    if (line.length() == 0 && !client.connected() && !client.available()) break;
    line.trim();
    if (!line.startsWith("data:")) continue;
    String payload = line.substring(5);
    payload.trim();
    if (payload == "[DONE]") {
      logf("[SSE]", "done events=%lu first=%lums total=%lums\n",
           (unsigned long)payload_count,
           first_payload_ms ? (unsigned long)(first_payload_ms - start_ms) : 0,
           (unsigned long)(millis() - start_ms));
      return true;
    }
    if (first_payload_ms == 0) first_payload_ms = millis();
    ++payload_count;
    onPayload(payload);
  }
  logf("[SSE]", "closed events=%lu first=%lums total=%lums\n",
       (unsigned long)payload_count,
       first_payload_ms ? (unsigned long)(first_payload_ms - start_ms) : 0,
       (unsigned long)(millis() - start_ms));
  return true;
}

class Base64HttpWriter {
 public:
  explicit Base64HttpWriter(WiFiClientSecure& client) : client_(client) {}

  void write(const uint8_t* data, size_t len) {
    size_t idx = 0;
    if (carry_len_) {
      while (carry_len_ < 3 && idx < len) carry_[carry_len_++] = data[idx++];
      if (carry_len_ == 3) {
        encode3(carry_, 3);
        carry_len_ = 0;
      }
    }
    while (idx + 3 <= len) {
      size_t chunk = len - idx;
      chunk -= chunk % 3;
      if (chunk > 768) chunk = 768;
      encode3(data + idx, chunk);
      idx += chunk;
    }
    while (idx < len) carry_[carry_len_++] = data[idx++];
  }

  void finish() {
    if (carry_len_) {
      encode3(carry_, carry_len_);
      carry_len_ = 0;
    }
  }

 private:
  void encode3(const uint8_t* data, size_t len) {
    uint8_t out[1028];
    size_t out_len = 0;
    if (mbedtls_base64_encode(out, sizeof(out), &out_len, data, len) == 0 && out_len) {
      client_.write(out, out_len);
    }
  }

  WiFiClientSecure& client_;
  uint8_t carry_[3] = {0};
  size_t carry_len_ = 0;
};

static void makeWavHeader(uint8_t* h, size_t pcm_len) {
  uint32_t data_size = pcm_len;
  uint32_t riff_size = 36 + data_size;
  uint32_t byte_rate = REC_SAMPLE_RATE * 2;
  h[0] = 'R'; h[1] = 'I'; h[2] = 'F'; h[3] = 'F';
  memcpy(h + 4, &riff_size, 4);
  h[8] = 'W'; h[9] = 'A'; h[10] = 'V'; h[11] = 'E';
  h[12] = 'f'; h[13] = 'm'; h[14] = 't'; h[15] = ' ';
  uint32_t fmt_size = 16;
  uint16_t audio_format = 1, channels = 1, bits = 16, block_align = 2;
  memcpy(h + 16, &fmt_size, 4);
  memcpy(h + 20, &audio_format, 2);
  memcpy(h + 22, &channels, 2);
  memcpy(h + 24, &REC_SAMPLE_RATE, 4);
  memcpy(h + 28, &byte_rate, 4);
  memcpy(h + 32, &block_align, 2);
  memcpy(h + 34, &bits, 2);
  h[36] = 'd'; h[37] = 'a'; h[38] = 't'; h[39] = 'a';
  memcpy(h + 40, &data_size, 4);
}

static bool postJsonSse(const String& body, std::function<void(const String&)> onPayload) {
  WiFiClientSecure client;
  if (!connectTls(client)) return false;
  client.printf("POST %s/chat/completions HTTP/1.1\r\n", g_prefix.c_str());
  client.printf("Host: %s\r\n", g_host.c_str());
  client.print("Content-Type: application/json\r\n");
  writeAuthHeaders(client);
  client.printf("Content-Length: %u\r\n", (unsigned)body.length());
  client.print("Connection: close\r\n\r\n");
  client.print(body);
  return readSse(client, onPayload);
}

static bool streamAsr(String& transcript) {
  const String prefix =
      String("{\"model\":\"") + ASR_MODEL +
      "\",\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"input_audio\",\"input_audio\":{\"data\":\"data:audio/wav;base64,";
  const String suffix =
      String("\"}}]}],\"asr_options\":{\"language\":\"") + ASR_LANGUAGE + "\"},\"stream\":true}";
  size_t wav_len = 44 + g_pcm_len;
  size_t b64_len = ((wav_len + 2) / 3) * 4;
  size_t content_len = prefix.length() + b64_len + suffix.length();

  WiFiClientSecure client;
  if (!connectTls(client)) return false;
  uint32_t upload_start_ms = millis();
  logf("[ASR]", "upload start wav=%u b64=%u content=%u free_heap=%lu\n",
       (unsigned)wav_len,
       (unsigned)b64_len,
       (unsigned)content_len,
       (unsigned long)ESP.getFreeHeap());
  client.printf("POST %s/chat/completions HTTP/1.1\r\n", g_prefix.c_str());
  client.printf("Host: %s\r\n", g_host.c_str());
  client.print("Content-Type: application/json\r\n");
  writeAuthHeaders(client);
  client.printf("Content-Length: %u\r\n", (unsigned)content_len);
  client.print("Connection: close\r\n\r\n");
  client.print(prefix);

  uint8_t wav_header[44];
  makeWavHeader(wav_header, g_pcm_len);
  Base64HttpWriter b64(client);
  b64.write(wav_header, sizeof(wav_header));
  b64.write(g_pcm, g_pcm_len);
  b64.finish();
  client.print(suffix);
  logf("[ASR]", "upload done cost=%lums free_heap=%lu\n",
       (unsigned long)(millis() - upload_start_ms),
       (unsigned long)ESP.getFreeHeap());

  transcript = "";
  return readSse(client, [&](const String& payload) {
    String delta = extractTextDelta(payload);
    if (delta.length()) {
      transcript += delta;
      Serial.print(delta);
    }
  });
}

static bool streamChat(const String& user, String& reply) {
  String body = String("{\"model\":\"") + LLM_MODEL +
                "\",\"messages\":[{\"role\":\"system\",\"content\":\"" + jsonEscape(SYSTEM_PROMPT) +
                "\"},{\"role\":\"user\",\"content\":\"" + jsonEscape(user) +
                "\"}],\"temperature\":0.7,\"max_tokens\":256,\"stream\":true}";
  reply = "";
  return postJsonSse(body, [&](const String& payload) {
    String delta = extractTextDelta(payload);
    if (delta.length()) {
      reply += delta;
      Serial.print(delta);
    }
  });
}

static void ttsPlaybackTask(void* arg) {
  auto* ctx = static_cast<TtsPlaybackContext*>(arg);
  static size_t buffer_index = 0;
  bool started = false;
  size_t accum_samples = 0;
  bool fade_in_next_block = false;

  auto play_accum = [&]() -> bool {
    if (accum_samples == 0) return true;
    int16_t* target = ttsSpeakerBuffers[buffer_index];
    buffer_index = (buffer_index + 1) % TTS_SPEAKER_BUFFERS;
    memcpy(target, ttsSpeakerAccum, accum_samples * sizeof(int16_t));
    if (fade_in_next_block) {
      size_t fade_samples = min((size_t)96, accum_samples);
      for (size_t i = 0; i < fade_samples; ++i) {
        target[i] = (int16_t)(((int32_t)target[i] * (int32_t)i) / (int32_t)fade_samples);
      }
      fade_in_next_block = false;
    }

    while (M5Cardputer.Speaker.isPlaying(SPEAKER_CHANNEL) == 2) {
      delay(1);
    }
    bool ok = M5Cardputer.Speaker.playRaw(target, accum_samples, TTS_SAMPLE_RATE, false, 1, SPEAKER_CHANNEL, false);
    if (!ok) {
      logf("[TTS]", "playRaw failed samples=%u\n", (unsigned)accum_samples);
      ctx->failed = true;
      return false;
    }
    ctx->playedBytes += accum_samples * sizeof(int16_t);
    ++ctx->playBlocks;
    accum_samples = 0;
    return true;
  };

  while (!ctx->producerDone || uxQueueMessagesWaiting(ctx->filledQueue) > 0) {
    if (!started) {
      while (!ctx->producerDone && uxQueueMessagesWaiting(ctx->filledQueue) < ctx->startQueueChunks) {
        delay(5);
      }
      started = true;
    }

    uint8_t queue_index = 0;
    if (xQueueReceive(ctx->filledQueue, &queue_index, pdMS_TO_TICKS(20)) != pdTRUE) {
      if (!ctx->producerDone) {
        ++ctx->underruns;
        fade_in_next_block = true;
        while (!ctx->producerDone && uxQueueMessagesWaiting(ctx->filledQueue) < ctx->resumeQueueChunks) {
          delay(5);
        }
      }
      continue;
    }

    size_t n = ctx->queueSamples[queue_index];
    if (n > TTS_QUEUE_SAMPLES) n = TTS_QUEUE_SAMPLES;
    const int16_t* source = ctx->queueBuffers + ((size_t)queue_index * TTS_QUEUE_SAMPLES);
    size_t offset = 0;
    while (offset < n) {
      size_t copy_samples = min(n - offset, TTS_SPEAKER_SAMPLES - accum_samples);
      memcpy(ttsSpeakerAccum + accum_samples, source + offset, copy_samples * sizeof(int16_t));
      accum_samples += copy_samples;
      offset += copy_samples;
      if (accum_samples == TTS_SPEAKER_SAMPLES && !play_accum()) break;
    }
    xQueueSend(ctx->freeQueue, &queue_index, 0);
    if (ctx->failed) break;
  }

  if (!ctx->failed) play_accum();

  while (M5Cardputer.Speaker.isPlaying(SPEAKER_CHANNEL)) {
    delay(5);
  }
  ctx->taskDone = true;
  vTaskDelete(nullptr);
}

static bool enqueuePcmForPlayback(const int16_t* pcm, size_t samples, TtsPlaybackContext& ctx) {
  size_t offset = 0;
  uint32_t last_wait_log_ms = 0;
  while (offset < samples) {
    if (ctx.failed) return false;
    size_t n = min(samples - offset, TTS_QUEUE_SAMPLES);
    uint8_t queue_index = 0;
    while (xQueueReceive(ctx.freeQueue, &queue_index, pdMS_TO_TICKS(100)) != pdTRUE) {
      if (ctx.failed) return false;
      uint32_t now_ms = millis();
      if (last_wait_log_ms == 0 || now_ms - last_wait_log_ms >= 1000) {
        logf("[TTS]", "wait free queue queued=%u offset=%u samples=%u played=%lu\n",
             (unsigned)uxQueueMessagesWaiting(ctx.filledQueue),
             (unsigned)offset,
             (unsigned)samples,
             (unsigned long)ctx.playedBytes);
        last_wait_log_ms = now_ms;
      }
    }
    memcpy(ctx.queueBuffers + ((size_t)queue_index * TTS_QUEUE_SAMPLES), pcm + offset, n * sizeof(int16_t));
    ctx.queueSamples[queue_index] = n;
    if (xQueueSend(ctx.filledQueue, &queue_index, pdMS_TO_TICKS(1000)) != pdTRUE) {
      xQueueSend(ctx.freeQueue, &queue_index, 0);
      logf("[TTS]", "filled queue send failed\n");
      return false;
    }
    offset += n;
  }
  return true;
}

static bool decodeAndQueuePcm(const String& payload, const JsonStringSlice& audio, TtsPlaybackContext& ctx, uint32_t& decoded_bytes) {
  size_t b64_len = audio.len;
  const char* b64_ptr = payload.c_str() + audio.start;
  String unescaped;
  if (audio.has_escape) {
    unescaped = jsonUnescape(payload.substring(audio.start, audio.start + audio.len));
    b64_ptr = unescaped.c_str();
    b64_len = unescaped.length();
  }

  size_t out_cap = (b64_len * 3) / 4 + 4;
  if (out_cap > sizeof(ttsDecodeBuffer)) {
    logf("[TTS]", "audio chunk too large b64=%u out_cap=%u\n", (unsigned)b64_len, (unsigned)out_cap);
    return false;
  }
  size_t out_len = 0;
  int rc = mbedtls_base64_decode(ttsDecodeBuffer, sizeof(ttsDecodeBuffer), &out_len, (const uint8_t*)b64_ptr, b64_len);
  bool ok = (rc == 0);
  if (ok && out_len > 1) {
    out_len &= ~static_cast<size_t>(1);
    decoded_bytes += out_len;
    ok = enqueuePcmForPlayback((const int16_t*)ttsDecodeBuffer, out_len / sizeof(int16_t), ctx);
  }
  if (!ok) logf("[TTS]", "decode/queue failed rc=%d b64=%u out=%u escaped=%d\n",
                rc,
                (unsigned)b64_len,
                (unsigned)out_len,
                audio.has_escape ? 1 : 0);
  return ok;
}

static bool isBase64Char(char c) {
  return (c >= 'A' && c <= 'Z') ||
         (c >= 'a' && c <= 'z') ||
         (c >= '0' && c <= '9') ||
         c == '+' || c == '/' || c == '=';
}

struct TtsBase64Decoder {
  char b64[TTS_B64_BUF_SIZE + 4] = {};
  size_t b64_len = 0;
  TtsPlaybackContext* ctx = nullptr;
  uint32_t* decoded_bytes = nullptr;
  bool failed = false;
  uint32_t current_b64_chars = 0;
  bool has_pending_pcm_byte = false;
  uint8_t pending_pcm_byte = 0;

  bool flush(bool final_chunk = false) {
    size_t decode_len = b64_len;
    size_t consume_len = b64_len;
    if (final_chunk) {
      size_t tail = decode_len & 3;
      if (tail == 1) {
        logf("[TTS]", "drop invalid base64 tail bytes=1\n");
        --decode_len;
        consume_len = decode_len;
      } else {
        while (tail && (decode_len & 3)) {
          b64[decode_len++] = '=';
        }
      }
    } else {
      decode_len &= ~static_cast<size_t>(3);
      consume_len = decode_len;
    }
    if (decode_len == 0) {
      if (final_chunk && b64_len) {
        logf("[TTS]", "drop partial base64 tail bytes=%u\n", (unsigned)b64_len);
        b64_len = 0;
      }
      return true;
    }

    size_t out_len = 0;
    int rc = mbedtls_base64_decode(ttsDecodeBuffer, sizeof(ttsDecodeBuffer), &out_len, (const uint8_t*)b64, decode_len);
    if (rc != 0) {
      logf("[TTS]", "base64 stream decode failed rc=%d b64=%u final=%d\n",
           rc,
           (unsigned)decode_len,
           final_chunk ? 1 : 0);
      failed = true;
      return false;
    }

    if (has_pending_pcm_byte) {
      if (out_len >= sizeof(ttsDecodeBuffer)) {
        logf("[TTS]", "pcm carry overflow out=%u\n", (unsigned)out_len);
        failed = true;
        return false;
      }
      memmove(ttsDecodeBuffer + 1, ttsDecodeBuffer, out_len);
      ttsDecodeBuffer[0] = pending_pcm_byte;
      ++out_len;
      has_pending_pcm_byte = false;
    }
    if (out_len & 1) {
      pending_pcm_byte = ttsDecodeBuffer[out_len - 1];
      has_pending_pcm_byte = true;
      --out_len;
    }
    if (out_len) {
      *decoded_bytes += out_len;
      if (!enqueuePcmForPlayback((const int16_t*)ttsDecodeBuffer, out_len / sizeof(int16_t), *ctx)) {
        failed = true;
        return false;
      }
    }

    size_t remain = b64_len - consume_len;
    if (final_chunk) {
      b64_len = 0;
    } else {
      if (remain) memmove(b64, b64 + decode_len, remain);
      b64_len = remain;
    }
    return true;
  }

  bool push(char c) {
    if (!isBase64Char(c)) return true;
    ++current_b64_chars;
    b64[b64_len++] = c;
    if (b64_len >= TTS_B64_BUF_SIZE) return flush(false);
    return true;
  }
};

static TtsBase64Decoder ttsB64Decoder;

static bool matchPattern(char c, const char* pattern, size_t& matched) {
  if (c == pattern[matched]) {
    ++matched;
    if (pattern[matched] == '\0') {
      matched = 0;
      return true;
    }
  } else {
    matched = (c == pattern[0]) ? 1 : 0;
  }
  return false;
}

static bool postTtsSseStream(const String& body, TtsPlaybackContext& ctx, uint32_t& event_count, uint32_t& chunk_count, uint32_t& decoded_bytes, uint32_t& first_audio_ms, uint32_t tts_start_ms) {
  WiFiClientSecure client;
  if (!connectTls(client)) return false;
  client.printf("POST %s/chat/completions HTTP/1.1\r\n", g_prefix.c_str());
  client.printf("Host: %s\r\n", g_host.c_str());
  client.print("Content-Type: application/json\r\n");
  writeAuthHeaders(client);
  client.printf("Content-Length: %u\r\n", (unsigned)body.length());
  client.print("Connection: close\r\n\r\n");
  client.print(body);

  int status = 0;
  bool chunked = false;
  uint32_t http_start_ms = millis();
  if (!skipHttpHeaders(client, &status, &chunked) || status < 200 || status >= 300) {
    logf("[HTTP]", "status=%d header_fail cost=%lums\n", status, (unsigned long)(millis() - http_start_ms));
    return false;
  }
  logf("[HTTP]", "status=%d headers cost=%lums chunked=%d\n", status, (unsigned long)(millis() - http_start_ms), chunked ? 1 : 0);
  HttpBodyReader body_reader(client, chunked);

  enum ParseState {
    FIND_AUDIO_DATA,
    READ_AUDIO_DATA
  };
  ParseState state = FIND_AUDIO_DATA;
  size_t data_match = 0;
  bool escaped = false;
  bool line_start = true;
  size_t data_prefix_match = 0;
  TtsBase64Decoder& decoder = ttsB64Decoder;
  decoder.b64_len = 0;
  decoder.ctx = &ctx;
  decoder.decoded_bytes = &decoded_bytes;
  decoder.failed = false;
  decoder.current_b64_chars = 0;
  decoder.has_pending_pcm_byte = false;
  decoder.pending_pcm_byte = 0;

  while (!body_reader.done && (client.connected() || client.available())) {
    int ch = body_reader.read();
    if (ch < 0) {
      delay(1);
      continue;
    }
    char c = (char)ch;

    if (line_start && c == 'd') data_prefix_match = 1;
    else if (data_prefix_match == 1 && c == 'a') data_prefix_match = 2;
    else if (data_prefix_match == 2 && c == 't') data_prefix_match = 3;
    else if (data_prefix_match == 3 && c == 'a') data_prefix_match = 4;
    else if (data_prefix_match == 4 && c == ':') {
      ++event_count;
      data_prefix_match = 0;
    } else if (c != '\r' && c != '\n') {
      data_prefix_match = 0;
    }
    if (c == '\n') line_start = true;
    else if (c != '\r') line_start = false;

    switch (state) {
      case FIND_AUDIO_DATA:
        if (matchPattern(c, "\"data\":\"", data_match)) {
          decoder.b64_len = 0;
          escaped = false;
          state = READ_AUDIO_DATA;
          ++chunk_count;
          if (first_audio_ms == 0) {
            first_audio_ms = millis();
            logf("[TTS]", "first audio after=%lums\n", (unsigned long)(first_audio_ms - tts_start_ms));
          }
          if (TTS_CHUNK_DEBUG || chunk_count <= 2 || (chunk_count % 32) == 0) {
            logf("[TTS]", "audio chunk #%lu event=%lu\n", (unsigned long)chunk_count, (unsigned long)event_count);
          }
        }
        break;
      case READ_AUDIO_DATA:
        if (escaped) {
          if (c == '/') {
            if (!decoder.push('/')) return false;
          } else {
            if (!decoder.push(c)) return false;
          }
          escaped = false;
        } else if (c == '\\') {
          escaped = true;
        } else if (c == '"') {
          if (!decoder.flush(true)) return false;
          if (TTS_CHUNK_DEBUG || chunk_count <= 2 || (chunk_count % 32) == 0) {
            logf("[TTS]", "audio chunk done #%lu b64=%lu decoded_total=%lu\n",
                 (unsigned long)chunk_count,
                 (unsigned long)decoder.current_b64_chars,
                 (unsigned long)decoded_bytes);
          }
          decoder.current_b64_chars = 0;
          state = FIND_AUDIO_DATA;
        } else {
          if (!decoder.push(c)) return false;
        }
        break;
    }
  }

  logf("[SSE]", "closed events=%lu total=%lums\n",
       (unsigned long)event_count,
       (unsigned long)(millis() - tts_start_ms));
  if (decoder.has_pending_pcm_byte) {
    logf("[TTS]", "drop dangling pcm byte at stream end\n");
    decoder.has_pending_pcm_byte = false;
  }
  return !decoder.failed;
}

static bool streamTts(const String& text) {
  String body = String("{\"model\":\"") + TTS_MODEL +
                "\",\"messages\":[{\"role\":\"user\",\"content\":\"\"},{\"role\":\"assistant\",\"content\":\"" +
                jsonEscape(text) + "\"}],\"audio\":{\"format\":\"pcm16\",\"voice\":\"" +
                jsonEscape(TTS_VOICE) + "\"},\"stream\":true}";
  TtsPlaybackContext ctx;
  size_t queue_buffer_bytes = (size_t)TTS_QUEUE_CHUNKS * TTS_QUEUE_SAMPLES * sizeof(int16_t);
  ctx.queueBuffers = (int16_t*)malloc(queue_buffer_bytes);
  ctx.queueSamples = (uint16_t*)malloc((size_t)TTS_QUEUE_CHUNKS * sizeof(uint16_t));
  ctx.freeQueue = xQueueCreate(TTS_QUEUE_CHUNKS, sizeof(uint8_t));
  ctx.filledQueue = xQueueCreate(TTS_QUEUE_CHUNKS, sizeof(uint8_t));
  auto cleanup = [&]() {
    if (ctx.freeQueue) {
      vQueueDelete(ctx.freeQueue);
      ctx.freeQueue = nullptr;
    }
    if (ctx.filledQueue) {
      vQueueDelete(ctx.filledQueue);
      ctx.filledQueue = nullptr;
    }
    if (ctx.queueBuffers) {
      free(ctx.queueBuffers);
      ctx.queueBuffers = nullptr;
    }
    if (ctx.queueSamples) {
      free(ctx.queueSamples);
      ctx.queueSamples = nullptr;
    }
  };
  if (!ctx.freeQueue || !ctx.filledQueue) {
    logf("[TTS]", "queue create failed free_heap=%lu max_alloc=%lu\n",
         (unsigned long)ESP.getFreeHeap(),
         (unsigned long)ESP.getMaxAllocHeap());
    cleanup();
    return false;
  }
  if (!ctx.queueBuffers || !ctx.queueSamples) {
    logf("[TTS]", "queue buffer alloc failed bytes=%u free_heap=%lu max_alloc=%lu\n",
         (unsigned)queue_buffer_bytes,
         (unsigned long)ESP.getFreeHeap(),
         (unsigned long)ESP.getMaxAllocHeap());
    cleanup();
    return false;
  }
  xQueueReset(ctx.freeQueue);
  xQueueReset(ctx.filledQueue);
  for (uint8_t i = 0; i < TTS_QUEUE_CHUNKS; ++i) {
    xQueueSend(ctx.freeQueue, &i, 0);
  }

  M5Cardputer.Speaker.stop(SPEAKER_CHANNEL);
  TaskHandle_t playback_task = nullptr;
  BaseType_t task_ok = xTaskCreatePinnedToCore(ttsPlaybackTask, "tts_play", 4096, &ctx, 8, &playback_task, 1);
  if (task_ok != pdPASS) {
    logf("[TTS]", "playback task create failed\n");
    cleanup();
    return false;
  }

  uint32_t chunk_count = 0;
  uint32_t decoded_bytes = 0;
  uint32_t tts_start_ms = millis();
  uint32_t first_audio_ms = 0;
  uint32_t tts_event_count = 0;
  logf("[TTS]", "request start text_chars=%u queue_chunks=%u start=%u resume=%u spk_samples=%u queue_bytes=%u free_heap=%lu max_alloc=%lu min_free=%lu\n",
       (unsigned)text.length(),
       (unsigned)ctx.queueChunks,
       (unsigned)ctx.startQueueChunks,
       (unsigned)ctx.resumeQueueChunks,
       (unsigned)TTS_SPEAKER_SAMPLES,
       (unsigned)queue_buffer_bytes,
       (unsigned long)ESP.getFreeHeap(),
       (unsigned long)ESP.getMaxAllocHeap(),
       (unsigned long)ESP.getMinFreeHeap());
  bool http_ok = postTtsSseStream(body, ctx, tts_event_count, chunk_count, decoded_bytes, first_audio_ms, tts_start_ms);

  ctx.producerDone = true;
  while (!ctx.taskDone) {
    M5Cardputer.update();
    delay(10);
  }

  bool success = http_ok && !ctx.failed && ctx.playedBytes > 0;
  logf("[TTS]", "stream done ok=%d events=%lu chunks=%lu decoded=%lu played=%lu blocks=%lu underruns=%lu first_audio=%lums total=%lums\n",
                success ? 1 : 0,
                (unsigned long)tts_event_count,
                (unsigned long)chunk_count,
                (unsigned long)decoded_bytes,
                (unsigned long)ctx.playedBytes,
                (unsigned long)ctx.playBlocks,
                (unsigned long)ctx.underruns,
                first_audio_ms ? (unsigned long)(first_audio_ms - tts_start_ms) : 0,
                (unsigned long)(millis() - tts_start_ms));
  cleanup();
  return success;
}

static int32_t blockLevel(const int16_t* samples, size_t n) {
  int64_t acc = 0;
  for (size_t i = 0; i < n; ++i) acc += abs(samples[i]);
  return (int32_t)(acc / (int64_t)n);
}

static void printMicBlockDebug(const int16_t* samples, size_t n, int32_t level, bool started, size_t pcm_len, uint32_t elapsed_ms) {
  if (!MIC_DEBUG) return;

  int16_t min_sample = samples[0];
  int16_t max_sample = samples[0];
  int64_t dc_acc = 0;
  for (size_t i = 0; i < n; ++i) {
    int16_t v = samples[i];
    if (v < min_sample) min_sample = v;
    if (v > max_sample) max_sample = v;
    dc_acc += v;
  }

  Serial.printf(
      "[%lums][MIC] t=%lums started=%d level=%ld threshold=%ld min=%d max=%d dc=%ld pcm=%u first=[",
      (unsigned long)millis(),
      (unsigned long)elapsed_ms,
      started ? 1 : 0,
      (long)level,
      (long)g_silence_threshold,
      min_sample,
      max_sample,
      (long)(dc_acc / (int64_t)n),
      (unsigned)pcm_len);

  size_t sample_count = n < 8 ? n : 8;
  for (size_t i = 0; i < sample_count; ++i) {
    if (i) Serial.print(",");
    Serial.print(samples[i]);
  }
  Serial.println("]");
}

static bool recordUtterance() {
  resetPcmBuffer();
  if (!ensurePcmBuffer()) {
    drawStatus("RAM error", "PCM buffer alloc failed");
    return false;
  }

  if (M5Cardputer.Speaker.isEnabled()) {
    M5Cardputer.Speaker.stop();
    M5Cardputer.Speaker.end();
  }
  if (M5Cardputer.Mic.isEnabled()) {
    while (M5Cardputer.Mic.isRecording()) delay(1);
    M5Cardputer.Mic.end();
  }
  delay(120);
  Serial.println();
  logf("[REC]", "prepare half-duplex input: speaker stopped\n");
  logf("[REC]", "sample_rate=%lu block_samples=%u max_seconds=%lu min_threshold=%ld silence_ms=%lu min_speech_ms=%lu preroll_ms=%lu\n",
       (unsigned long)REC_SAMPLE_RATE,
       (unsigned)REC_BLOCK_SAMPLES,
       (unsigned long)MAX_RECORD_SECONDS,
       (long)MIN_SILENCE_THRESHOLD,
       (unsigned long)SILENCE_MS,
       (unsigned long)MIN_SPEECH_MS,
       (unsigned long)PRE_ROLL_MS);

  configureCardputerAdvMic();
  bool mic_ok = M5Cardputer.Mic.begin();
  logf("[REC]", "Mic.begin()=%d isRunning=%d isEnabled=%d\n",
       mic_ok ? 1 : 0,
       M5Cardputer.Mic.isRunning() ? 1 : 0,
       M5Cardputer.Mic.isEnabled() ? 1 : 0);
  if (!mic_ok) {
    drawStatus("Mic begin failed");
    releasePcmBuffer();
    return false;
  }

  int16_t block[REC_BLOCK_SAMPLES];
  uint32_t warmup_start_ms = millis();
  int64_t warmup_level_sum = 0;
  int32_t warmup_level_count = 0;
  logf("[REC]", "warmup discard %lums\n", (unsigned long)WARMUP_MS);
  while (millis() - warmup_start_ms < WARMUP_MS) {
    if (M5Cardputer.Mic.record(block, REC_BLOCK_SAMPLES, REC_SAMPLE_RATE, false)) {
      while (M5Cardputer.Mic.isRecording()) delay(1);
      uint32_t warmup_elapsed_ms = millis() - warmup_start_ms;
      int32_t warmup_level = blockLevel(block, REC_BLOCK_SAMPLES);
      if (warmup_elapsed_ms > 180 && warmup_level < WARMUP_NOISE_REJECT_LEVEL) {
        warmup_level_sum += warmup_level;
        ++warmup_level_count;
      }
      if (MIC_DEBUG && warmup_elapsed_ms < 120) {
        printMicBlockDebug(block, REC_BLOCK_SAMPLES, warmup_level, false, 0, millis() - warmup_start_ms);
      }
    } else {
      delay(5);
    }
  }
  int32_t noise_floor = warmup_level_count > 0 ? warmup_level_sum / warmup_level_count : 0;
  g_silence_threshold = noise_floor * SILENCE_THRESHOLD_MULTIPLIER;
  if (g_silence_threshold < MIN_SILENCE_THRESHOLD) g_silence_threshold = MIN_SILENCE_THRESHOLD;
  if (g_silence_threshold > MAX_SILENCE_THRESHOLD) g_silence_threshold = MAX_SILENCE_THRESHOLD;
  logf("[REC]", "warmup done noise_floor=%ld accepted_blocks=%ld threshold=%ld\n",
       (long)noise_floor,
       (long)warmup_level_count,
       (long)g_silence_threshold);

  g_pcm_len = 0;
  bool started = false;
  uint32_t start_ms = 0;
  uint32_t last_voice_ms = millis();
  uint32_t voice_candidate_ms = 0;
  uint32_t begin_ms = millis();
  uint32_t last_debug_ms = 0;
  uint32_t record_fail_count = 0;
  size_t last_voice_pcm_len = 0;
  size_t pre_roll_head = 0;
  size_t pre_roll_count = 0;
  drawStatus("Listening", "Speak now", "BtnA cancels");

  while (millis() - begin_ms < (MAX_RECORD_SECONDS + 2) * 1000) {
    M5Cardputer.update();
    if (M5Cardputer.BtnA.wasClicked() && started) {
      Serial.println("[REC] stopped by BtnA");
      break;
    }
    if (!M5Cardputer.Mic.record(block, REC_BLOCK_SAMPLES, REC_SAMPLE_RATE, false)) {
      ++record_fail_count;
      if (MIC_DEBUG && (record_fail_count == 1 || record_fail_count % 50 == 0)) {
        Serial.printf("[MIC] record() failed count=%lu isRunning=%d isRecording=%u\n",
                      (unsigned long)record_fail_count,
                      M5Cardputer.Mic.isRunning() ? 1 : 0,
                      (unsigned)M5Cardputer.Mic.isRecording());
      }
      delay(5);
      continue;
    }
    while (M5Cardputer.Mic.isRecording()) delay(1);

    int32_t level = blockLevel(block, REC_BLOCK_SAMPLES);
    uint32_t now = millis();
    bool copied_current_from_preroll = false;
    if (!started) {
      memcpy(preRollBlocks[pre_roll_head], block, sizeof(block));
      pre_roll_head = (pre_roll_head + 1) % PRE_ROLL_BLOCKS;
      if (pre_roll_count < PRE_ROLL_BLOCKS) ++pre_roll_count;
    }
    if (MIC_DEBUG && (last_debug_ms == 0 || now - last_debug_ms >= MIC_DEBUG_INTERVAL_MS)) {
      printMicBlockDebug(block, REC_BLOCK_SAMPLES, level, started, g_pcm_len, now - begin_ms);
      last_debug_ms = now;
    }
    if (level > g_silence_threshold) {
      if (!started) {
        if (voice_candidate_ms == 0) {
          voice_candidate_ms = now;
          Serial.printf("[REC] voice candidate t=%lums level=%ld\n", (unsigned long)(now - begin_ms), (long)level);
        }
        if (now - voice_candidate_ms >= START_VOICE_MS) {
          started = true;
          start_ms = now;
          size_t first_pre_roll = (pre_roll_head + PRE_ROLL_BLOCKS - pre_roll_count) % PRE_ROLL_BLOCKS;
          for (size_t i = 0; i < pre_roll_count && g_pcm_len + sizeof(block) <= MAX_PCM_BYTES; ++i) {
            size_t idx = (first_pre_roll + i) % PRE_ROLL_BLOCKS;
            memcpy(g_pcm + g_pcm_len, preRollBlocks[idx], sizeof(block));
            g_pcm_len += sizeof(block);
          }
          copied_current_from_preroll = true;
          drawStatus("Recording", "Voice detected", "Stop after silence");
          logf("[REC]", "voice start t=%lums level=%ld candidate_ms=%lums preroll_blocks=%u preroll_ms=%lu pcm=%u\n",
               (unsigned long)(now - begin_ms),
               (long)level,
               (unsigned long)(now - voice_candidate_ms),
               (unsigned)pre_roll_count,
               (unsigned long)(pre_roll_count * REC_BLOCK_SAMPLES * 1000 / REC_SAMPLE_RATE),
               (unsigned)g_pcm_len);
        }
      }
      last_voice_ms = now;
    } else if (!started) {
      voice_candidate_ms = 0;
    }

    if (started && !copied_current_from_preroll && g_pcm_len + sizeof(block) <= MAX_PCM_BYTES) {
      memcpy(g_pcm + g_pcm_len, block, sizeof(block));
      g_pcm_len += sizeof(block);
    }
    if (started && level > g_silence_threshold) {
      last_voice_pcm_len = g_pcm_len;
    }

    if (started && now - last_voice_ms > SILENCE_MS && now - start_ms > MIN_SPEECH_MS) {
      Serial.printf("[REC] stop on silence t=%lums silence=%lums duration=%lums\n",
                    (unsigned long)(now - begin_ms),
                    (unsigned long)(now - last_voice_ms),
                    (unsigned long)(now - start_ms));
      break;
    }
    if (started && g_pcm_len + sizeof(block) > MAX_PCM_BYTES) {
      Serial.printf("[REC] stop on buffer full pcm=%u\n", (unsigned)g_pcm_len);
      break;
    }
  }

  M5Cardputer.Mic.end();
  delay(120);
  size_t min_pcm_bytes = REC_SAMPLE_RATE * 2 * MIN_SPEECH_MS / 1000;
  if (g_pcm_len >= min_pcm_bytes && last_voice_pcm_len > 0 && last_voice_pcm_len < g_pcm_len) {
    size_t pad_bytes = REC_SAMPLE_RATE * 2 * POST_SPEECH_PAD_MS / 1000;
    size_t trimmed_len = last_voice_pcm_len + pad_bytes;
    if (trimmed_len < g_pcm_len) {
      logf("[REC]", "trim trailing silence pcm=%u -> %u last_voice=%u pad_ms=%lu\n",
           (unsigned)g_pcm_len,
           (unsigned)trimmed_len,
           (unsigned)last_voice_pcm_len,
           (unsigned long)POST_SPEECH_PAD_MS);
      g_pcm_len = trimmed_len;
    }
  }
  Serial.printf("[REC] done started=%d pcm=%u min_pcm=%u record_fail_count=%lu accepted=%d\n",
                started ? 1 : 0,
                (unsigned)g_pcm_len,
                (unsigned)min_pcm_bytes,
                (unsigned long)record_fail_count,
                g_pcm_len >= min_pcm_bytes ? 1 : 0);
  bool accepted = g_pcm_len >= min_pcm_bytes;
  if (!accepted) releasePcmBuffer();
  return accepted;
}

static void connectWifi() {
  WiFi.useStaticBuffers(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  drawStatus("WiFi", WIFI_SSID, "Connecting...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
  }
  drawStatus("WiFi connected", WiFi.localIP().toString(), "Press BtnA");
}

static void runConversation() {
  uint32_t turn_start_ms = millis();
  logf("[TURN]", "start free_heap=%lu min_free=%lu\n",
       (unsigned long)ESP.getFreeHeap(),
       (unsigned long)ESP.getMinFreeHeap());
  if (!recordUtterance()) {
    drawStatus("No speech", "Press BtnA to retry");
    logf("[TURN]", "no speech total=%lums\n", (unsigned long)(millis() - turn_start_ms));
    return;
  }

  drawStatus("ASR streaming", String(g_pcm_len / 1024) + " KB audio");
  String transcript;
  uint32_t asr_start_ms = millis();
  Serial.println();
  logf("[ASR]", "start pcm=%u bytes\n", (unsigned)g_pcm_len);
  if (!streamAsr(transcript) || transcript.length() < 2) {
    releasePcmBuffer();
    drawStatus("ASR failed", transcript);
    logf("[ASR]", "failed cost=%lums text_chars=%u\n", (unsigned long)(millis() - asr_start_ms), (unsigned)transcript.length());
    return;
  }
  releasePcmBuffer();
  transcript.trim();
  logf("[ASR]", "done cost=%lums text_chars=%u text=%s\n",
       (unsigned long)(millis() - asr_start_ms),
       (unsigned)transcript.length(),
       transcript.c_str());
  drawStatus("You", transcript);

  String reply;
  uint32_t llm_start_ms = millis();
  Serial.println();
  logf("[LLM]", "start\n");
  if (!streamChat(transcript, reply) || reply.length() == 0) {
    drawStatus("LLM failed");
    logf("[LLM]", "failed cost=%lums reply_chars=%u\n", (unsigned long)(millis() - llm_start_ms), (unsigned)reply.length());
    return;
  }
  reply.trim();
  logf("[LLM]", "done cost=%lums reply_chars=%u\n", (unsigned long)(millis() - llm_start_ms), (unsigned)reply.length());
  drawStatus("AI", reply, "Streaming TTS...");

  M5Cardputer.Mic.end();
  uint32_t speaker_start_ms = millis();
  if (!M5Cardputer.Speaker.begin()) {
    drawStatus("Speaker failed");
    logf("[SPK]", "begin failed cost=%lums\n", (unsigned long)(millis() - speaker_start_ms));
    return;
  }
  M5Cardputer.Speaker.setVolume(TTS_VOLUME);
  logf("[SPK]", "begin ok cost=%lums volume=%u enabled=%d\n",
       (unsigned long)(millis() - speaker_start_ms),
       (unsigned)TTS_VOLUME,
       M5Cardputer.Speaker.isEnabled() ? 1 : 0);
  Serial.println();
  if (!streamTts(reply)) {
    drawStatus("TTS failed", reply);
    logf("[TURN]", "tts failed total=%lums\n", (unsigned long)(millis() - turn_start_ms));
    return;
  }
  logf("[TURN]", "done total=%lums\n", (unsigned long)(millis() - turn_start_ms));
  drawStatus("Ready", "Press BtnA to talk");
}

void setup() {
  Serial.begin(115200);
  auto cfg = M5.config();
  cfg.serial_baudrate = 115200;
  cfg.internal_mic = true;
  cfg.internal_spk = true;
  M5Cardputer.begin(cfg);
  M5Cardputer.Display.setRotation(1);
  M5Cardputer.Display.setTextScroll(false);
  M5Cardputer.Display.setFont(&fonts::efontCN_14);
  configureCardputerAdvMic();

  if (!parseBaseUrl(MIMO_BASE_URL)) {
    drawStatus("Config error", "MIMO_BASE_URL must be https");
    while (true) delay(1000);
  }
  connectWifi();
}

void loop() {
  M5Cardputer.update();
  if (M5Cardputer.BtnA.wasClicked()) {
    runConversation();
  }
  delay(10);
}
