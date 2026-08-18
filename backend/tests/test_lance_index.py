from app.schemas import Chunk
from app.services.index import LanceChunkIndex


def test_lance_index_supports_active_lexical_and_dense_search(tmp_path):
    index = LanceChunkIndex(tmp_path / "lance", dimensions=4)
    chunk = Chunk(
        id="chunk-1",
        document_id="doc-1",
        document_version_id="version-1",
        raw_text="enterprise revenue grew",
        retrieval_text="Document: Annual Report\nenterprise revenue grew",
        title="Annual Report",
        token_count=3,
        vector=[1.0, 0.0, 0.0, 0.0],
    )
    index.add([chunk])
    assert index.lexical_search("enterprise", 10) == []
    index.activate_version("doc-1", "version-1")
    assert index.lexical_search("enterprise", 10)[0].id == "chunk-1"
    assert index.dense_search([1.0, 0.0, 0.0, 0.0], 10)[0].id == "chunk-1"
    assert index.get("chunk-1").raw_text == "enterprise revenue grew"
    index.delete_document("doc-1")
    assert index.get("chunk-1") is None
