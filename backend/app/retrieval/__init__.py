"""The retrieval layer: embedding, chunking, and hybrid search over document text."""
from app.retrieval.embedding import embed_one, embed_many, active_model
from app.retrieval.search import Hit, search

__all__ = ["Hit", "active_model", "embed_many", "embed_one", "search"]
