"""Diagnostic: long-form scripted playthrough that classifies the kinds
of "out-of-place" narrative the model produces.

We drive game_turn() for ~12 turns with always-A. After each turn we
flag specific categories of failure — the goal is to separate
prompt-fixable problems from "this is the 1.7B Q4 ceiling":

  CATEGORY                                    Fixable by prompt?
  ──────────────────────────────────────────  ──────────────────
  3rd-person leak ("玩家"/"主角")              YES — prompt-rule
  Invents inventory not in pack                YES — pack-grounding
  Invents a different location                 YES — scene-locking
  Action ignored (narrative is about something
    completely unrelated to player's choice)   YES — action-primacy
  Outcome ignored (combat/loot result not
    reflected at all)                          YES — outcome-physical
  ────────
  Tonal/atmospheric vagueness, generic prose   PROBABLY MODEL CEILING
  Abrupt sentence cuts, format glitches        MODEL CEILING
  Word repetition / weird CJK orthography      MODEL CEILING

Output: per-turn flags + a final summary that quantifies how many
issues are prompt-side vs model-side. If prompt-side flags dominate,
there's still room to fix; if model-side dominate, we're at the floor.
"""

import os
import re
import sys
import tempfile
from collections import Counter

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g

g.Config.RAG_DIR = tempfile.mkdtemp()
g.Config.RAG_MIN_TURN = 99
g.Config.RAG_LLM_SUMMARY = False
g.Config.LANG = "zh"
g.Config.LLM_MAX_TOKENS = 220


def main():
    import requests
    try:
        requests.get(f"{g.Config.SERVER_URL}/health", timeout=3).raise_for_status()
    except Exception as e:
        print(f"✗ llama-server not reachable: {e}")
        sys.exit(2)
    print("✓ llama-server reachable")

    game_obj = g.DeadStaticGame()
    game_obj.llm = g.LLMClient()
    if game_obj.memory is not None:
        game_obj.memory.reset()
    p = game_obj.state.player
    p.health = 90; p.hunger = 80; p.thirst = 80; p.stamina = 85
    p.morale = 60; p.infection = 0
    p.inventory = ["canned beans", "bottled water", "kitchen knife", "flashlight"]
    p.equipped_weapon = "kitchen knife"
    w = game_obj.state.world
    w.location = "Abandoned Apartment"; w.day = 1
    w.time_of_day = g.TimeOfDay.DAY; w.weather = g.Weather.OVERCAST
    w.threat_level = 2

    # Quiet display
    class Q:
        def __init__(self, real): self.real=real; self.console=getattr(real,"console",None)
        def __getattr__(self, n):
            def noop(*a, **k): return None
            return noop
        def print_token(self, t): pass
    game_obj.display = Q(game_obj.display)
    game_obj.display.get_input = lambda prompt_text="> ": "A"

    # Spy: grab incoming context
    captured = {"action": "", "outcome": "", "event_title": "", "event_desc": ""}
    orig = game_obj.llm.generate_stream
    def spy(system, prompt, on_token=None):
        captured["action"] = ""
        captured["outcome"] = ""
        captured["event_title"] = ""
        captured["event_desc"] = ""
        for line in prompt.splitlines():
            if line.startswith("玩家行动: "):
                captured["action"] = line[len("玩家行动: "):]
            elif line.startswith("上一行动的结果: "):
                captured["outcome"] = line[len("上一行动的结果: "):]
            elif line.startswith("事件: "):
                captured["event_desc"] = line[len("事件: "):]
        return orig(system, prompt, on_token=lambda t: None)
    game_obj.llm.generate_stream = spy

    N = 12
    rows = []
    for i in range(N):
        try:
            game_obj.game_turn()
        except Exception as e:
            print(f"✗ turn {i} crashed: {e}")
            import traceback; traceback.print_exc()
            break
        opts = game_obj.current_options
        rows.append({
            "i": i,
            "loc": game_obj.state.world.location,
            "inv": list(game_obj.state.player.inventory),
            "weapon": game_obj.state.player.equipped_weapon,
            "incoming_action": captured["action"],
            "incoming_outcome": captured["outcome"],
            "event_desc": captured["event_desc"],
            "narrative": (game_obj.last_narrative or "").strip(),
            "options": dict(opts),
        })

    # ── Print + classify ────────────────────────────────────────────
    flags_prompt_side = Counter()
    flags_model_side = Counter()
    flag_log = []  # (turn, flag, detail)

    KNOWN_LOCATIONS_ZH = ["公寓", "街道", "走廊", "天台", "屋顶", "杂货", "便利店",
                          "警察局", "医院", "下水道", "桥", "检查站", "撤离区", "胡同", "巷"]
    INVENTORY_TOKEN_MAP = {
        "罐头": "canned beans", "豆": "canned beans",
        "瓶装水": "bottled water", "矿泉水": "bottled water",
        "菜刀": "kitchen knife", "刀": "kitchen knife",
        "手电筒": "flashlight", "手电": "flashlight",
    }
    # Items we DON'T have — flag if they appear
    SUSPECT_ITEMS = ["手枪", "步枪", "机枪", "子弹", "弹匣", "炸药", "手雷", "弓", "箭",
                     "匕首", "斧头", "锤子", "撬棍", "扳手", "电锯", "口罩",
                     "防毒", "绷带", "药品", "抗生素", "止痛药", "急救", "针管", "针筒",
                     "电池", "钥匙", "钱包", "手机", "笔记本", "信件", "日记", "报纸",
                     "护士服", "白大褂"]
    # Markers of fabricated biographical content / fabricated injury
    FABRICATION_MARKERS = [
        "溃烂的", "腐烂的脚", "被铁门", "在逃亡中", "被压坏", "断了的腿",
        "失去的手指", "缺了的牙",
    ]

    for r in rows:
        nar = r["narrative"]
        flags_here = []

        # 1) 3rd-person leak
        if re.search(r"玩家", nar) or re.search(r"主角", nar):
            flags_prompt_side["3rd_person_leak"] += 1
            flags_here.append("3rd_person_leak")

        # 2) Invented item — name an item the player isn't carrying
        present_inv = set(r["inv"])
        carried_zh = []
        for zh, en in INVENTORY_TOKEN_MAP.items():
            if en in present_inv:
                carried_zh.append(zh)
        for sus in SUSPECT_ITEMS:
            if sus in nar:
                # Allow if carrying
                en_equiv = INVENTORY_TOKEN_MAP.get(sus)
                if en_equiv and en_equiv in present_inv:
                    continue
                flags_prompt_side["invented_item"] += 1
                flags_here.append(f"invented_item:{sus}")
                break

        # 3) Wrong location — narrative names a location ≠ current
        # Build set of location names that DO match the current loc
        cur_loc = r["loc"]
        cur_loc_zh = g.LOCATIONS.get(cur_loc, {}).get("name_zh", "")
        # Allow current loc keywords; flag anything else from the known set
        hit_other = None
        for kw in KNOWN_LOCATIONS_ZH:
            if kw in nar:
                # Is this kw inside the current location's zh name? (or is it
                # a substring relationship — e.g. cur "公寓" mentioned)
                if cur_loc_zh and kw in cur_loc_zh:
                    continue
                hit_other = kw
                break
        if hit_other:
            flags_prompt_side["wrong_location"] += 1
            flags_here.append(f"wrong_location:{hit_other}")

        # 3b) Biographical fabrication
        for marker in FABRICATION_MARKERS:
            if marker in nar:
                flags_prompt_side["fabricated_backstory"] += 1
                flags_here.append(f"fabricated_backstory:{marker}")
                break

        # 3c) Action reversal — the action's main verb should appear, even
        # loosely, in the narrative. If a CONCRETE action verb is gone,
        # flag it. Only check when the incoming action is non-trivial.
        action = r["incoming_action"]
        if action and len(action) > 5:
            # Pull bigrams of CJK chars from action; skip stop bigrams
            action_cjk = re.findall(r"[一-鿿]", action)
            action_bgs = {action_cjk[k] + action_cjk[k+1]
                          for k in range(len(action_cjk) - 1)}
            action_bgs -= {"你的", "的手", "一下", "在地", "你看", "用力", "脚下"}
            if action_bgs:
                nar_bgs = set()
                nar_cjk = re.findall(r"[一-鿿]", nar[:200])
                for k in range(len(nar_cjk) - 1):
                    nar_bgs.add(nar_cjk[k] + nar_cjk[k+1])
                if not (action_bgs & nar_bgs):
                    flags_prompt_side["action_reversed"] += 1
                    flags_here.append("action_reversed")

        # 4) Format / structure glitches
        if re.search(r"\*\*\s*叙事\s*[:：]", nar) or re.search(r"\*\*\s*选项\s*[:：]", nar):
            flags_model_side["format_leak"] += 1
            flags_here.append("format_leak")
        # Sentence ends abruptly with comma or trails off
        head = nar.splitlines()[0] if nar else ""
        if head and head[-1] in "，、":
            flags_model_side["truncated"] += 1
            flags_here.append("truncated")

        # 5) Word/phrase repetition glitch
        # Hunt for any 4+ char substring repeated 3+ times in narrative
        repeated = None
        for L in (5, 6, 7):
            for j in range(len(nar) - L):
                sub = nar[j:j+L]
                if "，" in sub or "。" in sub: continue
                if nar.count(sub) >= 3:
                    repeated = sub; break
            if repeated: break
        if repeated:
            flags_model_side["loop"] += 1
            flags_here.append(f"loop:{repeated!r}")

        r["flags"] = flags_here

    # ── Per-turn dump ────────────────────────────────────────────────
    print(f"\n══════ {len(rows)} turns ══════")
    for r in rows:
        print(f"\n─── T{r['i']} @ {r['loc']} ───")
        print(f"  in.action  : {r['incoming_action'] or '(none)'}")
        print(f"  in.outcome : {r['incoming_outcome'] or '(none)'}")
        print(f"  event      : {r['event_desc'][:80]}")
        print(f"  inv        : {r['inv']}")
        print(f"  narrative  :")
        for line in r["narrative"].splitlines()[:6]:
            print(f"    > {line[:140]}")
        print(f"  flags      : {r['flags'] or '(clean)'}")

    # ── Summary ──────────────────────────────────────────────────────
    print("\n══════ FLAG SUMMARY ══════")
    print("-- prompt-side (likely fixable) --")
    for k, v in flags_prompt_side.most_common():
        print(f"  {k}: {v}")
    if not flags_prompt_side:
        print("  (none)")
    print("-- model-side (likely 1.7B ceiling) --")
    for k, v in flags_model_side.most_common():
        print(f"  {k}: {v}")
    if not flags_model_side:
        print("  (none)")

    total_p = sum(flags_prompt_side.values())
    total_m = sum(flags_model_side.values())
    total = total_p + total_m
    clean_turns = sum(1 for r in rows if not r["flags"])
    print(f"\n  Clean turns: {clean_turns} / {len(rows)}")
    print(f"  Prompt-side flags: {total_p}")
    print(f"  Model-side flags : {total_m}")
    if total == 0:
        print("\n  → No issues found in this run. Run again for variance.")
    elif total_p > total_m:
        print("\n  → Prompt-side dominates: prompt has more headroom.")
    elif total_m > total_p:
        print("\n  → Model-side dominates: probably at the 1.7B ceiling.")
    else:
        print("\n  → Mixed: both still contributing.")


if __name__ == "__main__":
    main()
