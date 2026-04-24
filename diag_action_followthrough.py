"""Diagnostic: does the narrative after a choice actually reflect
what the player chose?

Method: hold everything else constant (same state, same event, same
location, same weather), vary ONLY the action_context that would come
from the player's [A]/[B]/[C] pick. If the model is listening, the
two narratives should diverge sharply in the first sentence.

We run 4 paired tests — each pair uses the same event + state but
radically different player actions. We print the prompts and narratives
side-by-side for human inspection, then do a rough keyword scan.
"""

import os
import sys
import tempfile

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g

g.Config.RAG_DIR = tempfile.mkdtemp()
g.Config.RAG_MIN_TURN = 99       # disable episodic retrieval for isolation
g.Config.RAG_LLM_SUMMARY = False
g.Config.LANG = "zh"
g.Config.LLM_MAX_TOKENS = 180
g.Config.LORE_ENABLED = True


def fresh_game():
    game_obj = g.DeadStaticGame()
    game_obj.llm = g.LLMClient()
    if game_obj.memory is not None:
        game_obj.memory.reset()
    p = game_obj.state.player
    p.health = 85; p.hunger = 80; p.thirst = 80; p.stamina = 85
    p.morale = 60; p.infection = 0
    p.inventory = ["canned beans", "bottled water", "kitchen knife", "flashlight"]
    p.equipped_weapon = "kitchen knife"
    w = game_obj.state.world
    w.location = "Abandoned Apartment"
    w.day = 2; w.time_of_day = g.TimeOfDay.NIGHT
    w.weather = g.Weather.OVERCAST; w.threat_level = 3
    return game_obj


def run_once(label, action_ctx, event_title, event_desc):
    go = fresh_game()
    state = go.state
    event = {"title": event_title, "description": event_desc,
             "id": "scavenge", "is_story": False}

    lore_snippets = ""
    if go.lore is not None:
        hits = go.lore.query(
            location=state.world.location,
            weather=state.world.weather.value,
            time_of_day=state.world.time_of_day.value,
            query_text=" ".join([event_title, event_desc, action_ctx]),
            k=g.Config.LORE_TOP_K,
        )
        lore_snippets = go.lore.format_for_prompt(hits, lang=g.Config.LANG)

    prompt = g.build_prompt(
        state, event,
        action_context=action_ctx,
        prev_narrative="",
        memory_snippets="",
        lore_snippets=lore_snippets,
    )
    raw = go.llm.generate(g._get_system_prompt(), prompt)
    parsed = g.parse_llm_output(raw, state)
    narrative = (parsed["narrative"] or "").strip()

    print(f"\n══════ {label} ══════")
    print(f"action_context: {action_ctx!r}")
    print(f"event: {event_title} / {event_desc}")
    print("── narrative ──")
    for line in narrative.splitlines():
        print("  >", line)
    return narrative


def opens_with(narrative, *needles):
    """True if any needle shows up in the first sentence/line of narrative."""
    if not narrative:
        return False
    # take up to first period or first line
    head = narrative.splitlines()[0]
    for sep in ["。", "！", "？", ".", "!", "?"]:
        if sep in head:
            head = head.split(sep, 1)[0] + sep
            break
    return any(n in head for n in needles)


def anywhere(narrative, *needles):
    return any(n in narrative for n in needles)


def main():
    import requests
    try:
        requests.get(f"{g.Config.SERVER_URL}/health", timeout=3).raise_for_status()
    except Exception as e:
        print(f"✗ llama-server not reachable: {e}")
        sys.exit(2)
    print("✓ llama-server reachable")

    PASS = FAIL = 0
    def ok(label, cond, detail=""):
        nonlocal PASS, FAIL
        if cond: PASS += 1; print(f"  ✓ {label}")
        else:    FAIL += 1; print(f"  ✗ {label}  {detail}")

    # ── Pair 1: searching cabinet vs. hiding under bed ──────────────
    ev1 = ("公寓内的动静", "楼下传来碎裂的玻璃声。")
    n1a = run_once("P1-A 搜橱柜", "打开厨房橱柜翻找食物", *ev1)
    n1b = run_once("P1-B 躲床下", "钻到卧室的床底下屏住呼吸", *ev1)

    print("\n── P1 scan ──")
    ok("P1-A narrative mentions searching / kitchen",
       anywhere(n1a, "橱柜", "厨房", "翻", "搜", "找", "打开"),
       n1a[:120])
    ok("P1-B narrative mentions hiding / bed",
       anywhere(n1b, "床底", "床下", "躲", "屏住", "蜷缩", "趴"),
       n1b[:120])
    ok("P1 A vs B: narratives diverge (first 40 chars differ)",
       n1a[:40] != n1b[:40],
       f"A={n1a[:40]!r} B={n1b[:40]!r}")

    # ── Pair 2: opposite combat choices ────────────────────────────
    ev2 = ("遭遇一只丧尸", "一只游荡的丧尸朝你扑来。")
    n2a = run_once("P2-A 拔刀硬砍", "举起菜刀冲上去砍它", *ev2)
    n2b = run_once("P2-B 转身就跑", "立刻转身沿走廊全速奔跑", *ev2)

    print("\n── P2 scan ──")
    ok("P2-A narrative mentions attacking / knife",
       anywhere(n2a, "砍", "刀", "劈", "挥", "冲上去", "刺"),
       n2a[:120])
    ok("P2-B narrative mentions fleeing / running",
       anywhere(n2b, "跑", "奔", "逃", "撤", "冲向", "转身"),
       n2b[:120])
    ok("P2 A vs B: opposite actions produce different openings",
       n2a[:40] != n2b[:40],
       f"A={n2a[:40]!r} B={n2b[:40]!r}")

    # ── Pair 3: use item vs. ignore it ─────────────────────────────
    ev3 = ("短暂歇脚", "你靠在墙边喘气。")
    n3a = run_once("P3-A 喝水", "从背包里拿出瓶装水，拧开喝了几口", *ev3)
    n3b = run_once("P3-B 擦刀", "蹲下用破布擦拭菜刀上的血", *ev3)

    print("\n── P3 scan ──")
    ok("P3-A narrative mentions drinking / water",
       anywhere(n3a, "水", "喝", "瓶", "拧开", "仰"),
       n3a[:120])
    ok("P3-B narrative mentions wiping / knife",
       anywhere(n3b, "擦", "刀", "血", "布", "蹲"),
       n3b[:120])
    ok("P3 A vs B: drinking vs wiping produce different openings",
       n3a[:40] != n3b[:40],
       f"A={n3a[:40]!r} B={n3b[:40]!r}")

    # ── Pair 4: same event, check that action is actually "first" ──
    # The prompt ends with "先描述玩家行动的结果，再描述事件。"
    # Does the opening actually describe the action's result first?
    ev4 = ("门外的脚步声", "门把手开始缓缓转动。")
    n4a = run_once("P4-A 顶门", "用身体顶住门板，死死撑着", *ev4)

    print("\n── P4 scan (action-first directive) ──")
    ok("P4-A opening references the action (body/door push)",
       opens_with(n4a, "顶", "撑", "门", "身体", "抵", "压", "推", "用力", "咬"),
       f"head={n4a[:80]!r}")

    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
