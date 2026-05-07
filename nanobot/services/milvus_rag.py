"""Vector Store Service - Supports Milvus Lite and ChromaDB backends.

Uses Qwen3-Embedding for text vectorization.
Milvus Lite: Native, serverless, file-based (recommended for development)
ChromaDB: Alternative pure-Python solution

Usage:
    # With Milvus Lite (recommended)
    vector_store = VectorStoreService(provider="milvus")
    vector_store.init()
    
    # With ChromaDB
    vector_store = VectorStoreService(provider="chroma")
    vector_store.init()
    
    # Add documents
    vector_store.add_documents([
        {"text": "如何注册账户", "metadata": {"category": "faq"}},
    ])
    
    # Search
    results = vector_store.search("注册", top_k=5)
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from nanobot.utils.helpers import ensure_dir, get_data_path


# Constants
DEFAULT_DB_PATH = get_data_path() / "vector_store.db"
COLLECTION_NAME = "nanobot_knowledge"
DIMENSION = 1024  # Qwen3-Embedding output dimension


class VectorStoreService:
    """Vector Store Service supporting multiple backends.
    
    Supported providers:
    - "milvus": Milvus Lite (serverless, file-based)
    - "chroma": ChromaDB (pure Python, easier to install)
    
    Features:
    - Local file-based storage
    - Qwen3-Embedding for text vectorization
    - Top-K semantic search
    - Metadata filtering
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        collection_name: str = COLLECTION_NAME,
        dimension: int = DIMENSION,
        provider: Literal["milvus", "chroma"] = "chroma",  # Default to chromadb
        embedding_model: str = "Qwen/Qwen3-Embedding-0.6B",
        embedding_device: str = "cpu",
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.collection_name = collection_name
        self.dimension = dimension
        self.provider = provider
        self.embedding_model_name = embedding_model
        self.embedding_device = embedding_device

        self._client = None
        self._collection = None
        self._embedding_model = None
        self._chroma_client = None

    def _ensure_dir(self) -> None:
        """Ensure data directory exists."""
        ensure_dir(self.db_path.parent)

    def _init_milvus(self) -> None:
        """Initialize Milvus Lite client."""
        if self._client is not None:
            return

        try:
            from pymilvus import MilvusClient
            self._ensure_dir()
            logger.info(f"Connecting to Milvus Lite at {self.db_path}")
            self._client = MilvusClient(uri=str(self.db_path))
            logger.info("Milvus Lite connected successfully")
        except ImportError as e:
            raise ImportError(
                "pymilvus not installed or milvus_lite module missing. "
                "Try: pip install pymilvus==2.4.0"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Milvus Lite: {e}") from e

    def _init_chroma(self) -> None:
        """Initialize ChromaDB client."""
        if self._chroma_client is not None:
            return

        try:
            import chromadb
            from chromadb.config import Settings
            
            self._ensure_dir()
            logger.info(f"Connecting to ChromaDB at {self.db_path}")
            
            # Use persistent client to store data locally
            self._chroma_client = chromadb.PersistentClient(
                path=str(self.db_path.parent / "chroma_db"),
                settings=Settings(anonymized_telemetry=False)
            )
            logger.info("ChromaDB connected successfully")
        except ImportError:
            raise ImportError(
                "chromadb not installed. Run: pip install chromadb"
            )

    def _init_embedding_model(self) -> None:
        """Initialize Qwen embedding model."""
        if self._embedding_model is not None:
            return

        import os
        os.environ["TOKENIZERS_PARALLELISM"] = "false"

        try:
            from transformers import AutoTokenizer, AutoModel
            import torch

            logger.info(f"Loading embedding model: {self.embedding_model_name}")

            tokenizer = AutoTokenizer.from_pretrained(
                self.embedding_model_name,
                trust_remote_code=True,
            )
            model = AutoModel.from_pretrained(
                self.embedding_model_name,
                trust_remote_code=True,
            )

            if self.embedding_device == "cuda" and torch.cuda.is_available():
                model = model.to("cuda")
                logger.info("Embedding model loaded on CUDA")
            else:
                logger.info("Embedding model loaded on CPU")

            self._embedding_model = {
                "tokenizer": tokenizer,
                "model": model,
            }
            logger.info(f"Embedding model '{self.embedding_model_name}' loaded")

        except ImportError as e:
            raise ImportError(
                "transformers/torch not installed. Run: pip install transformers torch"
            ) from e
        except Exception as e:
            logger.warning(f"Failed to load Qwen3-Embedding, falling back to all-MiniLM-L6-v2: {e}")
            self._init_fallback_embedding()

    def _init_fallback_embedding(self) -> None:
        """Initialize fallback embedding model (all-MiniLM-L6-v2)."""
        try:
            from sentence_transformers import SentenceTransformer
            
            logger.info("Loading fallback embedding model: all-MiniLM-L6-v2")
            model = SentenceTransformer("all-MiniLM-L6-v2")
            self._embedding_model = {
                "tokenizer": None,
                "model": model,
                "fallback": True,
            }
            self.dimension = 384  # all-MiniLM-L6-v2 dimension
            logger.info("Fallback embedding model loaded")
        except ImportError:
            raise ImportError(
                "No embedding model available. Install either:\n"
                "  - transformers torch (for Qwen3-Embedding)\n"
                "  - sentence_transformers (for all-MiniLM-L6-v2)"
            )

    def _embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts.
        
        Args:
            texts: List of text strings to embed
            
        Returns:
            List of embedding vectors
        """
        self._init_embedding_model()

        model = self._embedding_model["model"]
        is_fallback = self._embedding_model.get("fallback", False)

        if is_fallback:
            # Using sentence-transformers
            embeddings = model.encode(texts, normalize_embeddings=True)
            return embeddings.tolist()
        else:
            # Using transformers with Qwen3-Embedding
            import torch
            import torch.nn.functional as F

            tokenizer = self._embedding_model["tokenizer"]

            encoded = tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=8192,
                return_tensors="pt",
            )

            if self.embedding_device == "cuda" and torch.cuda.is_available():
                encoded = {k: v.to("cuda") for k, v in encoded.items()}
                model = model.to("cuda")

            with torch.no_grad():
                outputs = model(**encoded)
                attention_mask = encoded["attention_mask"]
                token_embeddings = outputs.last_hidden_state
                input_mask_expanded = (
                    attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
                )
                embeddings = torch.sum(
                    token_embeddings * input_mask_expanded, 1
                ) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)
                embeddings = F.normalize(embeddings, p=2, dim=1)

            return embeddings.cpu().numpy().tolist()

    def init(self) -> None:
        """Initialize vector store and create collection.
        
        This is the main entry point for initialization.
        """
        if self.provider == "milvus":
            self._init_milvus()
            
            if self._client.has_collection(self.collection_name):
                logger.info(f"Collection '{self.collection_name}' already exists")
                return
            
            from pymilvus import DataType, CollectionSchema, FieldSchema
            
            schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
                    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="metadata", dtype=DataType.VARCHAR, max_length=65535),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
                ],
                description="Nanobot Knowledge Base Vector Collection",
            )
            
            self._client.create_collection(
                collection_name=self.collection_name,
                schema=schema,
                dimension=self.dimension,
                metric_type="COSINE",
                auto_id=False,
            )
            logger.info(f"Created Milvus collection '{self.collection_name}'")
        
        elif self.provider == "chroma":
            self._init_chroma()
            
            # Check if collection exists
            try:
                self._collection = self._chroma_client.get_collection(self.collection_name)
                logger.info(f"ChromaDB collection '{self.collection_name}' already exists")
            except Exception:
                # Create collection with embedding function
                self._collection = self._chroma_client.create_collection(
                    name=self.collection_name,
                    metadata={"description": "Nanobot Knowledge Base Vector Collection"},
                )
                logger.info(f"Created ChromaDB collection '{self.collection_name}'")

    def add_documents(
        self,
        documents: list[dict[str, Any]],
        batch_size: int = 32,
    ) -> list[str]:
        """Add documents to the vector store.
        
        Args:
            documents: List of dicts with 'text' and optional 'metadata'
            batch_size: Batch size for embedding generation
            
        Returns:
            List of document IDs
        """
        if not documents:
            return []

        ids = []
        texts = []
        metadatas = []

        for doc in documents:
            doc_id = str(uuid.uuid4())
            ids.append(doc_id)
            texts.append(doc["text"])
            
            # Clean metadata - remove empty lists and None values
            meta = doc.get("metadata", {}) or {}
            cleaned_meta = {
                k: v if v is not None and not (isinstance(v, list) and len(v) == 0) else ""
                for k, v in meta.items()
            }
            metadatas.append(cleaned_meta)

        # Generate embeddings
        logger.info(f"Generating embeddings for {len(texts)} documents...")
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_embeddings = self._embed_texts(batch_texts)
            all_embeddings.extend(batch_embeddings)
            logger.debug(f"Embedded batch {i // batch_size + 1}")

        # Insert into vector store
        if self.provider == "milvus":
            data = [
                {"id": id_, "text": text, "metadata": json.dumps(meta), "embedding": emb}
                for id_, text, meta, emb in zip(ids, texts, metadatas, all_embeddings)
            ]
            self._client.insert(collection_name=self.collection_name, data=data)
        
        elif self.provider == "chroma":
            self._collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas,
                embeddings=all_embeddings,
            )

        logger.info(f"Inserted {len(ids)} documents")
        return ids

    def search(
        self,
        query: str,
        top_k: int = 5,
        filter_expr: str | None = None,
        return_metadata: bool = True,
    ) -> list[dict[str, Any]]:
        """Search for relevant documents.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            filter_expr: Optional filter expression (not supported by ChromaDB)
            return_metadata: Whether to include metadata in results
            
        Returns:
            List of search results with 'id', 'text', 'distance', 'metadata'
        """
        # Generate query embedding
        query_embedding = self._embed_texts([query])[0]

        if self.provider == "milvus":
            search_params = {"metric_type": "COSINE", "params": {}}
            
            results = self._client.search(
                collection_name=self.collection_name,
                data=[query_embedding],
                limit=top_k,
                output_fields=["id", "text", "metadata"] if return_metadata else ["id", "text"],
                filter=filter_expr,
                search_params=search_params,
            )

            formatted = []
            for hit in results[0]:
                result = {
                    "id": hit["id"],
                    "text": hit["entity"]["text"],
                    "distance": hit["distance"],
                }
                if return_metadata and "metadata" in hit["entity"]:
                    result["metadata"] = json.loads(hit["entity"]["metadata"])
                formatted.append(result)
        
        elif self.provider == "chroma":
            # ChromaDB query
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                include=["documents", "metadatas", "distances"],
            )

            formatted = []
            if results["ids"] and len(results["ids"]) > 0:
                for i, doc_id in enumerate(results["ids"][0]):
                    result = {
                        "id": doc_id,
                        "text": results["documents"][0][i],
                        "distance": 1 - results["distances"][0][i],  # Convert to similarity
                    }
                    if return_metadata and "metadatas" in results:
                        result["metadata"] = results["metadatas"][0][i]
                    formatted.append(result)

        logger.debug(f"Search '{query}' returned {len(formatted)} results")
        return formatted

    def delete(self, doc_ids: list[str]) -> None:
        """Delete documents by ID."""
        if self.provider == "milvus":
            for doc_id in doc_ids:
                self._client.delete(collection_name=self.collection_name, pks=[doc_id])
        elif self.provider == "chroma":
            self._collection.delete(ids=doc_ids)
        
        logger.info(f"Deleted {len(doc_ids)} documents")

    def count(self) -> int:
        """Get total document count."""
        if self.provider == "milvus":
            return self._client.query(
                collection_name=self.collection_name,
                output_fields=["count(*)"],
            )[0]["count(*)"]
        elif self.provider == "chroma":
            return self._collection.count()

    def reset(self) -> None:
        """Drop collection and reset."""
        if self.provider == "milvus":
            self._init_milvus()
            if self._client.has_collection(self.collection_name):
                self._client.drop_collection(self.collection_name)
                logger.warning(f"Dropped Milvus collection '{self.collection_name}'")
        
        elif self.provider == "chroma":
            self._init_chroma()
            self._chroma_client.delete_collection(self.collection_name)
            logger.warning(f"Dropped ChromaDB collection '{self.collection_name}'")

    def get_context(
        self,
        query: str,
        top_k: int = 5,
        filter_expr: str | None = None,
    ) -> str:
        """Get formatted context string for LLM prompt.
        
        Args:
            query: User query
            top_k: Number of relevant chunks to retrieve
            filter_expr: Optional filter
            
        Returns:
            Formatted context string with citations
        """
        results = self.search(query, top_k=top_k, filter_expr=filter_expr)

        if not results:
            return ""

        context_parts = []
        for i, result in enumerate(results, 1):
            meta = result.get("metadata", {})
            category = meta.get("category", "general") if meta else "general"

            context_parts.append(
                f"[{i}] ({category}) {result['text']}"
            )

        header = f"=== Relevant Knowledge (Top {len(results)}) ===\n"
        return header + "\n".join(context_parts)

    def close(self) -> None:
        """Close connections."""
        self._client = None
        self._chroma_client = None
        self._embedding_model = None


# Alias for backward compatibility
MilvusRAGService = VectorStoreService
