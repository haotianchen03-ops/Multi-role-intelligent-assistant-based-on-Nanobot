# Knowledge Base Setup Guide

> PostgreSQL + Milvus Lite + Qwen3-Embedding 知识库配置指南

---

## 📦 依赖安装

```bash
# PostgreSQL 相关
pip install psycopg2-binary

# Milvus Lite (serverless mode)
pip install pymilvus[serverless]

# Qwen3-Embedding
pip install transformers torch

# 可选：更好的中文分词
pip install jieba
```

---

## 🗄️ 1. PostgreSQL 知识库

### 1.1 启动 PostgreSQL

使用 Docker：
```bash
docker run -d \
  --name nanobot-postgres \
  -e POSTGRES_DB=nanobot_kb \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_password \
  -p 5432:5432 \
  postgres:16
```

### 1.2 配置环境变量

```bash
# .env 文件
NANOBOT_TOOLS__POSTGRES_KB__ENABLED=true
NANOBOT_TOOLS__POSTGRES_KB__HOST=localhost
NANOBOT_TOOLS__POSTGRES_KB__PORT=5432
NANOBOT_TOOLS__POSTGRES_KB__DATABASE=nanobot_kb
NANOBOT_TOOLS__POSTGRES_KB__USER=postgres
NANOBOT_TOOLS__POSTGRES_KB__PASSWORD=your_password
```

### 1.3 初始化数据库

```python
from nanobot.services.postgres_kb import PostgresKBService

kb = PostgresKBService()
kb.init_db()  # 创建表结构
```

---

## 🔍 2. Milvus Lite (本地向量数据库)

### 2.1 特点

- ✅ 无需安装服务器，纯 Python
- ✅ 数据存储在本地文件 `milvus_lite.db`
- ✅ 支持向量检索和过滤
- ✅ 适合开发/测试/小规模数据

### 2.2 配置

```bash
# .env 文件
NANOBOT_TOOLS__MILVUS_RAG__ENABLED=true
NANOBOT_TOOLS__MILVUS_RAG__DB_PATH=D:/ai/.nanobot/data/milvus_lite.db
NANOBOT_TOOLS__MILVUS_RAG__DIMENSION=1024
NANOBOT_TOOLS__MILVUS_RAG__EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B
NANOBOT_TOOLS__MILVUS_RAG__EMBEDDING_DEVICE=cpu
```

### 2.3 初始化

```python
from nanobot.services.milvus_rag import MilvusRAGService

rag = MilvusRAGService()
rag.init()  # 创建 Collection
```

---

## 🤖 3. Qwen3-Embedding 模型

### 3.1 模型规格

| 模型 | 维度 | 上下文长度 | 设备支持 |
|------|------|-----------|---------|
| Qwen/Qwen3-Embedding-0.6B | 1024 | 32K | CPU/GPU |

### 3.2 首次使用

首次调用会下载模型（约 1.2GB），请耐心等待：

```python
rag = MilvusRAGService()
rag._embed_texts(["测试文本"])  # 触发模型下载
```

### 3.3 GPU 加速

```python
rag = MilvusRAGService(embedding_device="cuda")
rag.init()
```

---

## 📥 4. 导入知识库

### 4.1 一键导入

```bash
# 导入到 PostgreSQL
python -m nanobot.scripts.import_knowledge --target postgres

# 导入到 Milvus
python -m nanobot.scripts.import_knowledge --target milvus

# 导入到两者
python -m nanobot.scripts.import_knowledge --target all
```

### 4.2 自定义路径

```bash
python -m nanobot.scripts.import_knowledge \
  --kb-path D:/your/knowledge_base \
  --target all
```

### 4.3 导入日志示例

```
2026-04-30 17:30:00 | INFO | Loading knowledge base from: D:/ai/.nanobot/workspace/knowledge_base
2026-04-30 17:30:01 | INFO | Parsing FAQ: account.md -> 5 entries
2026-04-30 17:30:02 | INFO | Parsing FAQ: billing.md -> 3 entries
2026-04-30 17:30:05 | INFO | Total entries loaded: 28
2026-04-30 17:30:05 | SUCCESS | Imported 28 entries to PostgreSQL
2026-04-30 17:30:10 | INFO | Generating embeddings for 52 chunks...
2026-04-30 17:30:15 | SUCCESS | Imported 52 chunks to Milvus
2026-04-30 17:30:15 | SUCCESS | Import completed!
```

---

## 🔧 5. 在 Agent 中使用

### 5.1 方式一：直接调用 RAG 服务

```python
from nanobot.services.milvus_rag import MilvusRAGService

rag = MilvusRAGService()
rag.init()

# 搜索
results = rag.search("如何注册", top_k=5)
print(results[0]["text"])

# 获取 LLM 上下文
context = rag.get_context("API Key 问题", top_k=3)
```

### 5.2 方式二：使用 Tool

```python
from nanobot.agent.tools.knowledge_retriever import KnowledgeRetrieverTool

tool = KnowledgeRetrieverTool(top_k=5)
result = tool.execute("注册账户")
print(result.output)
```

### 5.3 方式三：混合搜索

```python
from nanobot.agent.tools.knowledge_retriever import HybridKnowledgeSearch

searcher = HybridKnowledgeSearch()
results = searcher.search("密码问题", top_k=5)
# 返回 PostgreSQL 关键词 + Milvus 语义 的融合结果
```

---

## 🧪 6. 测试

```bash
# 测试 Milvus RAG 服务
python test_milvus_rag.py
```

预期输出：
```
=== Test 1: Initialization ===
✅ Milvus Lite initialized successfully

=== Test 2: Embedding Generation ===
⏳ Loading Qwen3-Embedding model...
✅ Generated 3 embeddings
   Embedding dimension: 1024

=== Test 3: Add Documents ===
✅ Added 4 documents

=== Test 4: Semantic Search ===
📝 Query: '注册账户'
   Found 2 results
   [1] faq (score: 0.892)
       如何注册账户？...

=== Test 5: Get Context ===
✅ Generated context:
--- Relevant Knowledge (Top 2) ---
[1] (faq) 如何注册账户？...
[2] (faq) 忘记密码怎么办...
```

---

## 📁 文件结构

```
nanobot/
├── services/
│   ├── __init__.py
│   ├── postgres_kb.py      # PostgreSQL 知识库服务
│   └── milvus_rag.py       # Milvus RAG 服务
├── agent/tools/
│   └── knowledge_retriever.py  # RAG 检索工具
├── utils/
│   └── chunking.py         # 文本分块工具
├── scripts/
│   └── import_knowledge.py # 导入脚本
├── config/
│   └── schema.py           # 配置项（已更新）
├── test_milvus_rag.py      # 测试脚本
└── .env.example.knowledge  # 配置模板
```

---

## ❓ 常见问题

### Q1: 模型下载失败？
```python
# 设置 HuggingFace 镜像
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
```

### Q2: Milvus Lite 数据损坏？
```python
rag = MilvusRAGService()
rag.reset()  # 删除并重建
rag.init()
```

### Q3: PostgreSQL 连接失败？
```bash
# 检查 Docker 是否运行
docker ps | grep postgres

# 检查端口
netstat -an | grep 5432
```

### Q4: 内存不足？
```python
# 减小批次大小
rag.add_documents(docs, batch_size=16)  # 默认 32
```

---

## 🚀 下一步

1. ✅ 运行测试脚本验证安装
2. ✅ 导入你的知识库
3. ✅ 在 FAQ Skill 中集成 RAG
4. ✅ 优化搜索效果
