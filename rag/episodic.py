"""Episodic memory: store and retrieve per-turn summaries via BM25.

Design goals
------------
* Zero heavy deps — jieba (tokenizer) + rank_bm25 (pure python).
* Persistence via one JSONL file per session. Index rebuilds from disk on load.
* Robust to small corpora (a game rarely exceeds ~80 turns).
* Idempotent: appending one row is O(n) to rebuild the BM25 index, but n <= 80
  so it is cheap; no need for an incremental BM25 implementation.

Public API
----------
* EpisodicMemory(session_id, base_dir)  — construct / load
* .record(entry)                         — append a turn entry
* .query(query_text, k=3, max_age=None)  — return list[dict] of top-k relevant
* .reset()                               — clear current session
* .recent(n)                             — last-n entries without scoring
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import jieba
    jieba.setLogLevel(60)  # suppress startup logging
    _HAS_JIEBA = True
except Exception:
    _HAS_JIEBA = False

try:
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except Exception:
    _HAS_BM25 = False


# ─────────────────────────────────────────────────────────────────────
# Tokenization — mixed CJK + ASCII
# ─────────────────────────────────────────────────────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Tokenize a mixed-language string.

    * Chinese segments → jieba (falls back to character unigrams if jieba missing).
    * ASCII segments   → lowercase word split.
    """
    if not text:
        return []
    text = text.strip()
    tokens: list[str] = []

    if _HAS_JIEBA and _CJK_RE.search(text):
        for tok in jieba.lcut(text):
            tok = tok.strip().lower()
            if not tok:
                continue
            # keep content tokens only
            if _CJK_RE.search(tok) or _WORD_RE.fullmatch(tok):
                tokens.append(tok)
    else:
        # fallback — characters for CJK + lowercase words for ascii
        for ch in text:
            if _CJK_RE.match(ch):
                tokens.append(ch)
        tokens.extend(m.group(0).lower() for m in _WORD_RE.finditer(text))

    return tokens


# ─────────────────────────────────────────────────────────────────────
# Entry schema
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Entry:
    turn: int
    day: int
    time_of_day: str
    location: str
    weather: str
    action: str               # the player action that was chosen
    outcome: str              # mechanical outcome tags, if any (found X, combat hit…)
    summary: str              # short prose (1 sentence) summarizing this turn
    raw_narrative_head: str   # first ~80 chars of the LLM's narrative, for cross-ref

    def searchable_text(self) -> str:
        """What BM25 sees. Location/action repeated so they are weighted higher."""
        return " ".join([
            self.location, self.location,
            self.weather,
            self.time_of_day,
            self.action, self.action,
            self.outcome,
            self.summary,
        ])


# ─────────────────────────────────────────────────────────────────────
# The memory store
# ─────────────────────────────────────────────────────────────────────

class EpisodicMemory:
    def __init__(self, session_id: str, base_dir: str):
        self.session_id = session_id
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        self.path = os.path.join(base_dir, f"episodic_{session_id}.jsonl")

        self.entries: list[Entry] = []
        self._tokenized: list[list[str]] = []
        self._bm25: Optional["BM25Okapi"] = None

        self._load()

    # ── persistence ──────────────────────────────────────────────────

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    self.entries.append(Entry(**data))
            self._rebuild_index()
        except Exception:
            # Corrupt file — start fresh rather than crash the game
            self.entries = []
            self._tokenized = []
            self._bm25 = None

    def _append_disk(self, entry: Entry) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except Exception:
            pass  # non-fatal

    # ── index ────────────────────────────────────────────────────────

    def _rebuild_index(self) -> None:
        if not self.entries or not _HAS_BM25:
            self._bm25 = None
            self._tokenized = [tokenize(e.searchable_text()) for e in self.entries]
            return
        self._tokenized = [tokenize(e.searchable_text()) for e in self.entries]
        # BM25Okapi chokes on an all-empty corpus
        if not any(self._tokenized):
            self._bm25 = None
            return
        self._bm25 = BM25Okapi(self._tokenized)

    # ── public API ───────────────────────────────────────────────────

    def record(self, **kwargs) -> None:
        """Record a new turn entry. Missing fields default to empty strings / 0."""
        entry = Entry(
            turn=int(kwargs.get("turn", len(self.entries))),
            day=int(kwargs.get("day", 0)),
            time_of_day=str(kwargs.get("time_of_day", "")),
            location=str(kwargs.get("location", "")),
            weather=str(kwargs.get("weather", "")),
            action=str(kwargs.get("action", "")),
            outcome=str(kwargs.get("outcome", "")),
            summary=str(kwargs.get("summary", "")),
            raw_narrative_head=str(kwargs.get("raw_narrative_head", ""))[:160],
        )
        self.entries.append(entry)
        self._append_disk(entry)
        self._rebuild_index()

    def reset(self) -> None:
        self.entries = []
        self._tokenized = []
        self._bm25 = None
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass

    def recent(self, n: int = 3) -> list[Entry]:
        if n <= 0:
            return []
        return self.entries[-n:]

    def query(
        self,
        query_text: str,
        k: int = 3,
        exclude_last: int = 1,
        min_score: float = 0.5,
    ) -> list[Entry]:
        """Return up to k entries most relevant to query_text.

        ``exclude_last`` skips the N most recent turns (already in immediate
        context via last_narrative / last_action_context) so retrieval surfaces
        *older* memories the prompt would otherwise lose.
        """
        if not self.entries:
            return []

        candidates = self.entries[:-exclude_last] if exclude_last > 0 else list(self.entries)
        if not candidates:
            return []

        # BM25 path
        if self._bm25 is not None and _HAS_BM25:
            tokens = tokenize(query_text)
            if tokens:
                # rebuild index on candidate slice only — cheap for small n
                tok_candidates = self._tokenized[:-exclude_last] if exclude_last > 0 else self._tokenized
                if any(tok_candidates):
                    bm25 = BM25Okapi(tok_candidates)
                    scores = bm25.get_scores(tokens)
                    ranked = sorted(
                        zip(candidates, scores),
                        key=lambda x: x[1],
                        reverse=True,
                    )
                    hits = [e for e, s in ranked if s >= min_score][:k]
                    if hits:
                        # Re-sort chronologically so the model sees them in order
                        hits.sort(key=lambda e: e.turn)
                        return hits

        # Fallback: simple token overlap (used if rank_bm25 missing or no scores)
        tokens = set(tokenize(query_text))
        if not tokens:
            return candidates[-k:]
        scored = []
        for e, toks in zip(candidates, self._tokenized[:len(candidates)]):
            overlap = len(tokens.intersection(toks))
            if overlap > 0:
                scored.append((e, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        hits = [e for e, _ in scored[:k]]
        hits.sort(key=lambda e: e.turn)
        return hits

    # ── formatting helpers for prompt injection ──────────────────────

    def format_for_prompt(self, entries: list[Entry], lang: str = "en") -> str:
        if not entries:
            return ""
        lines = []
        for e in entries:
            when = f"D{e.day}-{e.time_of_day}" if e.time_of_day else f"D{e.day}"
            core = e.summary or e.raw_narrative_head or e.action
            core = core.strip().replace("\n", " ")
            if len(core) > 110:
                core = core[:110] + "…"
            loc = e.location or "?"
            lines.append(f"- [{when} @ {loc}] {core}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────
# Self-test when run directly
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    tmp = tempfile.mkdtemp()
    mem = EpisodicMemory("selftest", tmp)
    mem.reset()

    mem.record(turn=0, day=1, time_of_day="Dawn", location="Abandoned Apartment",
               weather="Overcast", action="搜索衣柜", outcome="found canned beans",
               summary="在衣柜里翻到一罐豆子", raw_narrative_head="你在衣柜深处摸到一个冰凉的金属罐。")
    mem.record(turn=1, day=1, time_of_day="Daytime", location="Street",
               weather="Overcast", action="sneak past zombies",
               outcome="stealth success",
               summary="悄悄溜过街上的丧尸群", raw_narrative_head="你屏住呼吸从一辆翻倒的车旁经过。")
    mem.record(turn=2, day=2, time_of_day="Night", location="Hospital",
               weather="Rain", action="check pharmacy",
               outcome="found antibiotics",
               summary="在医院药房找到抗生素", raw_narrative_head="货架大多被翻空，但角落还有半瓶药。")

    # Simulate a 4th turn where player returns to the hospital.
    # query() is called BEFORE recording, so exclude_last=1 drops turn 2 (hospital),
    # and retrieval should surface the earlier apartment/street turns.
    hits = mem.query("医院 夜晚 下雨", k=2, exclude_last=0)
    print("Query 1 (医院 夜晚 下雨) — with exclude_last=0 so hospital included:")
    print(mem.format_for_prompt(hits, lang="zh"))
    print()

    hits = mem.query("apartment closet search", k=2, exclude_last=0)
    print("Query 2 (apartment closet search):")
    print(mem.format_for_prompt(hits, lang="en"))
    print()

    hits = mem.query("Hospital Night", k=3, exclude_last=0)
    print("Query 3 (Hospital Night, k=3):")
    print(mem.format_for_prompt(hits, lang="en"))
