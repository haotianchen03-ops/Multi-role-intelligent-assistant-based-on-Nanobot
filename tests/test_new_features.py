"""Test script for new session management and semantic search features."""

import asyncio
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from nanobot.session.manager import SessionManager
from nanobot.session.embedding_index import EmbeddingIndex


def test_session_management():
    """Test session create/switch/list/reset."""
    print("\n" + "="*60)
    print("测试 1: Session 管理")
    print("="*60)
    
    workspace = Path(__file__).parent.parent / "workspace"
    manager = SessionManager(workspace)
    
    # 1. 创建新会话
    print("\n[1] 创建会话 'test_python'...")
    s1 = manager.get_or_create("test_python")
    s1.add_message("user", "我想学习 Python 编程")
    s1.add_message("assistant", "好的，我来教你 Python！")
    manager.save(s1)
    print(f"[OK] 会话已创建: {s1.key}")
    
    # 2. 再创建一个
    print("\n[2] 创建会话 'test_project'...")
    s2 = manager.get_or_create("test_project")
    s2.add_message("user", "我想开发一个网站")
    s2.add_message("assistant", "可以用 Flask 或 Django。")
    manager.save(s2)
    print(f"[OK] 会话已创建: {s2.key}")
    
    # 3. 列出会话
    print("\n[3] 列出所有会话...")
    sessions = manager.list_sessions()
    print(f"共有 {len(sessions)} 个会话:")
    for s in sessions[:10]:
        print(f"  - {s.get('key', '?')}: {s.get('title', '(无标题)')}")
    
    # 4. 切换到第一个会话
    print("\n[4] 切换到 'test_python'...")
    s3 = manager.switch_to("test_python")
    print(f"当前会话: {s3.key}, 消息数: {len(s3.messages)}")
    
    # 5. 添加新消息
    print("\n[5] 添加新消息...")
    s3.add_message("user", "Python 有什么优点？")
    manager.save(s3)
    print("✓ 消息已保存")
    
    # 6. 重置会话
    print("\n[6] 重置到默认会话...")
    s4 = manager.switch_to(None)
    print(f"[OK] 当前会话: {s4.key}")
    
    return manager


def test_embedding_index(manager: SessionManager):
    """Test semantic embedding index."""
    print("\n" + "="*60)
    print("测试 2: Embedding 索引")
    print("="*60)
    
    # 检查模型是否可用
    idx = manager._get_embedding_index()
    if idx is None or idx._model is None:
        print("\n⚠️  Embedding 模型未安装，跳过语义搜索测试")
        print("   运行: pip install sentence-transformers")
        return
    
    # 索引已有会话
    print("\n[1] 索引会话消息...")
    count = manager.index_session("test_python")
    print(f"[OK] 索引了 {count} 条消息")
    
    count2 = manager.index_session("test_project")
    print(f"[OK] 索引了 {count2} 条消息")
    
    # 语义搜索
    print("\n[2] 语义搜索测试...")
    
    queries = [
        ("Python 编程", 3),
        ("网站开发", 3),
        ("学习新东西", 3),
    ]
    
    for query, top_k in queries:
        print(f"\n  查询: '{query}'")
        results = manager.semantic_search(query, top_k=top_k)
        for i, r in enumerate(results, 1):
            content = r["content"][:50] + "..." if len(r["content"]) > 50 else r["content"]
            score = r.get("relevance_score", 0)
            print(f"    {i}. [{r['role']}] {content}")
            print(f"       相关度: {score:.4f}")


def test_history_search_tool():
    """Test the history_search tool directly."""
    print("\n" + "="*60)
    print("测试 3: HistorySearchTool 工具")
    print("="*60)
    
    from nanobot.agent.tools.history_search import HistorySearchTool
    
    workspace = Path(__file__).parent.parent / "workspace"
    manager = SessionManager(workspace)
    tool = HistorySearchTool(manager)
    
    print("\n[1] 测试 tool 描述...")
    print(f"  名称: {tool.name}")
    print(f"  描述: {tool.description[:100]}...")
    
    print("\n[2] 调用 tool 搜索...")
    
    async def run_tool():
        result = await tool.execute(query="Python", top_k=3)
        return result
    
    result = asyncio.run(run_tool())
    print(f"\n结果:\n{result}")


def main():
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print("==> 开始测试新功能")
    print("-" * 60)
    
    # Test 1: Session 管理
    manager = test_session_management()
    
    # Test 2: Embedding 索引
    test_embedding_index(manager)
    
    # Test 3: HistorySearchTool
    test_history_search_tool()
    
    print("\n" + "="*60)
    print("[DONE] 测试完成!")
    print("="*60)
    
    print("""
下一步:
1. 重启机器人使新工具生效
2. 在对话中尝试:
   - "创建一个叫学习的会话"
   - "搜索我之前问过的 Python 问题"
   - "列出所有会话"
3. 可选: 运行 manager.rebuild_index() 重建完整索引
""")


if __name__ == "__main__":
    main()
