# 多模态处理指南

让 OpenSquilla Agent 理解和处理图像、音频、视频等多模态内容。

## 🎯 支持的模态

| 模态 | 输入格式 | 输出格式 | 主要模型 |
|------|---------|---------|----------|
| **文本** | txt, md, pdf | txt, md, json | 全部 LLM |
| **图像** | png, jpg, webp, gif | 描述、标签、OCR | GPT-4o, Claude 3.5 Sonnet |
| **音频** | mp3, wav, m4a | 文本、转录 | Whisper |
| **视频** | mp4, mov, webm | 描述、摘要 | GPT-4o |
| **文档** | pdf, docx, pptx | 提取、分析 | 专用模型 |

---

## 🖼️ 图像处理

### 图像理解

```yaml
# skills/image-analyst.md
---
name: image-analyst
description: 图像分析与理解
---

## 图像分析

### 场景描述

将图像转换为自然语言描述：

```python
from opensquilla import Agent

agent = Agent(name="image_analyst")

result = agent.run(
    message="描述这张图片",
    image="path/to/image.jpg"
)

print(result.response)
# 输出: "这是一张日落时分的海滩照片，天空呈现橙色和紫色的渐变..."
```

### 物体检测

识别图像中的物体：

```python
result = agent.run(
    message="列出图片中的所有物体",
    image="https://example.com/image.jpg"
)

print(result.response)
# 输出: "图片中包含：一只猫、一台笔记本电脑、一杯咖啡..."
```

### OCR 文字识别

提取图像中的文字：

```python
result = agent.run(
    message="提取图片中的所有文字",
    image="receipt.jpg"
)

print(result.response)
# 输出: "超市收据\n总计: ¥123.45\n日期: 2026-06-01"
```

### 图表分析

理解数据可视化：

```python
result = agent.run(
    message="分析这个图表并提取数据",
    image="chart.png"
)

print(result.response)
# 输出: "这是一个折线图，显示了过去6个月的收入增长..."
```

## 图像生成

### DALL-E 集成

```yaml
# config/providers/openai.yaml
providers:
  openai:
    image_models:
      - name: "dall-e-3"
        size: "1024x1024"
        quality: "standard"
        style: "vivid"
```

```python
from opensquilla import Agent

agent = Agent(name="image_generator")

result = agent.run(
    message="生成一张未来城市的图片，赛博朋克风格",
    params={
        "model": "dall-e-3",
        "size": "1024x1024",
        "quality": "hd"
    }
)

# result.media 包含生成的图片 URL
print(result.media[0].url)
```

---

## 🎵 音频处理

### 语音转文字

```yaml
# skills/transcriber.md
---
name: transcriber
description: 音频转录
---

## 音频转录

使用 Whisper 模型：

```python
from opensquilla import Agent

agent = Agent(name="transcriber")

result = agent.run(
    message="转录这段音频",
    audio="meeting.mp3",
    params={
        "language": "zh",
        "model": "whisper-large-v3"
    }
)

print(result.response)
# 输出: "今天我们讨论了第三季度的产品规划..."
```

### 支持的格式

| 格式 | 容器 | 编码器 |
|------|------|--------|
| MP3 | .mp3 | MPEG-1/2 Layer 3 |
| WAV | .wav | PCM |
| M4A | .m4a | AAC |
| OGG | .ogg | Opus |
| WEBM | .webm | Opus |

### 多语言转录

```python
# 自动检测语言
result = agent.run(
    message="转录并检测语言",
    audio="recording.wav"
)

# 指定语言
result = agent.run(
    message="转录这段中文音频",
    audio="speech.mp3",
    params={"language": "zh"}
)
```

### 字幕生成

```python
# 生成 SRT 字幕
result = agent.run(
    message="生成视频字幕",
    audio="video_audio.mp4",
    params={
        "format": "srt",
        "timestamps": True
    }
)

print(result.response)
# 输出:
# 1
# 00:00:00,000 --> 00:00:05,000
# 大家好，欢迎来到这个视频
```

### 说话人识别

```python
# 区分不同说话人
result = agent.run(
    message="转录会议记录并标注说话人",
    audio="meeting.wav",
    params={
        "speaker_diarization": true
    }
)

print(result.response)
# 输出:
# 说话人A: 让我们开始今天的会议
# 说话人B: 好的，第一个议题是...
```

---

## 🎬 视频处理

### 视频理解

```yaml
# skills/video-analyst.md
---
name: video_analyst
description: 视频分析
---

## 视频分析

### 场景描述

```python
from opensquilla import Agent

agent = Agent(name="video_analyst")

result = agent.run(
    message="描述这个视频的内容",
    video="product_demo.mp4"
)

print(result.response)
# 输出: "这个视频展示了一个新产品的功能演示，首先介绍了..."
```

### 动作识别

```python
result = agent.run(
    message="识别视频中的动作",
    video="exercise.mp4"
)

print(result.response)
# 输出: "视频中的人在做以下动作：深蹲、俯卧撑、拉伸..."
```

### 关键帧提取

```python
result = agent.run(
    message="提取视频的关键帧并描述",
    video="tutorial.mp4",
    params={
        "max_frames": 10
    }
)

# result.media 包含提取的关键帧
for frame in result.media:
    print(f"时间戳: {frame.timestamp}")
    print(f"描述: {frame.description}")
```

## 视频处理流程

```yaml
# workflows/video-processing.yaml
name: "video_content_analyzer"
description: "视频内容分析流程"

steps:
  # 提取音频
  - id: "extract_audio"
    tool: "ffmpeg"
    params:
      input: "{{video}}"
      output: "audio.mp3"

  # 转录音频
  - id: "transcribe"
    agent: "transcriber"
    input:
      audio: "audio.mp3"

  # 提取关键帧
  - id: "extract_frames"
    tool: "opencv"
    params:
      input: "{{video}}"
      interval: 5  # 每 5 秒

  # 分析帧
  - id: "analyze_frames"
    agent: "image_analyst"
    input:
      images: "{{extract_frames.frames}}"

  # 合并结果
  - id: "combine"
    agent: "summarizer"
    input:
      transcript: "{{transcribe.text}}"
      visual_summary: "{{analyze_frames.summary}}"
```

---

## 📄 文档处理

### PDF 处理

```yaml
# skills/document-processor.md
---
name: document_processor
description: 文档处理
---

## PDF 处理

### 文本提取

```python
from opensquilla import Agent

agent = Agent(name="document_processor")

# 提取文本
result = agent.run(
    message="提取这个 PDF 的文本内容",
    document: "report.pdf"
)

print(result.response)
```

### 表格提取

```python
result = agent.run(
    message="提取 PDF 中的所有表格并转换为 Markdown",
    document: "financial_report.pdf"
)

print(result.response)
# 输出:
# | 项目 | Q1 | Q2 | Q3 | Q4 |
# |------|----|----|----|-----|
# | 收入 | 100 | 120 | 130 | 150 |
```

### 文档分析

```python
result = agent.run(
    message="分析这份合同的关键条款",
    document: "contract.pdf"
)

print(result.response)
# 输出: "关键条款：\n1. 合同期限：3年\n2. 付款条件：..."
```

### 文档对比

```python
result = agent.run(
    message="对比这两个版本的差异",
    documents:
      - "contract_v1.pdf"
      - "contract_v2.pdf"
)

print(result.response)
# 输出: "主要差异：\n- 第3条：付款期限从30天改为45天..."
```

## Office 文档

### Word 处理

```python
# 处理 .docx
result = agent.run(
    message="总结这份文档的主要内容",
    document: "proposal.docx"
)
```

### PowerPoint 处理

```python
# 处理 .pptx
result = agent.run(
    message="提取幻灯片中的要点",
    document: "presentation.pptx"
)
```

---

## 🔄 多模态组合

### 图文对话

```python
from opensquilla import Agent

agent = Agent(name="multimodal_assistant")

# 同时发送文本和图片
result = agent.run(
    message="这张图片是什么？怎么修复这个问题？",
    image="error_screenshot.png"
)

print(result.response)
# 输出: "这是一个数据库连接错误的截图。问题原因是连接超时..."
```

### 视频问答

```python
result = agent.run(
    message="视频中第30秒发生了什么？",
    video: "tutorial.mp4"
)
```

### 文档视觉问答

```python
result = agent.run(
    message="第5页的图表说明了什么？",
    document: "report.pdf"
)
```

---

## ⚙️ 配置

### 模型配置

```yaml
# config/multimodal/models.yaml
models:
  # 图像理解
  vision:
    default: "gpt-4o"
    alternatives:
      - "claude-3-5-sonnet"
      - "gemini-1.5-pro"

  # 图像生成
  image_generation:
    default: "dall-e-3"
    alternatives:
      - "midjourney"
      - "stable-diffusion"

  # 音频转录
  audio:
    default: "whisper-large-v3"
    alternatives:
      - "whisper-medium"
      - "whisper-small"

  # 视频理解
  video:
    default: "gpt-4o"
    alternatives:
      - "gemini-1.5-pro"
```

### 处理限制

```yaml
# config/multimodal/limits.yaml
limits:
  # 图像
  image:
    max_size: 20971520  # 20MB
    max_dimensions: [7680, 7680]
    supported_formats:
      - "png"
      - "jpg"
      - "webp"
      - "gif"

  # 音频
  audio:
    max_size: 52428800  # 50MB
    max_duration: 3600  # 1 小时
    supported_formats:
      - "mp3"
      - "wav"
      - "m4a"

  # 视频
  video:
    max_size: 524288000  # 500MB
    max_duration: 600  # 10 分钟
    supported_formats:
      - "mp4"
      - "mov"
      - "webm"

  # 文档
  document:
    max_size: 52428800  # 50MB
    max_pages: 100
    supported_formats:
      - "pdf"
      - "docx"
      - "pptx"
```

---

## 🎯 实战案例

### 案例一：发票处理

```yaml
# skills/invoice-processor.md
---
name: invoice_processor
description: 发票智能处理
---

## 发票处理流程

### 输入

- 发票图片（PDF 或图片格式）

### 处理步骤

1. OCR 识别文字
2. 提取关键信息
3. 验证数据格式
4. 存入数据库

### 配置

```yaml
extraction:
  fields:
    - name: "发票号码"
      type: "string"
      pattern: "\\d{8,12}"

    - name: "日期"
      type: "date"
      format: "YYYY-MM-DD"

    - name: "金额"
      type: "decimal"

    - name: "税额"
      type: "decimal"

    - name: "销售方"
      type: "string"
```

### 使用

```python
result = agent.run(
    message="处理这张发票",
    document: "invoice.pdf",
    params={
        "output_format": "json"
    }
)

# 输出 JSON
print(result.data)
# {
#   "invoice_number": "12345678",
#   "date": "2026-06-01",
#   "amount": 1000.00,
#   "tax": 130.00,
#   "vendor": "ABC 公司"
# }
```

---

### 案例二：会议记录

```yaml
# skills/meeting-note-taker.md
---
name: meeting_note_taker
description: 会议记录生成
---

## 会议记录生成

### 输入

- 会议录音/视频
- 参会人员名单

### 处理

1. 转录音频
2. 识别说话人
3. 提取要点
4. 生成行动项

### 使用

```python
result = agent.run(
    message="生成会议记录",
    video: "meeting.mp4",
    context: {
        "attendees": ["张三", "李四", "王五"],
        "meeting_type": "周会"
    }
)

print(result.response)
# 输出:
# # 产品周会会议记录
#
# **时间**: 2026-06-01 10:00-11:00
# **参会人**: 张三、李四、王五
#
# ## 讨论要点
# 1. Q2 产品规划
# 2. 用户反馈分析
#
# ## 行动项
# - [张三] 完成技术方案（截止：6月10日）
# - [李四] 准备用户调研（截止：6月15日）
```

---

## 📞 相关资源

- [工作流自动化](../workflows/automation.md)
- [技能模板](../skills/README.md)
- [API 服务](../api/service.md)
- [提供商配置](../providers/README.md)
