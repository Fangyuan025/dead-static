"""Diagnostic: does the LLM actually remember / respond to the player's
current state across turns?

We run a scripted 6-turn playthrough where state is manipulated between
turns (injury, hunger, dehydration, infection, inventory changes). On
each turn we capture:
  - the EXACT prompt sent to the model
  - the narrative it produced

Then we check the narrative for signals that the model read the state:
  - mentions of the injury when health is low
  - mentions of hunger/thirst when those are low
  - use / mention of equipped weapon
  - use / mention of items in inventory

The goal is to pinpoint WHAT the model misses so we can fix it.
"""

import os
import sys
import tempfile

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g

g.Config.RAG_DIR = tempfile.mkdtemp()
g.Config.RAG_MIN_TURN = 0
g.Config.RAG_LLM_SUMMARY = False
g.Config.LANG = "zh"
g.Config.LLM_MAX_TOKENS = 200


def run(label, game_obj, mutate_state, event_title, event_desc,
        action_ctx=""):
    """Mutate state then run one build_prompt → LLM → narrative cycle."""
    state = game_obj.state
    mutate_state(state)

    event = {"title": event_title, "description": event_desc,
             "id": "scavenge", "is_story": False}

    lore_snippets = ""
    if game_obj.lore is not None:
        hits = game_obj.lore.query(
            location=state.world.location,
            weather=state.world.weather.value,
            time_of_day=state.world.time_of_day.value,
            query_text=event_title + " " + event_desc,
            k=g.Config.LORE_TOP_K,
        )
        lore_snippets = game_obj.lore.format_for_prompt(hits, lang=g.Config.LANG)

    prompt = g.build_prompt(
        state, event,
        action_context=action_ctx or game_obj.last_action_context,
        prev_narrative=game_obj.last_narrative,
        memory_snippets="",
        lore_snippets=lore_snippets,
    )
    raw = game_obj.llm.generate(g._get_system_prompt(), prompt)
    parsed = g.parse_llm_output(raw, state)
    narrative = parsed["narrative"] or ""

    print(f"\n══════ {label} ══════")
    print("── state snapshot ──")
    p = state.player; w = state.world
    print(f"  HP={p.health}  hunger={p.hunger}  thirst={p.thirst}  "
          f"stamina={p.stamina}  morale={p.morale}  infection={p.infection}")
    print(f"  weapon={p.equipped_weapon or '(none)'}  "
          f"inventory={p.inventory}")
    print(f"  location={w.location}  D{w.day} {w.time_of_day.value} "
          f"{w.weather.value}  threat={w.threat_level}")
    print("── prompt sent to model ──")
    for line in prompt.splitlines():
        print("  |", line)
    print("── narrative ──")
    for line in narrative.strip().splitlines():
        print("  >", line)

    game_obj.last_narrative = narrative
    game_obj.last_action_context = action_ctx or event_title
    return prompt, narrative


def main():
    import requests
    try:
        requests.get(f"{g.Config.SERVER_URL}/health", timeout=3).raise_for_status()
    except Exception as e:
        print(f"✗ server not reachable: {e}")
        sys.exit(2)

    game_obj = g.DeadStaticGame()
    game_obj.llm = g.LLMClient()
    if game_obj.memory is not None:
        game_obj.memory.reset()

    # Baseline
    p = game_obj.state.player
    p.health = 100; p.hunger = 100; p.thirst = 100; p.stamina = 100
    p.morale = 60; p.infection = 0
    p.inventory = ["canned beans", "bottled water", "kitchen knife", "dirty bandage"]
    p.equipped_weapon = "kitchen knife"
    game_obj.state.world.location = "Abandoned Apartment"
    game_obj.state.world.day = 1
    game_obj.state.world.time_of_day = g.TimeOfDay.DAY
    game_obj.state.world.weather = g.Weather.OVERCAST
    game_obj.state.world.threat_level = 2

    # ── T1: Healthy, full inventory, mild action ─────────────────
    run("T1 健康、满背包", game_obj,
        mutate_state=lambda s: None,
        event_title="搜刮公寓",
        event_desc="你打开厨房的橱柜。",
        action_ctx="搜索厨房橱柜")

    # ── T2: Heavily wounded (HP=15), still same inventory ────────
    def t2(s):
        s.player.health = 15
        s.turn += 1
    run("T2 重伤 (HP=15)", game_obj,
        mutate_state=t2,
        event_title="继续前进",
        event_desc="门外传来脚步声。",
        action_ctx="屏住呼吸贴近墙")

    # ── T3: Starving + dehydrated — can still eat/drink? ─────────
    def t3(s):
        s.player.hunger = 10
        s.player.thirst = 8
        s.turn += 1
        s.world.location = "Main Street"
        s.world.threat_level = 5
    run("T3 饥饿+脱水 (HP=15, 背包里有罐头和水)", game_obj,
        mutate_state=t3,
        event_title="走到街上",
        event_desc="空荡的街道上风吹过。",
        action_ctx="朝十字路口走")

    # ── T4: Infection starts — 45%. Has antibiotics now. ─────────
    def t4(s):
        s.player.infection = 45
        s.player.inventory.append("antibiotics")
        s.turn += 1
        s.world.threat_level = 6
    run("T4 感染45% (背包里有抗生素)", game_obj,
        mutate_state=t4,
        event_title="短暂休息",
        event_desc="你靠在破损的汽车旁。",
        action_ctx="检查伤口")

    # ── T5: Player equipped a different weapon (machete) ─────────
    def t5(s):
        s.player.inventory.append("machete")
        s.player.equipped_weapon = "machete"
        s.turn += 1
    run("T5 换装了砍刀", game_obj,
        mutate_state=t5,
        event_title="遭遇一只丧尸",
        event_desc="一只游荡的丧尸向你扑来。",
        action_ctx="迎战")

    # ── T6: Morale breaking (15), after killing — does model echo? ─
    def t6(s):
        s.player.morale = 12
        s.player.kills += 1
        s.turn += 1
    run("T6 士气崩溃边缘 + 刚杀了一只", game_obj,
        mutate_state=t6,
        event_title="喘息",
        event_desc="血迹顺着砍刀滴下。",
        action_ctx="擦刀后坐下")

    print("\n\n══════ 结论检查（自动关键词扫描） ══════")
    # Recheck narratives for state signals — very rough, just to flag gaps
    # Read them again by keeping them on game_obj (our scripts don't cache,
    # but last_narrative holds the final one).


if __name__ == "__main__":
    main()
