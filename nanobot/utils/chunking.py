"""Text chunking utilities for RAG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class Chunk:
    """A text chunk with metadata."""
    text: str
    metadata: dict[str, Any]
    char_start: int = 0
    char_end: int = 0


def chunk_by_markdown(
    content: str,
    metadata: dict[str, Any] | None = None,
    min_chunk_size: int = 100,
    max_chunk_size: int = 1000,
) -> list[Chunk]:
    """Split markdown content into chunks by headers.
    
    Preserves header hierarchy and context.
    
    Args:
        content: Markdown content
        metadata: Additional metadata for chunks
        min_chunk_size: Minimum chunk size in characters
        max_chunk_size: Maximum chunk size in characters
        
    Returns:
        List of Chunk objects
    """
    if metadata is None:
        metadata = {}
    
    chunks = []
    
    # Split by headers (##, ###, etc.)
    parts = re.split(r'(?=^#{1,6}\s)', content, flags=re.MULTILINE)
    
    current_context = ""
    current_content = []
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Check if it's a header
        header_match = re.match(r'^(#{1,6})\s+(.+)$', part, re.MULTILINE)
        
        if header_match:
            # Save previous chunk if exists
            if current_content:
                chunk_text = f"{current_context}\n\n" + "\n\n".join(current_content)
                if len(chunk_text) >= min_chunk_size:
                    chunks.append(Chunk(
                        text=chunk_text.strip(),
                        metadata={**metadata, "section": current_context},
                    ))
                current_content = []
            
            current_context = part.split('\n')[0]  # Keep header as context
        else:
            # Content under current header
            current_content.append(part)
    
    # Don't forget the last chunk
    if current_content:
        chunk_text = f"{current_context}\n\n" + "\n\n".join(current_content)
        if len(chunk_text) >= min_chunk_size:
            chunks.append(Chunk(
                text=chunk_text.strip(),
                metadata={**metadata, "section": current_context},
            ))
    
    # Split oversized chunks
    final_chunks = []
    for chunk in chunks:
        if len(chunk.text) <= max_chunk_size:
            final_chunks.append(chunk)
        else:
            # Split by paragraphs
            paragraphs = chunk.text.split('\n\n')
            sub_chunk_text = ""
            
            for para in paragraphs:
                if len(sub_chunk_text) + len(para) + 2 <= max_chunk_size:
                    sub_chunk_text += para + "\n\n"
                else:
                    if sub_chunk_text:
                        final_chunks.append(Chunk(
                            text=sub_chunk_text.strip(),
                            metadata=chunk.metadata,
                        ))
                    sub_chunk_text = para + "\n\n"
            
            if sub_chunk_text.strip():
                final_chunks.append(Chunk(
                    text=sub_chunk_text.strip(),
                    metadata=chunk.metadata,
                ))
    
    return final_chunks


def chunk_by_sentences(
    content: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 5,
    overlap: int = 1,
) -> list[Chunk]:
    """Split content into sentence-based chunks with overlap.
    
    Args:
        content: Text content
        metadata: Additional metadata
        chunk_size: Number of sentences per chunk
        overlap: Number of sentences to overlap between chunks
        
    Returns:
        List of Chunk objects
    """
    if metadata is None:
        metadata = {}
    
    # Simple sentence splitting (can be improved with nltk/spacy)
    sentences = re.split(r'(?<=[。！？.!?])\s+', content.strip())
    
    chunks = []
    for i in range(0, len(sentences), chunk_size - overlap):
        chunk_sentences = sentences[i:i + chunk_size]
        if chunk_sentences:
            chunks.append(Chunk(
                text="".join(chunk_sentences),
                metadata=metadata,
            ))
    
    return chunks


def chunk_by_fixed_size(
    content: str,
    metadata: dict[str, Any] | None = None,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[Chunk]:
    """Split content into fixed-size chunks with overlap.
    
    Args:
        content: Text content
        metadata: Additional metadata
        chunk_size: Target chunk size in characters
        overlap: Character overlap between chunks
        
    Returns:
        List of Chunk objects
    """
    if metadata is None:
        metadata = {}
    
    chunks = []
    start = 0
    
    while start < len(content):
        end = start + chunk_size
        chunk_text = content[start:end]
        
        # Try to break at sentence boundary
        if end < len(content):
            last_punct = max(
                chunk_text.rfind('。'),
                chunk_text.rfind('.'),
                chunk_text.rfind('!'),
                chunk_text.rfind('?'),
                chunk_text.rfind('\n'),
            )
            if last_punct > chunk_size * 0.5:
                end = start + last_punct + 1
                chunk_text = content[start:end]
        
        chunks.append(Chunk(
            text=chunk_text.strip(),
            metadata=metadata,
            char_start=start,
            char_end=end,
        ))
        
        start = end - overlap if end < len(content) else end
    
    return chunks


def parse_faq_file(filepath: str, category: str = "faq") -> list[Chunk]:
    """Parse FAQ markdown file into chunks.
    
    Expected format:
    ## Q: Question Title
    
    **分类**: category
    **优先级**: P2
    **更新**: 2026-04-01
    
    ### 问题描述
    Description text...
    
    ### 解决方案
    Solution text...
    
    Args:
        filepath: Path to FAQ markdown file
        category: Default category
        
    Returns:
        List of Chunk objects
    """
    from pathlib import Path
    
    content = Path(filepath).read_text(encoding="utf-8")
    metadata = {
        "source_file": filepath,
        "category": category,
    }
    
    # Extract metadata from frontmatter
    meta_match = re.search(r'\*\*分类\*\*:\s*(\w+)', content)
    if meta_match:
        metadata["category"] = meta_match.group(1)
    
    priority_match = re.search(r'\*\*优先级\*\*:\s*(P\d)', content)
    if priority_match:
        metadata["priority"] = priority_match.group(1)
    
    return chunk_by_markdown(content, metadata, min_chunk_size=50)
