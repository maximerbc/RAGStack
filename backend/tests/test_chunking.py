from app.services.chunking import Block, StructureAwareChunker


def test_structure_aware_chunking_preserves_metadata_and_links():
    chunker = StructureAwareChunker(target_tokens=25, max_tokens=40, overlap_tokens=5)
    chunks = chunker.chunk(
        "doc-1",
        "version-1",
        "Annual Report",
        [
            Block("Revenue increased because enterprise demand grew.", ["Financials"], 4),
            Block("Operating costs remained stable.", ["Financials"], 4),
            Block("A | B\n1 | 2", ["Tables"], 5, "table"),
        ],
    )
    assert chunks
    assert chunks[0].retrieval_text.startswith(
        "Document: Annual Report\nSection: Financials\nPage: 4"
    )
    assert chunks[0].next_id == chunks[1].id
    assert chunks[1].previous_id == chunks[0].id
    assert all(chunk.token_count <= 40 for chunk in chunks)


def test_long_block_is_split_without_crossing_limit():
    chunker = StructureAwareChunker(target_tokens=12, max_tokens=18, overlap_tokens=3)
    text = "First sentence has several words. Second sentence also has several words. Third sentence finishes the block."
    chunks = chunker.chunk("d", "v", "Title", [Block(text, ["Section"], 1)])
    assert len(chunks) >= 2
    assert max(chunk.token_count for chunk in chunks) <= 18
