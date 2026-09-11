"""The Voyage path, with the network replaced — no key is needed to prove the batching."""
import pytest

from app.config import settings
from app.retrieval import embedding


class FakeVoyage:
    calls: list[dict] = []

    def __init__(self, api_key):
        assert api_key == "pa-test"

    def embed(self, texts, model, input_type):
        FakeVoyage.calls.append({"n": len(texts), "model": model, "input_type": input_type})

        class Result:
            # Each vector records which text it came from, so ordering can be checked.
            embeddings = [[float(t.split("-")[1])] for t in texts]
        return Result()


@pytest.fixture()
def voyage(monkeypatch):
    import voyageai
    FakeVoyage.calls = []
    monkeypatch.setattr(voyageai, "Client", FakeVoyage)
    monkeypatch.setattr(settings, "embedding_backend", "voyage")
    monkeypatch.setattr(settings, "voyage_api_key", "pa-test")
    monkeypatch.setattr(settings, "embedding_model", "voyage-4-large")
    return FakeVoyage


def test_a_long_document_goes_out_in_batches_and_comes_back_in_order(voyage):
    texts = [f"chunk-{i}" for i in range(300)]
    vectors = embedding.embed_many(texts)

    assert [c["n"] for c in voyage.calls] == [128, 128, 44]
    assert all(c["n"] <= 1000 for c in voyage.calls)          # Voyage's hard limit
    assert vectors == [[float(i)] for i in range(300)]
    assert {c["model"] for c in voyage.calls} == {"voyage-4-large"}


def test_questions_and_passages_are_embedded_as_different_sides(voyage):
    embedding.embed_many(["chunk-1"])
    embedding.embed_one("chunk-2", is_query=True)
    assert [c["input_type"] for c in voyage.calls] == ["document", "query"]


def test_a_missing_key_says_so_rather_than_failing_somewhere_deeper(voyage, monkeypatch):
    monkeypatch.setattr(settings, "voyage_api_key", None)
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY is not set"):
        embedding.embed_many(["chunk-1"])
