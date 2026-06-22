API_KEY = "tp-your-key-here"
TTS_VOICE = "冰糖"
SYSTEM_PROMPT = "你是一个智能助手，正在通过语音与用户对话。请用简洁的语言回答，适合语音场景，不要使用 Markdown 格式。"

# 语音检测阈值配置
# SILENCE_THRESHOLD: 静音阈值，音量低于此值认为是静音
# 范围：0-10000，建议值：500-2000
# 值越小越敏感，值越大越不敏感
# 可以通过运行 python example.py noise 测试环境噪音来确定合适值
SILENCE_THRESHOLD = 800

# 静音时长（秒），静音多久后停止录音并发送
# 范围：0.5-5.0，建议值：1.0-3.0
SILENCE_DURATION = 2.0

# 最小录音时长（秒），避免太短的噪音
# 范围：0.1-2.0，建议值：0.3-1.0
MIN_RECORD_DURATION = 0.5

# 开始录音的持续时间（秒），音量持续超过阈值多久才开始录音
# 范围：0.05-1.0，建议值：0.1-0.3
# 值越大越不容易被短暂噪音触发，但会延迟录音开始
START_DURATION = 0.1

# TTS播放模式配置
# TTS_STREAMING: 是否使用流式播放
# True - 流式播放，延迟更低，边接收边播放
# False - 文件模式，先下载完整音频再播放
TTS_STREAMING = True
