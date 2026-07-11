# backend/rag/chunker.py

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import re
import tiktoken

from config import get_settings


@dataclass
class DocumentChunk:
    """
    A single chunk of text with metadata attached.

    INTERVIEW: "Why store metadata with chunks?"
    ANSWER: "So the system can cite sources. When content is generated,
    we know exactly which document and position each fact came from.
    This enables source attribution and hallucination detection."
    """
    text: str                          # The actual chunk text
    chunk_id: str                      # Unique ID: "doc_name_chunk_0"
    source: str                        # Where it came from (filename/URL)
    chunk_index: int                   # Position in original document
    total_chunks: int                  # Total chunks in that document
    token_count: int                   # How many tokens this chunk uses
    metadata: Dict[str, Any] = field(default_factory=dict)  # Extra info


class RecursiveChunker:
    """
    Splits documents into overlapping chunks using recursive splitting.

    HOW RECURSIVE SPLITTING WORKS:
    1. Try to split on paragraph breaks (double newline) first
    2. If chunks still too big, split on single newline
    3. If still too big, split on sentences (. ! ?)
    4. If still too big, split on words
    5. Last resort: split on characters

    This preserves natural text boundaries as much as possible.
    Splitting mid-sentence is always the last option.
    """

    # Split priority: try these separators in order
    SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", " ", ""]

    def __init__(self):
        self.settings = get_settings()
        self.chunk_size = self.settings.chunk_size        # 512 tokens
        self.chunk_overlap = self.settings.chunk_overlap  # 50 tokens

        # tiktoken counts tokens the same way GPT models do
        # This ensures our "512 token" chunks are actually 512 tokens
        try:
            self.encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.encoder = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text. Falls back to word count if tiktoken fails."""
        if self.encoder:
            return len(self.encoder.encode(text))
        # Rough approximation: 1 token ≈ 0.75 words
        return int(len(text.split()) * 1.33)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """
        Recursively split text using the separator hierarchy.
        Returns a list of text pieces that fit within chunk_size.
        """
        final_chunks = []
        separator = separators[-1]  # default: empty string (char split)

        # Find the best separator that actually splits this text
        for sep in separators:
            if sep in text:
                separator = sep
                break

        # Split on the chosen separator
        splits = text.split(separator)
        current_chunk = ""

        for split in splits:
            # Would adding this split exceed chunk_size?
            candidate = current_chunk + (separator if current_chunk else "") + split
            if self.count_tokens(candidate) <= self.chunk_size:
                current_chunk = candidate
            else:
                # Save current chunk if it has content
                if current_chunk.strip():
                    final_chunks.append(current_chunk.strip())

                # Is the split itself too big? Recurse with next separator
                if self.count_tokens(split) > self.chunk_size:
                    next_separators = separators[separators.index(separator) + 1:] \
                        if separator in separators and separators.index(separator) + 1 < len(separators) \
                        else [""]
                    sub_chunks = self._split_text(split, next_separators)
                    final_chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = split

        # Don't forget the last chunk
        if current_chunk.strip():
            final_chunks.append(current_chunk.strip())

        return final_chunks

    def _add_overlap(self, chunks: List[str]) -> List[str]:
        """
        Add overlap between consecutive chunks.

        WHY OVERLAP MATTERS:
        If a sentence is: "Quantum computing will revolutionize [CHUNK BREAK] drug discovery by 2030"
        Without overlap, the first chunk ends mid-thought and the second
        chunk starts without context. With overlap, both chunks contain
        enough surrounding text to be meaningful on their own.
        """
        if len(chunks) <= 1:
            return chunks

        overlapped = [chunks[0]]

        for i in range(1, len(chunks)):
            prev_chunk = chunks[i - 1]
            current_chunk = chunks[i]

            # Take the last `chunk_overlap` tokens from previous chunk
            prev_tokens = prev_chunk.split()
            overlap_word_count = max(1, self.chunk_overlap // 2)  # rough words
            overlap_text = " ".join(prev_tokens[-overlap_word_count:])

            # Prepend overlap to current chunk
            new_chunk = overlap_text + " " + current_chunk
            overlapped.append(new_chunk.strip())

        return overlapped

    def chunk_document(
        self,
        text: str,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """
        Main method: takes a full document, returns a list of DocumentChunks.

        Args:
            text: Full document text
            source: Where the document came from (filename, URL, etc.)
            metadata: Any extra info to attach to all chunks

        Returns:
            List of DocumentChunk objects ready for embedding
        """
        if not text or not text.strip():
            return []

        metadata = metadata or {}

        # Clean the text
        text = self._clean_text(text)

        # Split into chunks
        raw_chunks = self._split_text(text, self.SEPARATORS)

        # Add overlap
        overlapped_chunks = self._add_overlap(raw_chunks)

        # Convert to DocumentChunk objects with metadata
        doc_chunks = []
        for i, chunk_text in enumerate(overlapped_chunks):
            if not chunk_text.strip():
                continue

            chunk_id = f"{self._make_id(source)}_chunk_{i}"
            token_count = self.count_tokens(chunk_text)

            doc_chunks.append(DocumentChunk(
                text=chunk_text,
                chunk_id=chunk_id,
                source=source,
                chunk_index=i,
                total_chunks=len(overlapped_chunks),
                token_count=token_count,
                metadata={
                    **metadata,
                    "chunk_position": f"{i+1}/{len(overlapped_chunks)}",
                    "is_first_chunk": i == 0,
                    "is_last_chunk": i == len(overlapped_chunks) - 1,
                }
            ))

        return doc_chunks

    def chunk_multiple_documents(
        self,
        documents: List[Dict[str, Any]],
    ) -> List[DocumentChunk]:
        """
        Chunk multiple documents at once.

        Args:
            documents: List of {"text": "...", "source": "...", "metadata": {...}}

        Returns:
            Flat list of all chunks from all documents
        """
        all_chunks = []
        for doc in documents:
            chunks = self.chunk_document(
                text=doc.get("text", ""),
                source=doc.get("source", "unknown"),
                metadata=doc.get("metadata", {}),
            )
            all_chunks.extend(chunks)

        print(f"📄 Chunked {len(documents)} documents → {len(all_chunks)} chunks")
        return all_chunks

    def _clean_text(self, text: str) -> str:
        """Remove excessive whitespace and normalize text."""
        # Collapse multiple spaces
        text = re.sub(r" {2,}", " ", text)
        # Collapse more than 2 consecutive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _make_id(self, source: str) -> str:
        """Convert a source path/URL into a clean ID string."""
        # Remove special characters, keep alphanumeric and underscores
        clean = re.sub(r"[^a-zA-Z0-9_]", "_", source)
        # Remove consecutive underscores
        clean = re.sub(r"_{2,}", "_", clean)
        return clean[:50]  # Max 50 chars