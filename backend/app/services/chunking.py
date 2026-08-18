from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

import tiktoken
from app.schemas import Chunk


@dataclass
class Block:
    text: str
    headings: list[str] = field(default_factory=list)
    page: int | None = None
    content_type: str = "text"


class StructureAwareChunker:
    def __init__(self, target_tokens: int = 450, max_tokens: int = 600, overlap_tokens: int = 60):
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def _split_long(self, block: Block) -> list[Block]:
        if self.count(block.text) <= self.max_tokens:
            return [block]
        sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", block.text)
        output: list[Block] = []
        current: list[str] = []
        for sentence in sentences:
            candidate = " ".join([*current, sentence]).strip()
            if current and self.count(candidate) > self.max_tokens:
                output.append(
                    Block(" ".join(current), block.headings, block.page, block.content_type)
                )
                overlap: list[str] = []
                for prior in reversed(current):
                    if self.count(" ".join([prior, *overlap])) > self.overlap_tokens:
                        break
                    overlap.insert(0, prior)
                current = [*overlap, sentence]
            else:
                current.append(sentence)
        if current:
            output.append(Block(" ".join(current), block.headings, block.page, block.content_type))
        return output

    def chunk(
        self, document_id: str, version_id: str, title: str, blocks: list[Block]
    ) -> list[Chunk]:
        expanded = [
            part for block in blocks for part in self._split_long(block) if part.text.strip()
        ]
        groups: list[Block] = []
        for block in expanded:
            if (
                groups
                and groups[-1].headings == block.headings
                and groups[-1].page == block.page
                and groups[-1].content_type == block.content_type
                and self.count(groups[-1].text + "\n\n" + block.text) <= self.target_tokens
            ):
                groups[-1].text += "\n\n" + block.text
            else:
                groups.append(block)

        chunks: list[Chunk] = []
        for block in groups:
            chunk_id = str(uuid.uuid4())
            context = [f"Document: {title}"]
            if block.headings:
                context.append("Section: " + " > ".join(block.headings))
            if block.page:
                context.append(f"Page: {block.page}")
            retrieval_text = "\n".join(context) + "\n\n" + block.text.strip()
            chunks.append(
                Chunk(
                    id=chunk_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    raw_text=block.text.strip(),
                    retrieval_text=retrieval_text,
                    title=title,
                    heading_path=block.headings,
                    page=block.page,
                    parent_id="/".join(block.headings) or None,
                    content_type=block.content_type,
                    token_count=self.count(block.text),
                )
            )
        for index, chunk in enumerate(chunks):
            chunk.previous_id = chunks[index - 1].id if index > 0 else None
            chunk.next_id = chunks[index + 1].id if index + 1 < len(chunks) else None
        return chunks
