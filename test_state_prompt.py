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
    ok("healthy: no '你的状态' line", "你的状态" not in prompt, prompt)
    ok("healthy: no body directive",
       "身体反应符合" not in prompt)
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
       "身体反应符合" in prompt)


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
           "身体反应符合" in prompt, prompt[:200])


def test_action_primacy_directive():
    """When an action_context is given, the prompt must carry the
    action-primacy directive that forbids the model from reversing
    the player's choice or opening with the event."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(s, EVENT, action_context="冲上去砍丧尸")
    ok("zh: prompt has '你的行动' line with action",
       "你的行动: 冲上去砍丧尸" in prompt, prompt[:300])
    ok("zh: action directive present (first sentence = action body)",
       "第一句必须写" in prompt and "「你的行动」" in prompt,
       prompt[-400:])
    ok("zh: directive forbids reversing the action",
       "不要中途换动作" in prompt, prompt[-400:])
    ok("zh: pronoun lock enforces second-person '你' (universal directive)",
       "全程第二人称，只用「你」" in prompt
       and "绝不写「玩家」「主角」" in prompt,
       prompt[-600:])


def test_outcome_hint_emits_distinct_line():
    """When build_prompt receives outcome_hint, it must emit a labeled
    '上一行动的结果' line distinct from '你的行动'."""
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
       "你的行动: 冲上去砍丧尸\n上一行动的结果:" in prompt, prompt[:400])
    ok("zh: outcome NOT jammed into action with parens",
       "(你干净利落地解决了它" not in prompt
       and "（你干净利落地解决了它" not in prompt)
    # Outcome should also appear inside the directive (for emphasis)
    ok("zh: directive inlines the outcome text",
       "你干净利落地解决了它" in prompt
       and "上一回合的结果" in prompt,
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
       "第一句必须写" in prompt)
    ok("no outcome → no outcome-specific directive",
       "上一回合的结果" not in prompt)


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
           "Rewrite the outcome" in prompt
           and "The body drops at your feet" in prompt)
    finally:
        g.Config.LANG = "zh"


def test_action_directive_absent_when_no_action():
    """With no action_context, no action-primacy directive fires."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(s, EVENT, action_context="")
    ok("no action → no '你的行动' line", "你的行动:" not in prompt)
    ok("no action → no first-sentence directive",
       "第一句话必须是" not in prompt)


def test_english_action_directive():
    """English path carries the same primacy directive."""
    g.Config.LANG = "en"
    try:
        s = fresh_state()
        prompt = g.build_prompt(s, EVENT, action_context="charge the zombie")
        ok("en: 'Your action:' line with action",
           "Your action: charge the zombie" in prompt)
        ok("en: first-sentence directive present",
           "first sentence must show 'Your action' executing" in prompt)
        ok("en: forbids reversing",
           "Don't change actions mid-narrative" in prompt
           and "don't let" in prompt
           and "replace the action" in prompt)
        ok("en: pronoun lock enforces 'you' (universal directive)",
           "Second person only — 'you'" in prompt,
           prompt[-700:])
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
           "Body reactions must match" in prompt)
    finally:
        g.Config.LANG = "zh"


def test_no_player_label_in_prompt():
    """The labels feeding the model must NOT contain '玩家'/'Player' as
    a noun the model can echo. Q4_K_M parrots prompt labels into
    narrative ('玩家行动:' → '玩家的手在颤抖')."""
    g.Config.LANG = "zh"
    s = fresh_state()
    s.player.health = 50  # trigger compromised body directive
    s.player.inventory = ["canned beans", "kitchen knife"]
    prompt = g.build_prompt(
        s, EVENT,
        action_context="搜索橱柜",
        outcome_hint="你找到一个空罐头。",
    )
    # Structural labels must not contain the bare noun 玩家
    BAD_LABELS = ["玩家行动:", "玩家状态:", "玩家可能选择"]
    for bad in BAD_LABELS:
        ok(f"zh: prompt does NOT contain bare label {bad!r}",
           bad not in prompt, prompt)
    # Friendly second-person labels ARE present
    ok("zh: '你的行动:' label present", "你的行动:" in prompt)
    ok("zh: '你的状态:' label present", "你的状态:" in prompt)


def test_pronoun_lock_directive():
    """The closing pronoun-lock directive must appear with the bans on
    '玩家' and on picking the next action for the player."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(s, EVENT, action_context="搜索")
    ok("zh: pronoun-lock directive present",
       "全程第二人称，只用「你」" in prompt
       and "绝不写「玩家」「主角」" in prompt,
       prompt[-700:])
    ok("zh: don't-pick-for-player ban present",
       "不要替「你」做下一个动作" in prompt
       and "你必须做出选择" in prompt,
       prompt[-700:])
    ok("zh: filler ending bans present",
       "「你必须做出选择…」" in prompt
       and "「你没有选择，只有…」" in prompt,
       prompt[-700:])
    g.Config.LANG = "en"
    try:
        prompt_en = g.build_prompt(s, EVENT, action_context="search")
        ok("en: pronoun-lock present",
           ("Second person only — 'you'" in prompt_en),
           prompt_en[-700:])
        ok("en: don't-pick-for-player present",
           ("Do not decide the next action for the player" in prompt_en),
           prompt_en[-700:])
        ok("en: filler ending bans present",
           "'You must choose...'" in prompt_en
           and "'You have no choice but to...'" in prompt_en,
           prompt_en[-700:])
    finally:
        g.Config.LANG = "zh"


def test_anti_verbatim_outcome_clause():
    """The outcome directive must instruct REWRITING, not echoing."""
    g.Config.LANG = "zh"
    s = fresh_state()
    prompt = g.build_prompt(
        s, EVENT,
        action_context="举刀砍丧尸",
        outcome_hint="你干净利落地解决了它，尸体瘫倒在你脚边。",
    )
    ok("zh: outcome directive forbids verbatim copy",
       "不要原样照抄" in prompt or "不要照抄" in prompt,
       prompt[-600:])
    g.Config.LANG = "en"
    try:
        prompt_en = g.build_prompt(
            s, EVENT,
            action_context="charge it",
            outcome_hint="You dispatched it efficiently.",
        )
        ok("en: outcome directive forbids verbatim copy",
           "Do NOT copy it" in prompt_en or "verbatim" in prompt_en,
           prompt_en[-600:])
    finally:
        g.Config.LANG = "zh"


def test_long_action_context_trimming():
    """Picking a 50+ char option should leave last_action_context ≤ 25
    chars (or trimmed to first clause). Test the same logic build_prompt
    consumes from."""
    # Mirror the trim logic from game_turn step 9
    def trim(chosen):
        compact = chosen
        if len(compact) > 25:
            for sep in "，。！？；,;.":
                if sep in compact:
                    head = compact.split(sep, 1)[0]
                    if 3 <= len(head) <= 25:
                        return head
            return compact[:25]
        return compact

    long_action = "拼尽全力推开门，却因体力不足而倒退几步，手电筒在墙上投下摇晃的阴影。"
    trimmed = trim(long_action)
    ok("long action trimmed to first clause",
       trimmed == "拼尽全力推开门",
       f"got {trimmed!r}")
    ok("trimmed length ≤ 25", len(trimmed) <= 25)
    # Short action passes through
    ok("short action unchanged", trim("搜索") == "搜索")
    # Action with no separator is hard-cut to 25
    no_sep = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefg"
    ok("no-separator long action hard-cut to 25",
       len(trim(no_sep)) == 25)


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
    ok("zh system prompt locks scene (no foreign location/weather/time)",
       "当前场景之外的地点" in sp_zh or "不要把场景换成别处" in sp_zh,
       sp_zh[:600])
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


def test_options_degenerate_detector():
    """Three identical or first-10-char-identical options → flagged as
    degenerate parse so the repair pass fires."""
    f = g._options_are_degenerate
    ok("3 identical options → degenerate",
       f({"A": "拿绷带", "B": "拿绷带", "C": "拿绷带"}) is True)
    ok("3 head-identical options → degenerate",
       f({"A": "拿起脏绷带，试图擦拭布料",
          "B": "拿起脏绷带，试图擦拭墙壁",
          "C": "拿起脏绷带，试图擦拭门板"}) is True)
    ok("3 distinct options → healthy",
       f({"A": "砍丧尸", "B": "躲到柜子后", "C": "喝水"}) is False)
    ok("empty options → not degenerate",
       f({}) is False)
    ok("single option → not degenerate (caller decides)",
       f({"A": "X"}) is False)


def test_indoor_weather_clause_in_system_prompt():
    """Live-play exposed 'rain hitting player inside the apartment'
    issue. System prompt must explicitly cover indoor weather."""
    g.Config.LANG = "zh"
    sp = g._get_system_prompt()
    ok("zh: indoor-weather clause present",
       "室内场景" in sp and "不会被雨水或风直接打到" in sp,
       sp[:1200])
    g.Config.LANG = "en"
    try:
        sp_en = g._get_system_prompt()
        ok("en: indoor-weather clause present",
           "Indoor scenes" in sp_en and "not directly rained" in sp_en,
           sp_en[:1200])
    finally:
        g.Config.LANG = "zh"


def test_repeat_penalty_in_payload():
    """The LLM payload must carry repeat_penalty / repeat_last_n.
    Without these, Q5_K_M falls into 2-sentence loops and produces 3
    identical options."""
    client = g.LLMClient()
    payload = client._build_payload("sys", "user")
    ok("payload has repeat_penalty",
       "repeat_penalty" in payload
       and 1.0 < payload["repeat_penalty"] <= 1.5,
       f"got {payload.get('repeat_penalty')}")
    ok("payload has repeat_last_n",
       "repeat_last_n" in payload
       and payload["repeat_last_n"] >= 64,
       f"got {payload.get('repeat_last_n')}")


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
    test_no_player_label_in_prompt()
    test_pronoun_lock_directive()
    test_anti_verbatim_outcome_clause()
    test_long_action_context_trimming()
    test_combat_keyword_classifier()
    test_anti_fabrication_rule_in_system_prompt()
    test_resolve_combat_has_chinese_hint()
    test_resolve_stealth_has_chinese_hint()
    test_options_degenerate_detector()
    test_indoor_weather_clause_in_system_prompt()
    test_repeat_penalty_in_payload()
    print(f"\n── Results: {PASS} passed, {FAIL} failed ──")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
