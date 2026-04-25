"""Diagnostic: when the previous turn triggered a mechanical outcome
(combat resolved, item found, stealth check), does the next turn's
narrative actually physicalize that outcome?

We force a combat scenario by directly seeding action_context with a
combat-trigger phrase and last_outcome with a clean Chinese hint.
Then we verify the model's opening reflects the OUTCOME (e.g. body on
the floor) not just the action.
"""

import os
import sys
import tempfile

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g

g.Config.RAG_DIR = tempfile.mkdtemp()
g.Config.RAG_MIN_TURN = 99
g.Config.RAG_LLM_SUMMARY = False
g.Config.LANG = "zh"
g.Config.LLM_MAX_TOKENS = 200


def run_with(action, outcome, label):
    go = g.DeadStaticGame()
    go.llm = g.LLMClient()
    if go.memory is not None:
        go.memory.reset()
    p = go.state.player
    p.health = 80; p.hunger = 70; p.thirst = 70; p.stamina = 70
    p.morale = 55; p.infection = 0
    p.inventory = ["kitchen knife", "bottled water"]
    p.equipped_weapon = "kitchen knife"
    w = go.state.world
    w.location = "Main Street"
    w.day = 3; w.time_of_day = g.TimeOfDay.NIGHT
    w.weather = g.Weather.OVERCAST; w.threat_level = 5

    event = {"title": "短暂喘息",
             "description": "周围又安静下来。",
             "id": "quiet_moment", "is_story": False}

    prompt = g.build_prompt(
        go.state, event,
        action_context=action,
        outcome_hint=outcome,
    )
    raw = go.llm.generate(g._get_system_prompt(), prompt)
    parsed = g.parse_llm_output(raw, go.state)
    narrative = (parsed["narrative"] or "").strip()

    print(f"\n══════ {label} ══════")
    print(f"action: {action!r}")
    print(f"outcome: {outcome!r}")
    print("── narrative ──")
    for line in narrative.splitlines()[:5]:
        print(f"  > {line}")
    return narrative


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

    # ── C1: clean win → expect body/blood imagery ──────────────────
    n1 = run_with(
        action="举起菜刀冲上去砍丧尸",
        outcome="你干净利落地解决了它，尸体瘫倒在你脚边。",
        label="C1 clean_win",
    )
    print("── C1 scan ──")
    ok("C1 narrative shows the outcome (body / fallen / blood)",
       any(kw in n1 for kw in ["尸体", "倒下", "倒在", "瘫倒", "尸", "脚边", "血", "倒地"]),
       n1[:120])

    # ── C2: messy win → expect injury imagery ─────────────────────
    n2 = run_with(
        action="举起菜刀冲上去砍丧尸",
        outcome="你把它放倒了，但它也重重砸了你一下，身上开始发烫疼痛（-12 HP）。",
        label="C2 messy_win",
    )
    print("── C2 scan ──")
    ok("C2 narrative shows injury (pain / burn / blood / hurt)",
       any(kw in n2 for kw in ["疼", "痛", "灼", "发烫", "伤", "血", "砸", "烧"]),
       n2[:120])

    # ── C3: stealth undetected → expect quiet/still imagery ───────
    n3 = run_with(
        action="贴墙绕过那只丧尸",
        outcome="你悄无声息地溜了过去，连呼吸都没被它听见。",
        label="C3 stealth undetected",
    )
    print("── C3 scan ──")
    ok("C3 narrative shows stealth success (quiet / past / behind)",
       any(kw in n3 for kw in ["悄", "无声", "溜", "屏住", "静", "贴", "绕", "经过", "身后"]),
       n3[:120])

    # ── C4: stealth detected → expect alarm imagery ───────────────
    n4 = run_with(
        action="贴墙绕过那只丧尸",
        outcome="它发现了你，目光锁死——现在只能跑或者打。",
        label="C4 stealth detected",
    )
    print("── C4 scan ──")
    ok("C4 narrative shows being spotted (eyes / sound / charge / spot)",
       any(kw in n4 for kw in ["目光", "盯", "发现", "看见", "瞪", "扑", "嘶吼", "锁定", "锁住"]),
       n4[:120])

    # ── C5: found loot → expect item-in-hand imagery ──────────────
    n5 = run_with(
        action="翻找货架",
        outcome="你在这里找到了罐头，现在拿在手里。",
        label="C5 found loot",
    )
    print("── C5 scan ──")
    ok("C5 narrative shows item in hand (hold / weight / can / metal)",
       any(kw in n5 for kw in ["罐头", "握", "手心", "重量", "金属", "手中", "拿"]),
       n5[:120])

    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
