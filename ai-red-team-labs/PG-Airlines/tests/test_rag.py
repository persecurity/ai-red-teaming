from unittest.mock import patch

from flask import Flask

from app.rag import _chunk, _lexical_retrieve, retrieve


def test_chunking_preserves_overlap_and_does_not_emit_empty_chunks():
    assert _chunk("   \n\n\n ") == []
    chunks = _chunk("abcdefghij", size=6, overlap=2)
    assert chunks == ["abcdef", "efghij", "ij"]
    assert chunks[0][-2:] == chunks[1][:2]


def test_lexical_retrieval_ranks_filename_and_content_matches(tmp_path):
    corpus = tmp_path / "corpus"
    (corpus / "public").mkdir(parents=True)
    (corpus / "sensitive").mkdir()
    (corpus / "public" / "baggage.md").write_text(
        "Baggage allowance is one cabin bag.", encoding="utf-8"
    )
    (corpus / "public" / "refunds.md").write_text(
        "Refund requests take seven days.", encoding="utf-8"
    )
    (corpus / "sensitive" / "pilots.md").write_text(
        "Synthetic pilot roster.", encoding="utf-8"
    )
    app = Flask(__name__)
    app.config["CORPUS_PATH"] = corpus

    with app.app_context():
        results = _lexical_retrieve("baggage allowance", top_k=2)

    assert results[0]["source"] == "baggage.md"
    assert all(result["group"] in {"public", "sensitive"} for result in results)


def test_retrieve_uses_lexical_fallback_when_vector_index_fails():
    expected = [{"source": "baggage.md", "group": "public", "text": "allowance"}]
    with patch("app.rag.ensure_index", side_effect=RuntimeError("offline")), patch(
        "app.rag._lexical_retrieve", return_value=expected
    ) as lexical:
        assert retrieve("baggage", top_k=3) == expected
    lexical.assert_called_once_with("baggage", 3)
