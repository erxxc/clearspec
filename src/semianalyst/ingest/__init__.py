"""ingest — fetch raw releases and store them content-addressed by sha256."""

from .base import Fetcher, RawRef, SourceRef, store_raw
from .foundry import FoundryFetcher

__all__ = ["Fetcher", "RawRef", "SourceRef", "store_raw", "FoundryFetcher"]
