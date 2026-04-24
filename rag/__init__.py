"""DEAD STATIC — RAG (Retrieval-Augmented Generation) module.

Phase 1: Episodic memory. Each turn's summary is stored, then relevant past
turns are retrieved and injected into the LLM prompt so long games stay
coherent (the model can "remember" what happened 10 turns ago).

Phase 2: Static lore corpus. Hand-authored per-location flavor and atmosphere
fragments are retrieved by (location, weather, time) and injected as scene
reference so the narrative stays tonally and visually consistent.
"""

from .episodic import EpisodicMemory
from .summarizer import summarize_turn
from .lore import LoreStore

__all__ = ["EpisodicMemory", "summarize_turn", "LoreStore"]
