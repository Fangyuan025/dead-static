"""Static lore corpus for DEAD STATIC.

Hand-authored location flavor and atmosphere fragments that the LLM can
borrow from — imagery, vocabulary, small concrete details — to keep the
world feeling consistent across a 15-day playthrough.

Data lives in a Python module (not JSON/YAML) so that:
  - no extra dependency
  - multi-line strings stay readable
  - entries can be commented

The `LoreStore` in ``rag/lore.py`` loads these constants once at startup.
"""

from .lore_data import LORE_ENTRIES, ATMOSPHERE_FRAGMENTS

__all__ = ["LORE_ENTRIES", "ATMOSPHERE_FRAGMENTS"]
