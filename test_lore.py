"""Headless tests for the Phase 2 Static Lore Corpus.

Verifies WITHOUT starting llama-server:
  * LoreStore loads all entries from rag.corpus.lore_data
  * Location filter is exact (no cross-location bleed)
  * Weather / time-of-day filters work on tagged entries and wildcards
  * BM25 ranking surfaces the most query-relevant entry first
  * Atmosphere fragments are pulled as top-up
  * build_prompt() includes a "scene reference" section when snippets are provided
"""

import os
import sys

# Force UTF-8 stdout so Chinese prints don't crash on cp1252
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rag import LoreStore
from rag.corpus import LORE_ENTRIES, ATMOSPHERE_FRAGMENTS
import game as g


PASS = 0
FAIL = 0


def banner(name):
    print(f"\n══════ {name} ══════")


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {detail}")


# ─────────────────────────────────────────────────────────────
# 1. Corpus sanity — schema + coverage
# ─────────────────────────────────────────────────────────────

def test_corpus_shape():
    banner("Corpus: schema + coverage")

    # Each entry has the required fields
    required = {"id", "location", "text_zh", "text_en"}
    missing = [e for e in LORE_ENTRIES + ATMOSPHERE_FRAGMENTS
               if not required.issubset(e.keys())]
    check("every entry has required fields", not missing,
          f"{len(missing)} missing: {[m.get('id') for m in missing]}")

    # ids are unique
    all_ids = [e["id"] for e in LORE_ENTRIES + ATMOSPHERE_FRAGMENTS]
    check("ids are unique", len(all_ids) == len(set(all_ids)),
          f"dups: {[i for i in all_ids if all_ids.count(i) > 1]}")

    # Both languages present and non-empty
    empty_zh = [e for e in LORE_ENTRIES if not e.get("text_zh", "").strip()]
    empty_en = [e for e in LORE_ENTRIES if not e.get("text_en", "").strip()]
    check("all location entries have text_zh", not empty_zh)
    check("all location entries have text_en", not empty_en)

    # Atmosphere entries all use wildcard location
    atm_bad_loc = [e for e in ATMOSPHERE_FRAGMENTS if e["location"] != "*"]
    check("atmosphere entries use location='*'", not atm_bad_loc,
          f"bad: {[e['id'] for e in atm_bad_loc]}")

    # Coverage: every location in game.LOCATIONS has >=1 lore entry
    covered = {e["location"] for e in LORE_ENTRIES}
    missing_locs = set(g.LOCATIONS.keys()) - covered
    check("every in-game location has a lore entry",
          not missing_locs, f"missing: {sorted(missing_locs)}")


# ─────────────────────────────────────────────────────────────
# 2. LoreStore: filtering
# ─────────────────────────────────────────────────────────────

def test_location_filter():
    banner("LoreStore: location filter is exact")
    store = LoreStore()

    # Query Hospital — specific entries must be Hospital-tagged, not "Hospital Basement"
    hits = store.query("Hospital", "Clear skies", "Daytime",
                       query_text="", k=2, include_atmosphere=False)
    specific_locs = {e.location for e in hits}
    check("Hospital query returns only Hospital-tagged specific entries",
          specific_locs == {"Hospital"} or specific_locs == set(),
          f"got {specific_locs}")

    # Atmosphere disabled → no "*" entries in results
    check("with include_atmosphere=False, no '*' entries leak",
          all(e.location != "*" for e in hits))

    # Query with atmosphere on → at least one atmosphere entry when k>num_specific
    hits = store.query("Rooftop", "Clear skies", "Night",
                       query_text="stars", k=3, include_atmosphere=True)
    has_atmosphere = any(e.location == "*" for e in hits)
    check("with atmosphere enabled, '*' entries fill remaining slots",
          has_atmosphere, f"got {[e.id for e in hits]}")


def test_weather_time_filter():
    banner("LoreStore: weather + time filters")
    store = LoreStore()

    # The apt-02 entry is gated to Heavy rain/Thunderstorm + Night. It must NOT
    # appear for Clear skies / Daytime, but SHOULD appear for Heavy rain / Night.
    hits_wrong = store.query("Abandoned Apartment", "Clear skies", "Daytime",
                             query_text="rain leak", k=3,
                             include_atmosphere=False)
    check("apt-02 excluded when weather/time don't match",
          all(e.id != "apt-02" for e in hits_wrong),
          f"got {[e.id for e in hits_wrong]}")

    hits_right = store.query("Abandoned Apartment", "Heavy rain", "Night",
                             query_text="rain leak storm", k=2,
                             include_atmosphere=False)
    check("apt-02 included when weather + time both match",
          any(e.id == "apt-02" for e in hits_right),
          f"got {[e.id for e in hits_right]}")


def test_wildcard_atmosphere():
    banner("LoreStore: atmosphere wildcard filtering")
    store = LoreStore()

    # In heavy rain, the rain-tagged atmosphere fragment should be retrievable.
    hits = store.query("Main Street", "Heavy rain", "Daytime",
                       query_text="rain footsteps", k=3,
                       include_atmosphere=True)
    atm_hits = [e for e in hits if e.location == "*"]
    check("rain-tagged atmosphere reachable in Heavy rain", bool(atm_hits),
          f"got {[e.id for e in hits]}")

    # In clear skies/daytime, the rain atmosphere should NOT appear.
    hits = store.query("Main Street", "Clear skies", "Daytime",
                       query_text="rain footsteps", k=5,
                       include_atmosphere=True)
    rain_atm = [e for e in hits if e.id == "atm-rain-01"]
    check("rain atmosphere not offered in Clear skies", not rain_atm,
          f"got {[e.id for e in hits]}")


# ─────────────────────────────────────────────────────────────
# 3. BM25 ranking
# ─────────────────────────────────────────────────────────────

def test_bm25_ranking():
    banner("LoreStore: BM25 ranking by query text")
    store = LoreStore()

    # The Hospital has 2 specific entries; hosp-02 is night-tagged and contains
    # "cardiac monitor / wheelchair". With query matching those words + Night
    # time, hosp-02 should outrank the generic hosp-01.
    hits = store.query("Hospital", "Overcast", "Night",
                       query_text="monitor beeping wheelchair corridor",
                       k=1, include_atmosphere=False)
    check("monitor+wheelchair query prefers hosp-02",
          hits and hits[0].id == "hosp-02",
          f"got {[e.id for e in hits]}")

    # Query targeting hosp-01's content (antiseptic / beds)
    hits = store.query("Hospital", "Overcast", "Daytime",
                       query_text="antiseptic beds sheets corridor",
                       k=1, include_atmosphere=False)
    check("antiseptic+beds query prefers hosp-01",
          hits and hits[0].id == "hosp-01",
          f"got {[e.id for e in hits]}")


# ─────────────────────────────────────────────────────────────
# 4. Prompt injection
# ─────────────────────────────────────────────────────────────

def test_build_prompt_includes_lore():
    banner("build_prompt: lore snippets appear in prompt")

    # zh
    g.Config.LANG = "zh"
    state = g.GameState()
    state.world.location = "Hospital"
    state.world.weather = g.Weather.OVERCAST
    state.world.time_of_day = g.TimeOfDay.NIGHT
    state.world.day = 5
    state.world.threat_level = 7
    event = {"title": "走廊尽头", "description": "一声低吼从黑暗中传来。"}

    lore = "- 走廊两侧的病床都空着，床单被褥扯到地上。\n- 夜里你靠的是耳朵。"
    prompt = g.build_prompt(state, event, action_context="小心前进",
                            lore_snippets=lore)
    check("zh prompt contains '场景参考'", "场景参考" in prompt, prompt[:300])
    check("zh prompt contains the lore body",
          "走廊两侧的病床都空着" in prompt)
    # The directive to borrow-not-copy
    check("zh prompt contains borrow directive",
          "不要照抄" in prompt or "借鉴" in prompt)

    # Lore must appear BEFORE the event line so the model reads it as context
    idx_lore = prompt.find("场景参考")
    idx_event = prompt.find("事件:")
    check("lore section placed before event line",
          0 < idx_lore < idx_event,
          f"idx_lore={idx_lore} idx_event={idx_event}")

    # en
    g.Config.LANG = "en"
    prompt_en = g.build_prompt(state, event, action_context="move carefully",
                               lore_snippets="- The corridor beds are empty.\n- At night you navigate by ear.")
    check("en prompt contains 'Scene reference'",
          "Scene reference" in prompt_en)
    check("en prompt contains borrow directive",
          "borrow" in prompt_en and "verbatim" in prompt_en)
    # Empty snippets → no Scene reference label
    prompt_empty = g.build_prompt(state, event, lore_snippets="")
    check("no section when snippets empty",
          "Scene reference" not in prompt_empty and "场景参考" not in prompt_empty)

    # reset
    g.Config.LANG = "zh"


# ─────────────────────────────────────────────────────────────
# 5. Format helper
# ─────────────────────────────────────────────────────────────

def test_format_for_prompt():
    banner("LoreStore.format_for_prompt")
    store = LoreStore()
    hits = store.query("Hospital", "Overcast", "Night",
                       query_text="dark corridor", k=2,
                       include_atmosphere=True)
    out_zh = store.format_for_prompt(hits, lang="zh")
    out_en = store.format_for_prompt(hits, lang="en")
    check("zh format yields non-empty bulleted lines",
          out_zh and all(l.startswith("- ") for l in out_zh.splitlines()))
    check("en format yields non-empty bulleted lines",
          out_en and all(l.startswith("- ") for l in out_en.splitlines()))
    check("zh and en differ (bilingual text)", out_zh != out_en)

    # Empty list → empty string
    check("empty entries → empty string", store.format_for_prompt([]) == "")


# ─────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────

def main():
    print("Running Phase 2 headless lore tests…")
    test_corpus_shape()
    test_location_filter()
    test_weather_time_filter()
    test_wildcard_atmosphere()
    test_bm25_ranking()
    test_build_prompt_includes_lore()
    test_format_for_prompt()

    total = PASS + FAIL
    print(f"\n══════ {PASS}/{total} passed ══════")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
