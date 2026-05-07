# 知识库目录结构

> 知识库用于存储 FAQ、产品文档、故障排查指南等内容

---

## 目录结构

```
knowledge_base/
├── README.md              # 本文件 - 目录说明
├── faq/                   # 常见问题
│   ├── README.md
│   ├── account.md         # 账户相关FAQ
│   ├── billing.md         # 计费相关FAQ
│   ├── technical.md       # 技术相关FAQ
│   └── general.md         # 通用问题
├── products/              # 产品文档
│   ├── README.md
│   ├── overview.md        # 产品概览
│   ├── features.md        # 功能介绍
│   ├── pricing.md         # 定价说明
│   └── api-docs.md        # API文档
├── troubleshooting/        # 故障排查
│   ├── README.md
│   ├── common-errors.md    # 常见错误
│   ├── performance.md     # 性能问题
│   └── connectivity.md    # 连接问题
└── satisfaction.md         # 满意度评价功能
```

---

## 文件编写规范

### FAQ 文件格式

```markdown
# {类别} - 常见问题

## Q: {问题标题}

**分类**: {account/billing/technical/general}
**优先级**: {P1/P2/P3}
**更新**: {日期}

### 问题描述
{详细描述}

### 解决方案
{步骤1}
{步骤2}
{步骤3}

### 相关链接
- {链接1}
- {链接2}

### 反馈
👍 有帮助: {count} | 👎 需改进: {count}
```

### 产品文档格式

```markdown
---
title: {产品名称}
category: {product}
version: {版本}
last_updated: {日期}
---

# {产品名称}

## 概述
{简介}

## 主要功能
1. {功能1}
2. {功能2}
3. {功能3}

## 使用指南
{详细说明}

## 定价
| 套餐 | 价格 | 功能 |
|------|------|------|
| 免费版 | ¥0 | ... |
| 专业版 | ¥99/月 | ... |
| 企业版 | ¥299/月 | ... |
```

### 故障排查格式

```markdown
# 故障排查指南

## 问题名称
**严重程度**: {P1/P2/P3}
**影响范围**: {影响描述}

## 症状
{用户看到的现象}

## 可能原因
1. {原因1}
2. {原因2}

## 排查步骤
### 步骤1: {描述}
```bash
# 执行命令或操作
```
### 步骤2: {描述}
...

## 解决方案
{针对每个原因的解决方案}

## 预防措施
{如何避免再次发生}
```

---

## 搜索优先级

当用户提问时，按以下顺序匹配：

1. `troubleshooting/` - 如果提到"错误"、"无法"、"故障"
2. `faq/` - 匹配具体问题
3. `products/` - 匹配功能咨询
4. 默认回复 - 引导用户描述问题

---

## 更新频率

| 类别 | 更新频率 | 负责人 |
|------|---------|--------|
| faq/ | 按需更新 | 客服团队 |
| products/ | 每月检查 | 产品团队 |
| troubleshooting/ | 每周更新 | 技术团队 |

---

## 导入脚本

可以使用以下命令批量导入知识库：

```bash
python scripts/import_knowledge.py --path ./knowledge_base
```