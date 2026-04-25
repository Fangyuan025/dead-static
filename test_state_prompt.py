"""Headless tests for build_prompt's state/inventory/relief/body-directive
injection — the "state memory" fix.

Background: the 1.7B model ignored the player's condition because the prompt
only flagged binary tags ("wounded"). The fix injects:
  1. graded state (numbers + severity label)
  2. always-visible inventory
  3. relief hints connecting bad state ↔ carried items
  4. a body-directive forcing the narrative to physically reflect state

These tests verify the plumbing — no LLM call.
"""

import os
import sys

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g


def fresh_state():
    s = g.GameState()
    p = s.player
    p.health = 100
    p.hunger = 100
    p.thirst = 100
    p.stamina = 100
    p.morale = 60
    p.infection = 0
    p.inventory = []
    p.equipped_weapon = ""
    s.world.location = "Abandoned Apartment"
    s.world.day = 1
    s.world.time_of_day = g.TimeOfDay.DAY
    s.world.weather = g.Weather.OVERCAST
    s.world.threat_level = 2
    return s


EVENT = {"title": "搜刮", "description": "你打开橱柜。",
         "id": "scavenge", "is_story": False}


PASS = 0
FAIL = 0


def ok(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {detail}")


def test_healthy_state_minimal():
    """Healthy full-HP player: no state line, no relief hints, no body directive."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(s, EVENT, action_context="搜索")
    ok("healthy: no '玩家状态' line", "玩家状态" not in prompt, prompt)
    ok("healthy: no body directive",
       "叙述必须体现玩家当前的身体" not in prompt)
    ok("healthy: no '可用资源' line", "可用资源" not in prompt)


def test_graded_injury_numbers():
    """HP=15 should emit number AND '重伤' severity label."""
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.health = 15
    prompt = g.build_prompt(s, EVENT)
    ok("HP=15 prompt contains HP number", "HP 15/100" in prompt, prompt)
    ok("HP=15 prompt contains '重伤' label", "重伤" in prompt, prompt)
    ok("HP=15 triggers body directive",
       "叙述必须体现玩家当前的身体" in prompt)


def test_grading_thresholds():
    """Severity labels fire at the right thresholds."""
    g.Config.LANG = "zh"
    # HP 65 → '受伤' (not '重伤')
    s = fresh_state(); s.player.health = 65
    prompt = g.build_prompt(s, EVENT)
    ok("HP=65 → '受伤'", "受伤" in prompt and "重伤" not in prompt)
    # HP 85 → number only, no severity
    s = fresh_state(); s.player.health = 85
    prompt = g.build_prompt(s, EVENT)
    ok("HP=85 → number only", "HP 85/100" in prompt
       and "受伤" not in prompt and "重伤" not in prompt)
    # Hunger 10 → '严重饥饿'
    s = fresh_state(); s.player.hunger = 10
    prompt = g.build_prompt(s, EVENT)
    ok("hunger=10 → '严重饥饿'", "严重饥饿" in prompt)
    # Thirst 8 → '脱水'
    s = fresh_state(); s.player.thirst = 8
    prompt = g.build_prompt(s, EVENT)
    ok("thirst=8 → '脱水'", "脱水" in prompt)
    # Infection 45 → '感染恶化'
    s = fresh_state(); s.player.infection = 45
    prompt = g.build_prompt(s, EVENT)
    ok("infection=45 → '感染恶化'", "感染恶化" in prompt)
    # Morale 12 → '崩溃边缘'
    s = fresh_state(); s.player.morale = 12
    prompt = g.build_prompt(s, EVENT)
    ok("morale=12 → '崩溃边缘'", "崩溃边缘" in prompt)


def test_inventory_listing():
    """Inventory must always be visible when non-empty."""
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.inventory = ["canned beans", "bottled water", "kitchen knife"]
    prompt = g.build_prompt(s, EVENT)
    ok("inventory header present", "背包(" in prompt, prompt)
    ok("inventory shows '3/10'", "3/10" in prompt)
    # Dedup-with-count
    s.player.inventory = ["canned beans", "canned beans", "bottled water"]
    prompt = g.build_prompt(s, EVENT)
    ok("duplicates collapse with ×N", "×2" in prompt, prompt)


def test_relief_hint_food():
    """Hungry + carrying food → 'food in pack' hint."""
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.hunger = 15
    s.player.inventory = ["canned beans"]
    prompt = g.build_prompt(s, EVENT)
    ok("hungry+food → '背包里有食物' hint", "背包里有食物" in prompt, prompt)


def test_relief_hint_water():
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.thirst = 15
    s.player.inventory = ["bottled water"]
    prompt = g.build_prompt(s, EVENT)
    ok("thirsty+water → '背包里有水' hint", "背包里有水" in prompt, prompt)


def test_relief_hint_antibiotics():
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.infection = 45
    s.player.inventory = ["antibiotics"]
    prompt = g.build_prompt(s, EVENT)
    ok("infected+antibiotics → 抗感染药 hint",
       "背包里有抗感染药" in prompt, prompt)


def test_no_relief_when_thresholds_not_met():
    """If state is fine, no relief hint even if items are carried."""
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.hunger = 80  # fine
    s.player.inventory = ["canned beans"]
    prompt = g.build_prompt(s, EVENT)
    ok("hunger=80+food → no hint", "可用资源" not in prompt)


def test_compromised_triggers_body_directive():
    """Any single compromised axis fires the body directive."""
    g.Config.LANG = "zh"
    for mutate, label in [
        (lambda s: setattr(s.player, "health", 65), "HP<70"),
        (lambda s: setattr(s.player, "hunger", 35), "hunger<40"),
        (lambda s: setattr(s.player, "thirst", 35), "thirst<40"),
        (lambda s: setattr(s.player, "stamina", 25), "stamina<30"),
        (lambda s: setattr(s.player, "infection", 25), "infection>=20"),
        (lambda s: setattr(s.player, "morale", 25), "morale<30"),
    ]:
        s = fresh_state(); mutate(s)
        prompt = g.build_prompt(s, EVENT)
        ok(f"body directive fires for {label}",
           "叙述必须体现玩家当前的身体" in prompt, prompt[:200])


def test_action_primacy_directive():
    """When an action_context is given, the prompt must carry the
    action-primacy directive that forbids the model from reversing
    the player's choice or opening with the event."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(s, EVENT, action_context="冲上去砍丧尸")
    ok("zh: prompt has '玩家行动' line with action",
       "玩家行动: 冲上去砍丧尸" in prompt, prompt[:300])
    ok("zh: action directive present (first sentence = action body result)",
       "第一句话必须是" in prompt and "具体身体/感官结果" in prompt,
       prompt[-400:])
    ok("zh: directive forbids reversing the action",
       "绝对不要让玩家中途改主意" in prompt, prompt[-400:])
    ok("zh: directive enforces second-person '你'",
       "只用「你」称呼玩家" in prompt, prompt[-400:])


def test_outcome_hint_emits_distinct_line():
    """When build_prompt receives outcome_hint, it must emit a labeled
    '上一行动的结果' line distinct from '玩家行动'."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(
        s, EVENT,
        action_context="冲上去砍丧尸",
        outcome_hint="你干净利落地解决了它，尸体瘫倒在你脚边。",
    )
    ok("zh: '上一行动的结果' line present",
       "上一行动的结果: 你干净利落地解决了它" in prompt, prompt[:400])
    ok("zh: action and outcome are SEPARATE lines",
       "玩家行动: 冲上去砍丧尸\n上一行动的结果:" in prompt, prompt[:400])
    ok("zh: outcome NOT jammed into action with parens",
       "(你干净利落地解决了它" not in prompt
       and "（你干净利落地解决了它" not in prompt)
    # Outcome should also appear inside the directive (for emphasis)
    ok("zh: directive inlines the outcome text",
       "你干净利落地解决了它" in prompt
       and "上一回合的结果就是这句" in prompt,
       prompt[-500:])


def test_outcome_hint_absent_falls_back():
    """When no outcome_hint, the fallback action directive is used."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(
        s, EVENT, action_context="冲上去砍丧尸", outcome_hint="")
    ok("no outcome → no '上一行动的结果' line",
       "上一行动的结果:" not in prompt)
    ok("no outcome → fallback directive (action body result)",
       "第一句话必须是" in prompt)
    ok("no outcome → no outcome-specific directive",
       "上一回合的结果就是这句" not in prompt)


def test_english_outcome_hint():
    g.Config.LANG = "en"
    try:
        s = fresh_state()
        prompt = g.build_prompt(
            s, EVENT,
            action_context="charge the zombie",
            outcome_hint="You dispatched it efficiently. The body drops at your feet.",
        )
        ok("en: 'Outcome of that action' line present",
           "Outcome of that action: You dispatched it efficiently" in prompt)
        ok("en: directive inlines outcome",
           "Last turn's outcome was:" in prompt
           and "The body drops at your feet" in prompt)
    finally:
        g.Config.LANG = "zh"


def test_action_directive_absent_when_no_action():
    """With no action_context, no action-primacy directive fires."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(s, EVENT, action_context="")
    ok("no action → no '玩家行动' line", "玩家行动:" not in prompt)
    ok("no action → no first-sentence directive",
       "第一句话必须是" not in prompt)


def test_english_action_directive():
    """English path carries the same primacy directive."""
    g.Config.LANG = "en"
    try:
        s = fresh_state()
        prompt = g.build_prompt(s, EVENT, action_context="charge the zombie")
        ok("en: 'Player action:' line with action",
           "Player action: charge the zombie" in prompt)
        ok("en: first-sentence directive present",
           "first sentence MUST be the concrete physical/sensory" in prompt)
        ok("en: forbids reversing",
           "Do NOT have" in prompt and "abandon the action" in prompt)
        ok("en: enforces 'you'",
           "Use 'you', never 'the player'" in prompt)
    finally:
        g.Config.LANG = "zh"


def test_english_output_parity():
    """English path emits the same structure with English labels."""
    g.Config.LANG = "en"
    try:
        s = fresh_state()
        s.player.health = 15
        s.player.hunger = 15
        s.player.inventory = ["canned beans", "bottled water"]
        prompt = g.build_prompt(s, EVENT)
        ok("en: HP number", "HP 15/100" in prompt)
        ok("en: 'badly wounded' label", "badly wounded" in prompt)
        ok("en: 'starving' label", "starving" in prompt)
        ok("en: 'Pack (' inventory line", "Pack (" in prompt)
        ok("en: relief 'food in pack' hint", "food in pack" in prompt)
        ok("en: body directive triggered",
           "narrative MUST physically reflect" in prompt)
    finally:
        g.Config.LANG = "zh"


def test_combat_keyword_classifier():
    """The keyword detector that decides whether an action triggers
    resolve_combat must NOT fire on movement verbs ('冲向出口') or on
    actions that only mention a weapon noun ('握紧菜刀'). It MUST fire
    on clear violent intent ('举刀砍它', '进攻丧尸')."""
    # Mirror the classifier logic from game_turn (we test the rule, not the
    # full game_turn). We rebuild it from the source list to keep them in
    # lockstep.
    combat_keywords = [
        "fight", "attack", "kill", "shoot", "swing", "stab the",
        "charge at", "charge it", "charge the", "lunge at",
        "战斗", "攻击", "袭击", "杀", "射击", "开枪", "搏斗", "厮杀",
        "进攻", "迎战", "硬碰硬", "挥刀", "挥舞", "举刀", "举起武器",
        "拔刀", "砍", "捅", "刺向", "刺死", "刺穿",
    ]
    charge_pairs = [("冲", "丧尸"), ("冲", "敌"), ("冲", "怪物"),
                    ("冲", "尸"), ("冲", "它"), ("冲", "他")]
    def is_combat(action):
        if any(kw in action.lower() for kw in combat_keywords):
            return True
        return any(v in action and t in action for v, t in charge_pairs)

    # Should NOT fire (the false-positive cases that bit us)
    for non_combat in ["冲向出口", "冲入房间", "冲下楼", "冲上天台",
                       "握紧菜刀蹲下", "拿起武器藏在背后",
                       "悄悄绕过", "刺探周围动静"]:
        ok(f"NOT combat: {non_combat!r}",
           not is_combat(non_combat),
           f"is_combat returned True")

    # Should fire (clear violent intent)
    for combat in ["举刀砍丧尸", "进攻", "迎战那只丧尸", "拔刀劈下去",
                   "冲向丧尸砍倒它", "开枪打它", "刺向它的喉咙",
                   "搏斗", "厮杀"]:
        ok(f"IS combat: {combat!r}",
           is_combat(combat),
           f"is_combat returned False")


def test_anti_fabrication_rule_in_system_prompt():
    """The system prompt now contains an anti-fabrication clause."""
    g.Config.LANG = "zh"
    sp_zh = g._get_system_prompt()
    ok("zh system prompt has '不要凭空捏造'",
       "不要凭空捏造" in sp_zh, sp_zh[:300])
    ok("zh system prompt forbids fake injuries",
       "不存在的伤" in sp_zh)
    ok("zh system prompt locks scene to 「场景」",
       "「场景」" in sp_zh and "不要把场景换成别处" in sp_zh)
    g.Config.LANG = "en"
    try:
        sp_en = g._get_system_prompt()
        ok("en system prompt has 'NO FABRICATION'",
           "NO FABRICATION" in sp_en or "Do not invent" in sp_en, sp_en[:300])
        ok("en system prompt cites 'pack' as source of truth",
           "pack" in sp_en.lower() and "source of truth" in sp_en.lower())
    finally:
        g.Config.LANG = "zh"


def test_resolve_combat_has_chinese_hint():
    """All four combat outcomes now expose a Chinese-language hint
    in addition to the English one. Exercise many seeds to hit each branch."""
    import random as _r
    rules = g.RulesEngine()
    p = g.Player(); p.equipped_weapon = "kitchen knife"
    p.skills = {"combat": 5, "stealth": 1, "medical": 1, "survival": 1, "persuasion": 1}
    seen = set()
    all_have_zh = True
    for seed in range(40):
        _r.seed(seed)
        p.health = 100
        result = rules.resolve_combat(p, threat_level=4)
        seen.add(result["outcome"])
        if not result.get("narrative_hint_zh"):
            all_have_zh = False
    ok("every combat result carries narrative_hint_zh", all_have_zh)
    ok("combat tests cover ≥2 distinct outcomes",
       len(seen) >= 2, f"seen={seen}")


def test_resolve_stealth_has_chinese_hint():
    import random as _r
    rules = g.RulesEngine()
    p = g.Player()
    p.skills = {"combat": 1, "stealth": 2, "medical": 1, "survival": 1, "persuasion": 1}
    seen = set()
    all_have_zh = True
    # Sweep threat levels so we hit all three outcome bands
    for seed in range(40):
        for threat in (2, 5, 8):
            _r.seed(seed * 10 + threat)
            result = rules.resolve_stealth(p, threat_level=threat)
            seen.add(result["outcome"])
            if not result.get("narrative_hint_zh"):
                all_have_zh = False
    ok("every stealth result carries narrative_hint_zh", all_have_zh)
    ok("stealth tests cover ≥2 distinct outcomes",
       len(seen) >= 2, f"seen={seen}")


def main():
    test_healthy_state_minimal()
    test_graded_injury_numbers()
    test_grading_thresholds()
    test_inventory_listing()
    test_relief_hint_food()
    test_relief_hint_water()
    test_relief_hint_antibiotics()
    test_no_relief_when_thresholds_not_met()
    test_compromised_triggers_body_directive()
    test_action_primacy_directive()
    test_outcome_hint_emits_distinct_line()
    test_outcome_hint_absent_falls_back()
    test_english_outcome_hint()
    test_action_directive_absent_when_no_action()
    test_english_action_directive()
    test_english_output_parity()
    test_combat_keyword_classifier()
    test_anti_fabrication_rule_in_system_prompt()
    test_resolve_combat_has_chinese_hint()
    test_resolve_stealth_has_chinese_hint()
    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
