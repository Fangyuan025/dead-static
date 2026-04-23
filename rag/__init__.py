"""DEAD STATIC — RAG (Retrieval-Augmented Generation) module.

Phase 1: Episodic memory. Each turn's summary is stored, then relevant past
turns are retrieved and injected into the LLM prompt so long games stay
coherent (the model can "remember" what happened 10 turns ago).
"""

from .episodic import EpisodicMemory
from .summarizer import summarize_turn

__all__ = ["EpisodicMemory", "summarize_turn"]
