"""Live end-to-end test of Phase 1 Episodic RAG with a running llama-server.

Drives a scripted game through multiple turns, then makes the player return
to an earlier location and verifies:
  * Episodic memories are recorded on every turn
  * On revisit, the prompt contains a "Past echoes" section
  * The retrieved memories are actually from a previous visit
  * The LLM output references earlier events (weak signal — print for human review)
"""

import os
import sys
import json
import shutil
import tempfile

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g
from rag import EpisodicMemory, summarize_turn

# ─────────────────────────────────────────────────────────────
# Setup — isolated rag dir, ZH language, low MIN_TURN for testing
# ─────────────────────────────────────────────────────────────

TMP = tempfile.mkdtemp()
g.Config.RAG_DIR = TMP
g.Config.RAG_MIN_TURN = 0
g.Config.LANG = "zh"
g.Config.LLM_MAX_TOKENS = 180  # speed up the test


def run_turn(game_obj, location, action, event_title, event_desc,
             time_of_day=g.TimeOfDay.DAY, weather=g.Weather.OVERCAST,
             day=1, is_story=False, extra_tags=None):
    """Simulate one full turn but without the user-input loop.

    Mirrors the code path in DeadStaticGame.game_turn() that matters for RAG:
      1. build_prompt (with retrieval)
      2. call LLM
      3. record the turn in memory
    """
    state = game_obj.state
    state.world.location = location
    state.world.time_of_day = time_of_day
    state.world.weather = weather
    state.world.day = day

    event = {"title": event_title, "description": event_desc,
             "id": "scavenge", "is_story": is_story}

    # Retrieval (matches logic in game_turn)
    memory_snippets = ""
    revisit_memory = ""
    hits = []
    if (game_obj.memory is not None
            and g.Config.RAG_ENABLED
            and state.turn >= g.Config.RAG_MIN_TURN):
        query_parts = [
            state.world.location,
            g.LOCATIONS.get(state.world.location, {}).get("name_zh", ""),
            state.world.time_of_day.value,
            state.world.weather.value,
            event_title, event_desc,
            game_obj.last_action_context,
        ]
        query_text = " ".join(p for p in query_parts if p)
        hits = game_obj.memory.query(
            query_text, k=g.Config.RAG_TOP_K,
            exclude_last=g.Config.RAG_EXCLUDE_LAST,
            min_score=g.Config.RAG_MIN_SCORE,
        )
        memory_snippets = game_obj.memory.format_for_prompt(hits, lang=g.Config.LANG)

        # Revisit detection — mirror the new game.py logic (prefer summary)
        for entry in reversed(game_obj.memory.entries[:-g.Config.RAG_EXCLUDE_LAST]
                              if g.Config.RAG_EXCLUDE_LAST > 0
                              else game_obj.memory.entries):
            if entry.location == state.world.location:
                frag = (entry.summary or entry.raw_narrative_head or "").strip()
                if len(frag) > 100:
                    frag = frag[:100] + "…"
                revisit_memory = frag
                break

    prompt = g.build_prompt(state, event,
                            action_context=game_obj.last_action_context,
                            prev_narrative=game_obj.last_narrative,
                            memory_snippets=memory_snippets,
                            revisit_memory=revisit_memory)

    # Call LLM (non-streaming for scripted test)
    raw = game_obj.llm.generate(g._get_system_prompt(), prompt)
    parsed = g.parse_llm_output(raw, state)
    narrative = parsed["narrative"]

    # Record
    outcome_str = " ".join(extra_tags) if extra_tags else ""
    head = narrative.strip()
    for sep in ["。", ".", "\n"]:
        if sep in head:
            head = head.split(sep, 1)[0] + sep
            break
    head = head[:160]
    loc_display = g.LOCATIONS.get(location, {}).get("name_zh", location)
    auto_summary = f"{loc_display}: {action}"
    if outcome_str:
        auto_summary += " — " + outcome_str

    # Phase 1.5 — use the LLM summarizer (same as game_turn does)
    if g.Config.RAG_LLM_SUMMARY and narrative:
        llm_sum = summarize_turn(
            game_obj.llm,
            narrative=narrative,
            action=action,
            location=loc_display,
            outcome=outcome_str,
            lang=g.Config.LANG,
            max_tokens=g.Config.RAG_LLM_SUMMARY_MAX_TOKENS,
        )
        if llm_sum:
            auto_summary = llm_sum

    game_obj.memory.record(
        turn=state.turn,
        day=day,
        time_of_day=time_of_day.value,
        location=location,
        weather=weather.value,
        action=action,
        outcome=outcome_str,
        summary=auto_summary,
        raw_narrative_head=head,
    )

    # Update cross-turn state
    game_obj.last_narrative = narrative
    game_obj.last_action_context = action
    state.turn += 1
    state.world.discovered_locations = list(
        set(state.world.discovered_locations + [location]))

    return {"prompt": prompt, "raw": raw, "parsed": parsed, "hits": hits,
            "memory_snippets": memory_snippets, "revisit_memory": revisit_memory}


def main():
    # Sanity: server up?
    import requests
    try:
        r = requests.get(f"{g.Config.SERVER_URL}/health", timeout=3)
        r.raise_for_status()
    except Exception as e:
        print(f"✗ llama-server not reachable at {g.Config.SERVER_URL} — {e}")
        sys.exit(2)
    print(f"✓ llama-server reachable at {g.Config.SERVER_URL}")

    # Construct
    game_obj = g.DeadStaticGame()
    game_obj.llm = g.LLMClient()
    game_obj.memory.reset()

    # ─── Scripted 5-turn playthrough ─────────────────────────────
    # T0 — apartment: search for food
    # T1 — hospital: find antibiotics  (the memory we want to retrieve later)
    # T2 — street: flee from horde
    # T3 — gas station: siphon fuel
    # T4 — hospital again: now we should retrieve T1

    script = [
        ("废弃公寓",  "翻找厨房寻找食物",    "安静的时刻", "你在废弃公寓里寻找任何能吃的东西。",
         g.TimeOfDay.DAWN, g.Weather.OVERCAST, 1, ["找到了一罐豆子"]),
        ("医院",      "在药房里翻找药品",     "搜刮",       "医院走廊一片漆黑，你摸到了药房的门。",
         g.TimeOfDay.NIGHT, g.Weather.RAIN, 1, ["找到了抗生素"]),
        ("街道",      "悄悄溜过一群丧尸",     "丧尸群",     "一群丧尸堵住了前进的路。",
         g.TimeOfDay.DAY, g.Weather.OVERCAST, 2, ["潜行成功"]),
        ("加油站",    "抽取残存的汽油",       "搜刮",       "泵站一片狼藉，但还有一个半满的油桶。",
         g.TimeOfDay.DUSK, g.Weather.OVERCAST, 2, ["找到了汽油"]),
        ("医院",      "再次回到药房寻找更多药品", "搜刮",   "你又回到医院了。雨下得更大。",
         g.TimeOfDay.NIGHT, g.Weather.RAIN, 3, None),
    ]

    results = []
    for i, (loc, action, title, desc, tod, wx, day, tags) in enumerate(script):
        print(f"\n───── Turn {i}: {loc} — {action} ─────")
        r = run_turn(game_obj, loc, action, title, desc,
                     time_of_day=tod, weather=wx, day=day, extra_tags=tags)
        results.append(r)
        head = (r["parsed"]["narrative"] or "").strip().splitlines()[:4]
        for h in head:
            print(f"  > {h}")

    # ─── Assertions on turn 4 (revisit) ─────────────────────────
    print("\n══════ 校验 ══════")

    t4 = results[4]
    print(f"\n— turn 4 retrieval hits: {len(t4['hits'])}")
    for h in t4["hits"]:
        print(f"  · D{h.day}-{h.time_of_day} @ {h.location}: {h.summary}")

    PASS = FAIL = 0
    def ok(label, cond, detail=""):
        nonlocal PASS, FAIL
        if cond:
            PASS += 1; print(f"  ✓ {label}")
        else:
            FAIL += 1; print(f"  ✗ {label}  {detail}")

    ok("5 entries recorded", len(game_obj.memory.entries) == 5,
       f"got {len(game_obj.memory.entries)}")

    # Verify LLM summaries were used (not the mechanical fallback pattern)
    llm_shaped = sum(
        1 for e in game_obj.memory.entries
        # mechanical fallback always contains ": " + action + " — " or is just "{loc}: {action}"
        # LLM summaries typically do NOT contain the raw action string verbatim
        if e.action not in e.summary or len(e.summary) < len(e.action) + 10
    )
    ok(f"≥3/5 entries use LLM summary (not mechanical fallback)", llm_shaped >= 3,
       f"llm-shaped={llm_shaped}; summaries={[e.summary for e in game_obj.memory.entries]}")

    print("\n— Recorded summaries:")
    for e in game_obj.memory.entries:
        print(f"    T{e.turn} @ {e.location}: {e.summary}")

    ok("turn 4 retrieved at least 1 memory", len(t4["hits"]) >= 1)

    locs_hit = [h.location for h in t4["hits"]]
    ok("turn 4 retrieved the earlier 医院 (Hospital) visit",
       "医院" in locs_hit,
       f"got locs={locs_hit}")

    ok("turn 4 prompt contains '往事回响' marker",
       "往事回响" in t4["prompt"],
       t4["prompt"][-300:])

    ok("turn 4 prompt embeds the retrieved memory text",
       "抗生素" in t4["prompt"] or "药房" in t4["prompt"],
       t4["prompt"][-500:])

    ok("turn 4 revisit_memory was populated",
       bool(t4["revisit_memory"]),
       f"got {t4['revisit_memory']!r}")

    ok("turn 4 prompt contains the revisit imperative",
       "不是玩家第一次来这里" in t4["prompt"] or "been here before" in t4["prompt"],
       t4["prompt"][-600:])

    # Stronger signal: after the revisit hook, check if the model references the past visit
    narrative_t4 = t4["parsed"]["narrative"] or ""
    revisit_words = ["再次", "又", "上次", "之前", "还记得", "重新", "回到",
                     "again", "before", "last time", "remember"]
    uses_revisit = any(w in narrative_t4 for w in revisit_words)
    ok("turn 4 narrative uses a revisit word (continuity signal)",
       uses_revisit,
       f"narrative excerpt: {narrative_t4[:200]!r}")

    print("\n— Turn 4 full narrative:")
    for line in narrative_t4.splitlines()[:8]:
        print(f"    {line}")

    print(f"\n— Turn 4 revisit_memory clause: {t4['revisit_memory']!r}")

    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")

    # cleanup
    try:
        shutil.rmtree(TMP, ignore_errors=True)
    except Exception:
        pass

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
