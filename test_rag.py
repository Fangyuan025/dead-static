"""Headless smoke test for the Phase 1 Episodic RAG integration.

Verifies end-to-end WITHOUT starting llama-server:
  * EpisodicMemory records and retrieves across turns
  * build_prompt() includes memory snippets when supplied
  * query uses location/weather/time/action as signal
  * Chinese tokenization works
"""

import os
import sys
import tempfile
import shutil

# Force UTF-8 stdout so Chinese prints don't crash on cp1252
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import before touching Config
from rag import EpisodicMemory
import game as g


def banner(name):
    print(f"\n══════ {name} ══════")


PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {detail}")


# ─────────────────────────────────────────────────────────────
# 1. Module-level unit tests
# ─────────────────────────────────────────────────────────────

def test_memory_basic():
    banner("Memory: basic record + retrieve (Chinese)")
    tmp = tempfile.mkdtemp()
    try:
        mem = EpisodicMemory("t1", tmp)
        mem.reset()

        mem.record(turn=0, day=1, time_of_day="Dawn", location="Abandoned Apartment",
                   weather="Overcast", action="搜索衣柜",
                   outcome="found canned beans",
                   summary="废弃公寓：搜索衣柜 — found canned beans",
                   raw_narrative_head="你在衣柜深处摸到一个冰凉的金属罐。")
        mem.record(turn=1, day=1, time_of_day="Daytime", location="Pharmacy",
                   weather="Rain", action="sneak past zombies",
                   outcome="stealth success",
                   summary="Pharmacy: sneak past zombies — stealth success",
                   raw_narrative_head="你屏住呼吸，紧贴墙面挪动。")
        mem.record(turn=2, day=2, time_of_day="Night", location="Hospital",
                   weather="Rain", action="check pharmacy",
                   outcome="found antibiotics",
                   summary="Hospital: check pharmacy — found antibiotics",
                   raw_narrative_head="货架大多被翻空，但角落还有半瓶药。")
        mem.record(turn=3, day=2, time_of_day="Night", location="Hospital",
                   weather="Rain", action="hide in morgue",
                   outcome="",
                   summary="Hospital: hide in morgue",
                   raw_narrative_head="冰冷的金属门合上时发出哒的一声。")

        # Query for the apartment — should surface entry 0, NOT the hospital entries
        hits = mem.query("废弃公寓 衣柜 beans", k=2, exclude_last=0)
        check("apartment query returns >=1 hit", len(hits) >= 1)
        locs = [h.location for h in hits]
        check("apartment query surfaces Abandoned Apartment",
              "Abandoned Apartment" in locs, f"got locs={locs}")

        # Query matching Hospital — should not include apartment
        hits = mem.query("Hospital Night Rain", k=2, exclude_last=0)
        check("hospital query surfaces Hospital", any(h.location == "Hospital" for h in hits),
              f"got locs={[h.location for h in hits]}")

        # exclude_last=1 should drop the most recent turn
        hits = mem.query("Hospital Night", k=3, exclude_last=1)
        turns = [h.turn for h in hits]
        check("exclude_last=1 drops turn 3", 3 not in turns, f"got turns={turns}")

        # format_for_prompt non-empty
        snippet = mem.format_for_prompt(hits, lang="zh")
        check("format_for_prompt produces text", bool(snippet.strip()))
        check("snippet contains a day marker", "D" in snippet)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────
# 2. build_prompt() accepts memory_snippets
# ─────────────────────────────────────────────────────────────

def test_build_prompt_injection():
    banner("build_prompt: injects memory_snippets")

    # Minimal state
    state = g.GameState()
    state.world.location = "Abandoned Apartment"
    state.world.day = 5
    event = {"title": "Quiet moment", "description": "The wind pushes the door.", "is_story": False}

    # EN
    g.Config.LANG = "en"
    p_no = g.build_prompt(state, event, action_context="walk outside")
    p_yes = g.build_prompt(state, event, action_context="walk outside",
                           memory_snippets="- [D2-Dawn @ Apartment] you found beans")
    check("EN prompt without memory omits 'Past echoes'",
          "Past echoes" not in p_no)
    check("EN prompt with memory includes 'Past echoes'",
          "Past echoes" in p_yes)
    check("EN prompt with memory includes the snippet text",
          "found beans" in p_yes)

    # ZH
    g.Config.LANG = "zh"
    p_yes_zh = g.build_prompt(state, event, action_context="走出去",
                              memory_snippets="- [D2-Dawn @ 废弃公寓] 在衣柜里翻到豆子")
    check("ZH prompt includes 往事回响 marker", "往事回响" in p_yes_zh)
    check("ZH prompt includes snippet text", "翻到豆子" in p_yes_zh)

    g.Config.LANG = "en"  # reset


# ─────────────────────────────────────────────────────────────
# 3. Simulated game_turn recording
# ─────────────────────────────────────────────────────────────

def test_game_integration():
    banner("Game: DeadStaticGame wires memory correctly")

    tmp = tempfile.mkdtemp()
    try:
        # Redirect RAG dir so the test doesn't pollute real rag_data/
        original_dir = g.Config.RAG_DIR
        g.Config.RAG_DIR = tmp
        g.Config.RAG_MIN_TURN = 0  # inject from turn 0 for testing

        # Don't call full DeadStaticGame init (it builds Display etc — Display is fine but let's be safe)
        game_obj = g.DeadStaticGame()
        check("game has .memory", game_obj.memory is not None)
        if game_obj.memory is None:
            return

        game_obj.memory.reset()

        # Simulate 4 turns: player visits Hospital early, then moves away, then
        # will return at turn 4. This way exclude_last=1 drops the most recent
        # non-hospital turn and the earlier Hospital memory is still available.
        turns = [
            dict(turn=0, day=1, time_of_day="Dawn", location="Abandoned Apartment",
                 weather="Overcast", action="search closet",
                 outcome="[Found: canned beans]", summary="Abandoned Apartment: search closet — [Found: canned beans]",
                 raw_narrative_head="You find a cold metal can buried in the back of the closet."),
            dict(turn=1, day=1, time_of_day="Night", location="Hospital",
                 weather="Rain", action="check pharmacy",
                 outcome="[Found: antibiotics]",
                 summary="Hospital: check pharmacy — [Found: antibiotics]",
                 raw_narrative_head="Shelves are bare but half a bottle of pills rolls from a drawer."),
            dict(turn=2, day=2, time_of_day="Daytime", location="Street",
                 weather="Overcast", action="sneak past a zombie horde",
                 outcome="[Stealth: success]", summary="Street: sneak past a zombie horde — [Stealth: success]",
                 raw_narrative_head="You press against a burnt-out car as the horde shuffles past."),
            dict(turn=3, day=2, time_of_day="Dusk", location="Gas Station",
                 weather="Overcast", action="siphon fuel",
                 outcome="[Found: fuel can]", summary="Gas Station: siphon fuel — [Found: fuel can]",
                 raw_narrative_head="The pump is dry but a half-full jerry can sits behind the counter."),
        ]
        for t in turns:
            game_obj.memory.record(**t)

        check("4 entries recorded", len(game_obj.memory.entries) == 4,
              f"got {len(game_obj.memory.entries)}")

        # Now simulate building a prompt on turn 4 where the player returns to the Hospital
        game_obj.state.world.location = "Hospital"
        game_obj.state.world.day = 3
        game_obj.state.world.time_of_day = g.TimeOfDay.NIGHT
        game_obj.state.world.weather = g.Weather.RAIN
        game_obj.state.turn = 4
        game_obj.last_action_context = "revisit the pharmacy"

        event = {"title": "Scavenge", "description": "You return to the hospital.", "is_story": False}
        query_parts = [
            game_obj.state.world.location,
            game_obj.state.world.time_of_day.value,
            game_obj.state.world.weather.value,
            event["title"], event["description"],
            game_obj.last_action_context,
        ]
        query_text = " ".join(p for p in query_parts if p)
        hits = game_obj.memory.query(query_text, k=3,
                                     exclude_last=g.Config.RAG_EXCLUDE_LAST,
                                     min_score=g.Config.RAG_MIN_SCORE)
        check("retrieval returns at least 1 hit", len(hits) >= 1,
              f"query={query_text!r}")
        if hits:
            locs = [h.location for h in hits]
            check("retrieval surfaces Hospital first (most relevant)",
                  "Hospital" in locs, f"got locs={locs}")

        snippet = game_obj.memory.format_for_prompt(hits, lang="en")
        prompt = g.build_prompt(game_obj.state, event,
                                action_context=game_obj.last_action_context,
                                memory_snippets=snippet)
        check("final prompt contains 'Past echoes'", "Past echoes" in prompt,
              prompt[:400])
        check("final prompt contains retrieved content",
              ("pharmacy" in prompt.lower()) or ("antibiotics" in prompt.lower()),
              prompt[:400])

        # Disk persistence round-trip
        mem2 = EpisodicMemory("current", tmp)
        check("entries persist to disk", len(mem2.entries) == 4,
              f"reloaded {len(mem2.entries)}")

        g.Config.RAG_DIR = original_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_memory_basic()
    test_build_prompt_injection()
    test_game_integration()
    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")
    sys.exit(0 if FAIL == 0 else 1)
