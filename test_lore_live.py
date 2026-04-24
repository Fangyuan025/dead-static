"""Live end-to-end test for Phase 2 Static Lore Corpus.

Starts a real llama-server round-trip and verifies that:
  * Each turn's prompt contains a '场景参考' (scene reference) section
  * The lore snippet is the one matching the current location + weather + time
  * The model actually borrows imagery from lore when generating narrative
    (checked as a soft signal — at least some of the lore vocabulary shows
    up in the narrative output across the 3-turn sample)

This is NOT a deterministic test of model output — small LLMs wander. We
check that the plumbing works and that signal is measurable.
"""

import os
import sys
import tempfile

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g
from rag import EpisodicMemory, LoreStore


# Speed + isolation
g.Config.RAG_DIR = tempfile.mkdtemp()
g.Config.RAG_MIN_TURN = 99      # disable episodic retrieval so we isolate lore
g.Config.RAG_LLM_SUMMARY = False  # skip extra LLM call
g.Config.LANG = "zh"
g.Config.LLM_MAX_TOKENS = 160


def run_turn(game_obj, location_key, weather, time_of_day, event_title, event_desc):
    """Run one scripted turn, driving state like game_turn would.

    Returns (prompt, lore_snippets, narrative).
    """
    state = game_obj.state
    state.world.location = location_key         # MUST be an English key in LOCATIONS
    state.world.weather = weather
    state.world.time_of_day = time_of_day

    event = {"title": event_title, "description": event_desc,
             "id": "scavenge", "is_story": False}

    # Lore retrieval (mirrors the block in DeadStaticGame.game_turn)
    lore_snippets = ""
    lore_hits = []
    if game_obj.lore is not None and g.Config.LORE_ENABLED:
        lore_hits = game_obj.lore.query(
            location=location_key,
            weather=weather.value,
            time_of_day=time_of_day.value,
            query_text=" ".join([event_title, event_desc,
                                 game_obj.last_action_context]),
            k=g.Config.LORE_TOP_K,
            include_atmosphere=g.Config.LORE_INCLUDE_ATMOSPHERE,
        )
        lore_snippets = game_obj.lore.format_for_prompt(lore_hits, lang=g.Config.LANG)

    prompt = g.build_prompt(
        state, event,
        action_context=game_obj.last_action_context,
        prev_narrative=game_obj.last_narrative,
        lore_snippets=lore_snippets,
    )

    raw = game_obj.llm.generate(g._get_system_prompt(), prompt)
    parsed = g.parse_llm_output(raw, state)
    narrative = parsed["narrative"] or ""

    game_obj.last_narrative = narrative
    game_obj.last_action_context = event_title

    return prompt, lore_snippets, lore_hits, narrative


def main():
    import requests
    try:
        requests.get(f"{g.Config.SERVER_URL}/health", timeout=3).raise_for_status()
    except Exception as e:
        print(f"✗ llama-server not reachable at {g.Config.SERVER_URL} — {e}")
        sys.exit(2)
    print(f"✓ llama-server reachable at {g.Config.SERVER_URL}")

    game_obj = g.DeadStaticGame()
    game_obj.llm = g.LLMClient()
    if game_obj.memory is not None:
        game_obj.memory.reset()
    if game_obj.lore is None:
        print("✗ LoreStore did not initialize — check rag.lore import path")
        sys.exit(3)
    print(f"✓ LoreStore loaded: {len(game_obj.lore.specific)} specific + "
          f"{len(game_obj.lore.generic)} atmosphere fragments")

    # ─── Three distinct scenes, each exercising a different lore bucket ───
    script = [
        # (location_key, weather, time_of_day, event_title, event_desc)
        ("Hospital", g.Weather.OVERCAST, g.TimeOfDay.NIGHT,
         "走廊搜索", "医院走廊深处传来拖行的声响。"),
        ("Rooftop", g.Weather.CLEAR, g.TimeOfDay.NIGHT,
         "瞭望城市", "你从楼梯爬上天台，风很大。"),
        ("Sewer Tunnels", g.Weather.RAIN, g.TimeOfDay.DAY,
         "下水道跋涉", "你必须趟过齐膝的脏水前进。"),
    ]

    results = []
    for i, (loc, wx, tod, title, desc) in enumerate(script):
        print(f"\n───── Turn {i}: {loc} ({wx.value} / {tod.value}) ─────")
        prompt, lore, hits, narrative = run_turn(
            game_obj, loc, wx, tod, title, desc)
        results.append({
            "loc": loc, "prompt": prompt, "lore": lore,
            "hits": hits, "narrative": narrative,
        })
        print(f"  lore retrieved ({len(hits)} entries):")
        for h in hits:
            text = h.text_for(g.Config.LANG)
            print(f"    - [{h.id} loc={h.location}] {text[:80]}…")
        print("  narrative head:")
        for line in (narrative.strip().splitlines()[:3] or [""]):
            print(f"    > {line}")

    # ─── Assertions ─────────────────────────────────────────────────
    print("\n══════ 校验 ══════")
    PASS = FAIL = 0

    def ok(label, cond, detail=""):
        nonlocal PASS, FAIL
        if cond:
            PASS += 1; print(f"  ✓ {label}")
        else:
            FAIL += 1; print(f"  ✗ {label}  {detail}")

    # 1. Every turn got lore snippets
    for i, r in enumerate(results):
        ok(f"T{i} ({r['loc']}) got non-empty lore",
           bool(r["lore"].strip()),
           f"snippets: {r['lore']!r}")

    # 2. Every turn's prompt contains the scene-reference section header
    for i, r in enumerate(results):
        ok(f"T{i} prompt contains '场景参考' header",
           "场景参考" in r["prompt"])

    # 3. Every turn retrieved at least one LOCATION-SPECIFIC entry (not just atmosphere)
    for i, r in enumerate(results):
        specific_hits = [h for h in r["hits"] if h.location != "*"]
        ok(f"T{i} retrieved at least one location-specific entry",
           bool(specific_hits),
           f"ids: {[h.id for h in r['hits']]}")

    # 4. The retrieved specific entry matches the current location (no cross-contamination)
    for i, r in enumerate(results):
        specific_hits = [h for h in r["hits"] if h.location != "*"]
        ok(f"T{i} specific entries all match location '{r['loc']}'",
           all(h.location == r["loc"] for h in specific_hits),
           f"got {[(h.id, h.location) for h in specific_hits]}")

    # 5. Hospital/Night scene retrieved hosp-02 (night-gated), NOT hosp-01
    t0 = results[0]
    hosp_specific_ids = [h.id for h in t0["hits"] if h.location == "Hospital"]
    ok("Hospital/Night prefers hosp-02 (night-tagged)",
       "hosp-02" in hosp_specific_ids,
       f"got Hospital ids: {hosp_specific_ids}")

    # 6. Rooftop/Clear/Night should pull roof-02 (night-tagged)
    t1 = results[1]
    roof_ids = [h.id for h in t1["hits"] if h.location == "Rooftop"]
    ok("Rooftop/Clear/Night prefers roof-02",
       "roof-02" in roof_ids,
       f"got Rooftop ids: {roof_ids}")

    # 7. Soft signal — informational only. Small LLMs ignore injected
    # context unevenly; the directive says "borrow, don't copy verbatim".
    # We print echo counts for human review but do NOT fail on them.
    total_echoes = 0
    import re
    for i, r in enumerate(results):
        lore_text = r["lore"]
        cjk_chars = re.findall(r"[\u4e00-\u9fff]", lore_text)
        bigrams = {"".join(cjk_chars[j:j+2]) for j in range(len(cjk_chars) - 1)}
        stop = {"的一", "一下", "的是", "在一", "就是", "的时", "你的", "的门",
                "一个", "一样", "一边", "一直", "一下子"}
        bigrams -= stop
        narrative = r["narrative"]
        matches = sum(1 for bg in bigrams if len(bg) == 2 and bg in narrative)
        print(f"  T{i} narrative echoes {matches} lore bigrams (informational)")
        total_echoes += matches
    print(f"  total lore-vocab echoes across 3 turns: {total_echoes} "
          f"(soft signal, not asserted)")

    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
