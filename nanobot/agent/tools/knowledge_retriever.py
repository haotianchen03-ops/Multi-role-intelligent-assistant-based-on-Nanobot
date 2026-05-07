"""Knowledge Retriever tool - RAG-based knowledge search for the agent."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from loguru import logger

from nanobot.agent.tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from nanobot.services.milvus_rag import MilvusRAGService


class KnowledgeRetrieverTool(BaseTool):
    """RAG-based knowledge retriever using Milvus.
    
    Provides the agent with ability to search the knowledge base
    for relevant information to answer user questions.
    
    Returns top-K relevant chunks with citations.
    """

    name = "knowledge_retriever"
    description = """
    Search the knowledge base for relevant information to answer user questions.
    
    Use this when you need to find:
    - FAQ answers and solutions
    - Product documentation
    - Troubleshooting guides
    - Policy and procedures
    
    Input: A search query describing what information you need
    Output: Relevant knowledge chunks with confidence scores
    
    Examples:
    - "如何注册账户" -> Returns account registration FAQ
    - "API Key 怎么获取" -> Returns API key documentation
    - "登录失败怎么办" -> Returns troubleshooting guide
    """

    def __init__(
        self,
        milvus_service: MilvusRAGService | None = None,
        top_k: int = 5,
        min_relevance: float = 0.5,
    ):
        super().__init__()
        self._milvus = milvus_service
        self.top_k = top_k
        self.min_relevance = min_relevance

    def _get_service(self) -> MilvusRAGService:
        """Lazy load Milvus service."""
        if self._milvus is None:
            from nanobot.services.milvus_rag import MilvusRAGService
            self._milvus = MilvusRAGService()
            self._milvus.init()
        return self._milvus

    def execute(self, query: str, top_k: int | None = None, category: str | None = None) -> ToolResult:
        """Execute knowledge retrieval.
        
        Args:
            query: Search query (natural language)
            top_k: Override default top-k results
            category: Optional filter by category (faq, product, troubleshoot)
            
        Returns:
            ToolResult with relevant knowledge chunks
        """
        k = top_k or self.top_k
        
        try:
            service = self._get_service()
            
            # Build filter expression if category specified
            filter_expr = None
            if category:
                filter_expr = f'metadata["category"] == "{category}"'
            
            # Search
            results = service.search(
                query=query,
                top_k=k,
                filter_expr=filter_expr,
                return_metadata=True,
            )
            
            if not results:
                return ToolResult(
                    success=True,
                    output="No relevant knowledge found.",
                    data={"results": [], "query": query},
                )
            
            # Filter by minimum relevance
            filtered = [r for r in results if r["distance"] >= self.min_relevance]
            
            if not filtered:
                return ToolResult(
                    success=True,
                    output=f"Found {len(results)} results but none meet minimum relevance threshold ({self.min_relevance}).",
                    data={"results": results, "query": query},
                )
            
            # Format output
            lines = [f"Found {len(filtered)} relevant knowledge chunks:\n"]
            
            for i, result in enumerate(filtered, 1):
                meta = result.get("metadata", {})
                title = meta.get("title", "Untitled")
                cat = meta.get("category", "general")
                distance = result["distance"]
                
                lines.append(f"\n--- Result {i} (relevance: {distance:.2f}) ---")
                lines.append(f"Title: {title}")
                lines.append(f"Category: {cat}")
                lines.append(f"Content:\n{result['text'][:500]}...")
            
            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={
                    "results": filtered,
                    "query": query,
                    "count": len(filtered),
                },
            )
            
        except Exception as e:
            logger.error(f"Knowledge retrieval failed: {e}")
            return ToolResult(
                success=False,
                output=f"Knowledge retrieval failed: {str(e)}",
                error=str(e),
            )

    def get_context(self, query: str, top_k: int | None = None) -> str:
        """Get formatted context string for LLM prompt injection.
        
        Args:
            query: Search query
            top_k: Number of chunks to retrieve
            
        Returns:
            Formatted context string ready for LLM prompt
        """
        service = self._get_service()
        return service.get_context(query, top_k=top_k or self.top_k)


class HybridKnowledgeSearch:
    """Hybrid search combining PostgreSQL keyword + Milvus vector search.
    
    Uses PostgreSQL for exact keyword matching and Milvus for semantic search,
    then merges results using Reciprocal Rank Fusion (RRF).
    """

    def __init__(
        self,
        pg_service=None,
        milvus_service=None,
    ):
        self._pg = pg_service
        self._milvus = milvus_service
        self.rrf_k = 60  # RRF constant

    def _get_pg_service(self):
        if self._pg is None:
            from nanobot.services.postgres_kb import PostgresKBService
            self._pg = PostgresKBService()
        return self._pg

    def _get_milvus_service(self):
        if self._milvus is None:
            from nanobot.services.milvus_rag import MilvusRAGService
            self._milvus = MilvusRAGService()
            self._milvus.init()
        return self._milvus

    def search(
        self,
        query: str,
        top_k: int = 5,
        categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Hybrid search combining keyword and semantic search.
        
        Args:
            query: Search query
            top_k: Final number of results
            categories: Optional category filter
            
        Returns:
            Merged and ranked results
        """
        # Get PostgreSQL results (keyword search)
        pg_results = []
        try:
            pg_service = self._get_pg_service()
            from nanobot.services.postgres_kb import KBCategory
            cat = KBCategory(categories[0]) if categories else None
            pg_entries = pg_service.search(query, category=cat, limit=top_k * 2)
            
            for i, entry in enumerate(pg_entries):
                pg_results.append({
                    "id": entry.id,
                    "text": f"{entry.title}\n\n{entry.answer}",
                    "score": 1.0 / (i + 1),  # Rank-based score
                    "source": "postgres",
                    "metadata": {
                        "title": entry.title,
                        "category": entry.category.value,
                        "priority": entry.priority.value,
                    },
                })
        except Exception as e:
            logger.warning(f"PostgreSQL search failed: {e}")

        # Get Milvus results (semantic search)
        milvus_results = []
        try:
            milvus_service = self._get_milvus_service()
            filter_expr = None
            if categories:
                filter_expr = f'metadata["category"] == "{categories[0]}"'
            
            results = milvus_service.search(
                query=query,
                top_k=top_k * 2,
                filter_expr=filter_expr,
            )
            
            for result in results:
                milvus_results.append({
                    "id": result["id"],
                    "text": result["text"],
                    "score": result["distance"],
                    "source": "milvus",
                    "metadata": result.get("metadata", {}),
                })
        except Exception as e:
            logger.warning(f"Milvus search failed: {e}")

        # Reciprocal Rank Fusion
        fused = self._rrf(pg_results, milvus_results, k=self.rrf_k)
        
        # Return top-k
        return fused[:top_k]

    def _rrf(
        self,
        list1: list[dict],
        list2: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Reciprocal Rank Fusion."""
        scores = {}
        
        # Score from list1 (keyword search)
        for i, item in enumerate(sorted(list1, key=lambda x: x["score"], reverse=True)):
            key = item["id"]
            scores[key] = scores.get(key, 0) + (1 / (k + i + 1))
            scores[f"{key}_data"] = item
        
        # Score from list2 (semantic search)
        for i, item in enumerate(sorted(list2, key=lambda x: x["score"], reverse=True)):
            key = item["id"]
            scores[key] = scores.get(key, 0) + (1 / (k + i + 1))
            scores[f"{key}_data"] = item
        
        # Sort by fused score
        ranked = []
        seen_ids = set()
        
        for key in sorted(scores.keys()):
            if key.endswith("_data"):
                continue
            if key in seen_ids:
                continue
            
            data = scores.get(f"{key}_data")
            if data:
                data["fused_score"] = scores[key]
                ranked.append(data)
                seen_ids.add(key)
        
        return ranked
