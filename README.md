# Multi-role Intelligent Assistant Based on Nanobot

基于 nanobot 二次开发的智能问答助手。项目围绕企业知识库问答、飞书机器人接入、长短期记忆、工具调用、文档解析、图片生成和多会话管理做了完整扩展，适合部署为一个可在飞书、discord、钉钉、微信等平台中使用的个人或团队 AI 助手。

本项目基于 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的轻量级 agent 框架进行扩展，保留其简洁的 CLI 和工具系统，同时增强了飞书通道、知识库检索、上下文压缩、长期记忆和可观测性。

---

## 目录

- [项目概览](#项目概览)
- [核心能力](#核心能力)
- [系统架构](#系统架构)
- [核心模块](#核心模块)
- [目录结构](#目录结构)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [飞书机器人配置](#飞书机器人配置)
- [知识库问答配置](#知识库问答配置)

---

## 项目概览

这是一个面向飞书场景的多角色智能助手系统。用户可以在飞书中向机器人提问，系统会根据上下文、长期记忆、知识库和可用工具生成回答，并通过飞书卡片、文本、图片或文件形式返回结果。

典型使用场景包括：

- 企业内部知识库问答
- 飞书群聊或私聊 AI 助手
- 多轮上下文记忆与偏好记忆
- PDF、网页、Notion、知识库文档辅助处理
- 后台任务、定时任务和子代理任务
- 对工具调用过程进行透明展示和记录

---

## 核心能力

| 能力 | 说明 |
|------|------|
| 飞书机器人接入 | 支持飞书长连接 WebSocket、消息接收、卡片回复、图片上传和文件发送 |
| 智能问答 | 通过 LiteLLM 接入 OpenAI、OpenRouter、DeepSeek、Gemini、Moonshot 等模型 |
| 知识库检索 | 支持 PostgreSQL 结构化知识库和 Milvus/Chroma 向量检索 |
| 长期记忆 | 使用 SQLite 保存用户偏好、决策、约束、资料和项目上下文 |
| 上下文压缩 | 自动压缩长会话，降低 token 消耗并保持对话连续性 |
| 工具调用 | 内置文件、Shell、网页搜索、PDF 解析、Notion、图片生成、消息发送等工具 |
| 多会话管理 | 支持创建、切换、列出和重置会话 |
| 子代理执行 | 支持 spawn 子代理处理复杂或耗时任务 |
| 定时任务 | 支持 cron 风格的后台定时任务 |
| 可观测性 | 飞书中可展示工具调用、token 使用和任务执行状态 |

---

## 系统架构

```text
用户 / 飞书群聊
        |
        v
飞书开放平台 WebSocket 长连接
        |
        v
nanobot.channels.feishu
        |
        v
MessageBus 消息总线
        |
        v
AgentLoop 核心推理循环
        |
        +--> LiteLLM Provider
        |       +--> OpenAI / OpenRouter / DeepSeek / Gemini / Moonshot / 自托管模型
        |
        +--> ContextBuilder
        |       +--> 会话历史
        |       +--> 长期记忆
        |       +--> 知识库检索结果
        |
        +--> ToolRegistry
                +--> 文件工具
                +--> 网页搜索
                +--> PDF 解析
                +--> Notion
                +--> 图片生成
                +--> 知识库检索
                +--> 子代理
                +--> 定时任务
```

---

## 核心模块

### 1. Feishu Channel

`nanobot/channels/feishu.py` 是飞书接入核心模块，负责：

- 建立飞书长连接
- 接收私聊和群聊消息
- 发送普通文本、互动卡片、图片和文件
- 支持 CardKit 流式更新
- 自动上传本地图片并替换为飞书 `image_key`
- 对收到的消息进行回执和反应反馈

### 2. Agent Loop

`nanobot/agent/loop.py` 是智能体主循环，负责：

- 构建系统提示词和上下文
- 调用大模型
- 判断并执行工具调用
- 记录工具结果
- 汇总 token 使用情况
- 将最终结果发送回通道

### 3. Memory System

长期记忆系统由以下模块组成：

| 模块 | 作用 |
|------|------|
| `personal_memory_store.py` | SQLite 记忆存储 |
| `memory_compiler.py` | 从对话中提取和合并记忆 |
| `memory_retriever.py` | 根据当前上下文召回相关记忆 |
| `memory_search.py` | 让 agent 主动搜索长期记忆 |

记忆类型包括 `preference`、`decision`、`reference`、`constraint` 和 `profile`。

### 4. Knowledge Base

项目提供两类知识库能力：

- PostgreSQL：适合 FAQ、工单、产品文档等结构化数据
- Milvus/Chroma：适合语义检索和 RAG 问答

示例知识库位于：

```text
examples/knowledge_base/
```

### 5. Tool System

内置工具位于 `nanobot/agent/tools/`，包括：

| 工具 | 说明 |
|------|------|
| `filesystem` | 文件读取、写入、追加、编辑和目录查看 |
| `shell` | 执行 Shell 命令 |
| `web` | 网页搜索和网页抓取 |
| `pdf_mineru` | 使用 MinerU 解析 PDF |
| `notion` | Notion 数据库管理和文档上传 |
| `image_generate` | OpenAI 兼容图片生成接口 |
| `message` | 主动发送消息到飞书等通道 |
| `spawn` | 启动子代理 |
| `cron` | 定时任务 |
| `knowledge_retriever` | 知识库检索 |
| `session_manage` | 会话管理 |

---

## 目录结构

```text
nanobot-feishu-github/
|-- README.md                       # 项目说明
|-- pyproject.toml                  # Python 包配置
|-- Dockerfile                      # Docker 构建配置
|-- LICENSE                         # 开源许可证
|-- SECURITY.md                     # 安全说明
|-- KNOWLEDGE_BASE_SETUP.md         # 知识库配置说明
|-- .env.example.knowledge          # 知识库环境变量示例
|-- PUBLICATION_NOTES.md            # 发布清理记录
|
|-- nanobot/                        # Python 主程序
|   |-- agent/                      # Agent 主循环、上下文、记忆、子代理
|   |-- agent/tools/                # 工具系统
|   |-- channels/                   # 飞书、Telegram、Discord、WhatsApp 通道
|   |-- cli/                        # 命令行入口
|   |-- config/                     # 配置加载和 Pydantic schema
|   |-- cron/                       # 定时任务服务
|   |-- heartbeat/                  # 心跳服务
|   |-- providers/                  # LLM Provider
|   |-- services/                   # PostgreSQL 和向量知识库服务
|   |-- session/                    # 会话管理和上下文压缩
|   |-- skills/                     # 内置技能说明
|   |-- scripts/                    # 知识库导入脚本
|   `-- utils/                      # 通用工具函数
|
|-- bridge/                         # TypeScript bridge 服务
|   |-- package.json
|   |-- tsconfig.json
|   `-- src/
|
|-- examples/
|   `-- knowledge_base/             # 示例知识库 Markdown 文档
|
|-- prompts/                        # Prompt 设计文档
`-- tests/                          # 测试用例
```

---

## 技术栈

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 主程序和 agent 框架 |
| Typer | CLI 命令行 |
| Pydantic | 配置和数据结构校验 |
| LiteLLM | 多模型供应商统一调用 |
| lark-oapi | 飞书开放平台 SDK |
| PostgreSQL / psycopg3 | 结构化知识库和业务数据 |
| Milvus Lite / Chroma | 向量检索与 RAG |
| SQLite | 长期记忆和本地状态 |
| httpx / websockets | HTTP 与 WebSocket 通信 |
| Notion API | Notion 数据库集成 |
| MinerU | PDF 文档解析 |
| TypeScript | bridge 服务 |
| pytest | 自动化测试 |

---

## 快速开始

### 1. 克隆项目

```bash
cd [你希望存放项目的路径]
git clone https://github.com/haotianchen03-ops/Multi-role-intelligent-assistant-based-on-Nanobot.git
```

### 2. 创建环境并安装

```bash
conda create --name nanobot python=3.12.7
```

### 3. 初始化配置

```bash
conda activate nanobot
nanobot onboard
```

默认配置目录为：

```text
~/.nanobot/config.json
```

也可以通过环境变量指定：

```bash
set NANOBOT_HOME=C:\path\to\.nanobot
```

PowerShell:

```powershell
$env:NANOBOT_HOME="C:\path\to\.nanobot"
```

### 4. 配置模型 Key

在 `config.json` 中填写至少一个模型供应商，例如：

```json
{
  "providers": {
    "openai": {
      "apiKey": "your_openai_api_key"
    },
    "openrouter": {
      "apiKey": "your_openrouter_api_key"
    }
  }
}
```

### 5. 本地 CLI 测试

```bash
nanobot agent -m "你好，介绍一下你能做什么"
```

进入交互模式：

```bash
nanobot agent
```

### 6. 启动飞书网关

```bash
nanobot gateway
```

---

## 飞书机器人配置

1. 打开 [飞书开放平台](https://open.feishu.cn/app)
2. 创建企业自建应用
3. 启用机器人能力
4. 在凭证与基础信息中获取 `App ID` 和 `App Secret`
5. 事件订阅选择长连接模式
6. 订阅 `im.message.receive_v1`
7. 添加必要权限并发布应用

建议权限包括：

| 权限 | 用途 |
|------|------|
| `im:message` | 发送消息 |
| `im:message:send_as_bot` | 以机器人身份发送消息 |
| `im:resource` | 下载和上传图片资源 |
| `im:message:readonly` | 读取消息 |
| `im:message.p2p_msg:readonly` | 读取私聊消息 |
| `cardkit:card:write` | 创建和更新互动卡片 |
| `docs:document.content:read` | 读取飞书云文档内容 |

配置示例：

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "your_app_id",
      "appSecret": "your_app_secret",
      "cardTemplateId": "your_card_template_id",
      "streamingEnabled": true
    }
  }
}
```

---

## 知识库问答配置

### PostgreSQL

复制示例环境变量：

```bash
copy .env.example.knowledge .env
```

修改 `.env` 中的数据库连接信息：

```env
NANOBOT_TOOLS__POSTGRES_KB__ENABLED=true
NANOBOT_TOOLS__POSTGRES_KB__HOST=localhost
NANOBOT_TOOLS__POSTGRES_KB__PORT=5432
NANOBOT_TOOLS__POSTGRES_KB__DATABASE=nanobot_db
NANOBOT_TOOLS__POSTGRES_KB__USER=postgres
NANOBOT_TOOLS__POSTGRES_KB__PASSWORD=your_password
```

### Milvus / Chroma

向量库示例：

```env
NANOBOT_TOOLS__MILVUS_RAG__ENABLED=true
NANOBOT_TOOLS__MILVUS_RAG__DB_PATH=.nanobot/data/milvus_lite.db
NANOBOT_TOOLS__MILVUS_RAG__COLLECTION_NAME=nanobot_knowledge
NANOBOT_TOOLS__MILVUS_RAG__EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
NANOBOT_TOOLS__MILVUS_RAG__EMBEDDING_DEVICE=cpu
```

导入示例知识库：

```bash
python -m nanobot.scripts.import_knowledge --kb-path examples/knowledge_base --target all
```


