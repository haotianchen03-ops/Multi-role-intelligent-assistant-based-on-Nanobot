# Publication Notes

This folder is the cleaned GitHub publication copy. It keeps the project code and examples, while excluding local runtime state, secrets, and one-off debugging scripts.

## Kept

- `nanobot/`: core Python package, Feishu channel, agent loop, tools, memory, cron, RAG and PostgreSQL services.
- `bridge/`: TypeScript bridge service.
- `tests/`: project tests.
- `prompts/`: prompt design notes.
- `examples/knowledge_base/`: Markdown knowledge-base examples copied from the local runtime workspace.
- `Dockerfile`, `pyproject.toml`, `README.md`, `LICENSE`, `SECURITY.md`, `KNOWLEDGE_BASE_SETUP.md`.

## Excluded

- `.git/`: removed so the new GitHub repository has a fresh history and only your account appears in Contributors.
- `workspace/`: local agent workspace and personal memory files.
- `C:\Users\sbsbs\.nanobot` and `D:\ai\.nanobot`: local runtime config, sessions, media, databases, embeddings, and secrets.
- `.env`: local environment variables.
- Runtime data: `sessions/`, `media/`, `data/`, `cron/`, `*.db`, `*.sqlite*`, `*.jsonl`, `*.log`.
- One-off scripts: `add_members.py`, `create_feishu_group.py`, `fetch_pages.py`, `fetch_putike.py`, `read_resume.py`, `resume_text.txt`, `check_cron.py`, `check_tasks.py`, `test_milvus_rag.py`.

## Security Notes

- Do not commit real Feishu `appSecret`, OpenAI keys, database passwords, session logs, or generated embedding indexes.
- Rotate any key that has ever appeared in a local file before publishing publicly.
