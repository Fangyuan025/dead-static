"""Static lore corpus retrieval.

Loads hand-authored location flavor + atmosphere fragments from
``rag.corpus.lore_data`` once at startup, then answers per-turn queries:

    lore.query(location, weather, time_of_day, query_text, k=2) -> list[Entry]

Design
------
* Two-stage retrieval:
    1. Hard filter — entries are candidates only if:
       - entry.location == current_location, or entry.location == "*"
       - entry.weather is None/[] or current_weather in entry.weather
       - entry.time    is None/[] or current_time    in entry.time
    2. BM25 rank on filtered set; fallback to token overlap if rank_bm25 is
       unavailable or the corpus is empty.

* Location-specific entries are preferred over atmosphere (location="*"): we
  retrieve top-K from the specific bucket first, then top up from atmosphere.

* Zero persistence: the corpus is static, so no on-disk index is needed.

Tokenization / BM25 are reused from ``rag.episodic``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .episodic import tokenize
from .corpus import LORE_ENTRIES, ATMOSPHERE_FRAGMENTS


# Tokens that carry no discriminative signal — filtered out of lore scoring
# so common particles don't drown out real matches in small buckets.
# Conservative list: common CJK function words + the highest-frequency English
# stopwords that appear in our corpus vocabulary.
_STOPWORDS = frozenset([
    # CJK particles and high-freq function words
    "的", "了", "是", "在", "有", "和", "就", "不", "这", "那", "也",
    "你", "我", "他", "她", "它", "们", "个", "吗", "吧", "啊", "呢",
    "等", "又", "着", "从", "于", "向", "被", "把", "到", "对", "让",
    "里", "中", "下", "上", "前", "后", "或", "而", "且", "但",
    # English function words that show up in the bilingual corpus
    "the", "a", "an", "of", "to", "in", "on", "is", "are", "was", "were",
    "it", "its", "and", "or", "but", "as", "at", "by", "with", "for",
    "this", "that", "these", "those",
])


def _filter_score_tokens(tokens):
    """Drop stopwords and 1-char CJK tokens before scoring."""
    out = []
    for t in tokens:
        if not t or t in _STOPWORDS:
            continue
        # Single-char CJK tokens are almost always particles/filler
        if len(t) == 1 and "\u4e00" <= t <= "\u9fff":
            continue
        out.append(t)
    return out


# ─────────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────────

@dataclass
class LoreEntry:
    id: str
    location: str                      # "*" means applies anywhere
    weather: Optional[list] = None     # None/[] means applies to any weather
    time: Optional[list] = None        # None/[] means applies to any time-of-day
    tags: list = field(default_factory=list)
    text_zh: str = ""
    text_en: str = ""

    def text_for(self, lang: str) -> str:
        return (self.text_zh if lang == "zh" else self.text_en).strip()

    def searchable_text(self, lang: str = "zh") -> str:
        # Weight location and tags by repeating them. Weather/time tags are
        # also included so queries mentioning e.g. "Night" can pull scoring
        # weight toward night-gated entries (tags are used for hard filtering
        # upstream, but appearing here also gives them a BM25 boost).
        loc = self.location if self.location != "*" else ""
        tag_str = " ".join(self.tags) if self.tags else ""
        weather_str = " ".join(self.weather) if self.weather else ""
        time_str = " ".join(self.time) if self.time else ""
        return " ".join([
            loc, loc,
            tag_str, tag_str,
            weather_str, time_str,
            self.text_zh,
            self.text_en,
        ])


def _mk_entry(d: dict) -> LoreEntry:
    return LoreEntry(
        id=str(d.get("id", "")),
        location=str(d.get("location", "*")),
        weather=list(d["weather"]) if d.get("weather") else None,
        time=list(d["time"]) if d.get("time") else None,
        tags=list(d.get("tags", [])),
        text_zh=str(d.get("text_zh", "")),
        text_en=str(d.get("text_en", "")),
    )


# ─────────────────────────────────────────────────────────────────────
# Store
# ─────────────────────────────────────────────────────────────────────

class LoreStore:
    """Read-only retrieval over the static lore corpus."""

    def __init__(self, entries=None, atmosphere=None):
        src_entries = entries if entries is not None else LORE_ENTRIES
        src_atmos   = atmosphere if atmosphere is not None else ATMOSPHERE_FRAGMENTS

        self.specific: list[LoreEntry] = [_mk_entry(d) for d in src_entries]
        self.generic:  list[LoreEntry] = [_mk_entry(d) for d in src_atmos]

        # Pre-tokenize once — the corpus is static.
        # Stopwords and 1-char CJK tokens are stripped so common particles
        # like "的/了/是" don't dominate scoring on small buckets.
        self._tok_specific = [_filter_score_tokens(tokenize(e.searchable_text()))
                              for e in self.specific]
        self._tok_generic  = [_filter_score_tokens(tokenize(e.searchable_text()))
                              for e in self.generic]

    # ── filtering ────────────────────────────────────────────────────

    @staticmethod
    def _tag_ok(tag_list: Optional[list], value: str) -> bool:
        """An entry passes the tag filter if its list is None/empty (wildcard)
        or the current value appears in the list."""
        if not tag_list:
            return True
        return value in tag_list

    def _candidates(self, pool, location: str, weather: str, time_of_day: str,
                    only_location: bool):
        """Yield (entry, tokenized) pairs that pass the hard filter."""
        toks_pool = self._tok_specific if pool is self.specific else self._tok_generic
        for entry, toks in zip(pool, toks_pool):
            if only_location:
                if entry.location != location:
                    continue
            else:
                if entry.location != "*":
                    continue
            if not self._tag_ok(entry.weather, weather):
                continue
            if not self._tag_ok(entry.time, time_of_day):
                continue
            yield entry, toks

    # ── Ranking on a candidate slice ────────────────────────────────
    #
    # Notes on scoring choice
    # -----------------------
    # The lore buckets are small (per-location specific buckets often have
    # 1–2 entries, atmosphere ~12). BM25Okapi on such tiny corpora is
    # unreliable — IDF degenerates when every doc shares the common
    # vocabulary (e.g. the location name), producing negative scores that
    # are noise, not signal.
    #
    # Instead we use a weighted token-count overlap: each query token scores
    # by the number of times it appears in the doc's searchable_text.
    # Because we repeat high-signal fields (location, tags, weather, time)
    # when building searchable_text, this gives an effective field-boost
    # equivalent to tf weighting — predictable and stable on small corpora.
    # If a query has zero overlap with any doc, we fall back to the order
    # the docs appeared (hard-filter survivors are still better than none).

    @staticmethod
    def _score_and_pick(candidates, query_tokens, k, min_score):
        """Return up to k candidates ranked by weighted token overlap."""
        if not candidates:
            return []
        entries, tokens_lists = zip(*candidates)

        if not query_tokens:
            return list(entries)[:k]

        qset = set(query_tokens)
        scored = []
        for e, toks in zip(entries, tokens_lists):
            # weighted by token-frequency in the doc (repeated fields count)
            score = sum(1 for t in toks if t in qset)
            scored.append((e, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        if min_score > 0:
            above = [e for e, s in scored if s >= min_score][:k]
            if above:
                return above
        # Default: return top-k — any hard-filter survivor is a valid result
        return [e for e, _ in scored[:k]]

    # ── public query ────────────────────────────────────────────────

    def query(self, location: str, weather: str, time_of_day: str,
              query_text: str = "", k: int = 2,
              min_score: float = 0.0,
              include_atmosphere: bool = True) -> list[LoreEntry]:
        """Return up to k lore entries relevant to the current scene.

        Strategy: take up to k-1 from the location-specific bucket, then fill
        remaining slots from the atmosphere bucket. If the location has no
        matching specific entries, the result is pure atmosphere.
        """
        if k <= 0:
            return []

        q = " ".join([p for p in (location, weather, time_of_day, query_text) if p])
        qtokens = _filter_score_tokens(tokenize(q))

        spec_cands = list(self._candidates(
            self.specific, location, weather, time_of_day, only_location=True))
        gen_cands = list(self._candidates(
            self.generic, location, weather, time_of_day, only_location=False
        )) if include_atmosphere else []

        # With atmosphere on, reserve at least 1 slot for location-specific (if
        # available) and fill the rest from the atmosphere bucket. With
        # atmosphere off, give all k slots to the specific bucket.
        if include_atmosphere:
            n_spec = min(len(spec_cands), max(1, k - 1)) if spec_cands else 0
            n_gen  = k - n_spec
        else:
            n_spec = min(len(spec_cands), k)
            n_gen  = 0

        out: list[LoreEntry] = []
        seen: set[str] = set()

        if n_spec > 0:
            for e in self._score_and_pick(spec_cands, qtokens, n_spec, min_score):
                if e.id not in seen:
                    out.append(e); seen.add(e.id)

        if n_gen > 0:
            for e in self._score_and_pick(gen_cands, qtokens, n_gen, min_score):
                if e.id not in seen:
                    out.append(e); seen.add(e.id)

        return out[:k]

    # ── formatting for prompt injection ─────────────────────────────

    def format_for_prompt(self, entries: list[LoreEntry], lang: str = "zh") -> str:
        if not entries:
            return ""
        lines = []
        for e in entries:
            txt = e.text_for(lang)
            if not txt:
                continue
            # keep it tight — one line per entry
            lines.append(f"- {txt}")
        return "\n".join(lines)

    # ── introspection helpers (for tests) ───────────────────────────

    def __len__(self) -> int:
        return len(self.specific) + len(self.generic)

    def locations(self) -> set:
        return {e.location for e in self.specific}


# ─────────────────────────────────────────────────────────────────────
# Self-test when run directly
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    store = LoreStore()
    print(f"Loaded {len(store.specific)} location entries + "
          f"{len(store.generic)} atmosphere fragments")
    print(f"Locations covered: {sorted(store.locations())}")
    print()

    hits = store.query("Hospital", "Heavy rain", "Night",
                       query_text="corridor dark beds", k=2)
    print("Query: Hospital / Heavy rain / Night")
    print(store.format_for_prompt(hits, lang="en"))
    print()

    hits = store.query("Rooftop", "Clear skies", "Night",
                       query_text="stars wind", k=2)
    print("Query: Rooftop / Clear skies / Night")
    print(store.format_for_prompt(hits, lang="zh"))
