"""Diagnostic: when the player keeps picking the same option [A], does
the model actually respond to the choice each turn?

We drive the real DeadStaticGame.game_turn() loop 6 times, always
picking [A]. After each turn we print:
  - the [A] text the player just chose
  - the action_context that gets carried forward
  - the next turn's narrative head (first ~80 chars)

Then for each turn (N>=2) we check whether the narrative head actually
references the previous [A] — by looking for content-word overlap
between option-A's text and the next narrative's opening.
"""

import os
import sys
import tempfile
import re

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g

# Speed + isolation
g.Config.RAG_DIR = tempfile.mkdtemp()
g.Config.RAG_MIN_TURN = 99         # disable episodic during isolation test
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
    print(f"✓ llama-server reachable")

    game_obj = g.DeadStaticGame()
    game_obj.llm = g.LLMClient()
    if game_obj.memory is not None:
        game_obj.memory.reset()

    # Baseline state
    p = game_obj.state.player
    p.health = 90; p.hunger = 85; p.thirst = 85; p.stamina = 85
    p.morale = 60; p.infection = 0
    p.inventory = ["canned beans", "bottled water", "kitchen knife", "flashlight"]
    p.equipped_weapon = "kitchen knife"
    w = game_obj.state.world
    w.location = "Abandoned Apartment"
    w.day = 1; w.time_of_day = g.TimeOfDay.DAY
    w.weather = g.Weather.OVERCAST; w.threat_level = 2

    # ── Silence heavy display output, keep streams invisible ─────────
    class QuietDisplay:
        def __init__(self, real):
            self.real = real
            self.console = getattr(real, "console", None)
        def __getattr__(self, name):
            # Any method we don't override → no-op
            def noop(*a, **k): return None
            return noop
        def print_token(self, tok): pass

    real_display = game_obj.display
    game_obj.display = QuietDisplay(real_display)

    # ── Force display.get_input to always return "A" ─────────────────
    game_obj.display.get_input = lambda prompt_text="> ": "A"

    # ── Capture per-turn data ─────────────────────────────────────────
    turns = []

    # Wrap game_turn so we can capture the prompt, narrative, and chosen [A] text.
    # Capture BEFORE game_turn mutates state — the prompt as-sent is what matters.
    orig_generate_stream = game_obj.llm.generate_stream
    last_prompt = [None]
    last_raw = [None]
    incoming_action = [""]  # action_context AT prompt-build time
    incoming_outcome = [""]  # outcome_hint AT prompt-build time

    def spy_generate_stream(system, prompt, on_token=None):
        last_prompt[0] = prompt
        # Pull the lines we care about straight out of the prompt
        for line in prompt.splitlines():
            if line.startswith("玩家行动: "):
                incoming_action[0] = line[len("玩家行动: "):]
            elif line.startswith("上一行动的结果: "):
                incoming_outcome[0] = line[len("上一行动的结果: "):]
        out = orig_generate_stream(system, prompt, on_token=lambda t: None)
        last_raw[0] = out
        return out

    game_obj.llm.generate_stream = spy_generate_stream

    # Run 6 turns. After each, capture what was IN the prompt (incoming),
    # the narrative the model produced, and the [A] the player just picked.
    N_TURNS = 6
    for i in range(N_TURNS):
        incoming_action[0] = ""
        incoming_outcome[0] = ""
        try:
            game_obj.game_turn()
        except Exception as e:
            print(f"✗ game_turn raised at turn {i}: {e}")
            import traceback; traceback.print_exc()
            break

        opts = game_obj.current_options
        chosen_a = opts.get("A", "(no A option)")
        narrative_head = (game_obj.last_narrative or "").strip().splitlines()
        head_line = narrative_head[0] if narrative_head else ""
        loc_now = game_obj.state.world.location

        turns.append({
            "turn_idx": i,
            "location": loc_now,
            "event_prompt": last_prompt[0] or "",
            "narrative_head": head_line,
            "full_narrative": game_obj.last_narrative or "",
            "chose_A_this_turn": chosen_a,
            "incoming_action": incoming_action[0],
            "incoming_outcome": incoming_outcome[0],
        })

    # ── Print per-turn summary ──────────────────────────────────────
    print(f"\n══════ {len(turns)} turns with ALWAYS-A ══════")
    for t in turns:
        print(f"\n─── Turn {t['turn_idx']} @ {t['location']} ───")
        print(f"  玩家行动 (in prompt this turn):")
        print(f"    {t['incoming_action'] or '(first turn — no action yet)'}")
        print(f"  上一行动的结果 (in prompt this turn):")
        print(f"    {t['incoming_outcome'] or '(none)'}")
        print(f"  narrative head this turn:")
        print(f"    > {t['narrative_head'][:160]}")
        print(f"  [A] just chosen → next turn's 玩家行动:")
        print(f"    {t['chose_A_this_turn']}")

    # ── Plumbing check: does the prompt actually carry the action? ─
    print("\n══════ PLUMBING CHECK ══════")
    PASS = FAIL = 0
    def ok(label, cond, detail=""):
        nonlocal PASS, FAIL
        if cond: PASS += 1; print(f"  ✓ {label}")
        else:    FAIL += 1; print(f"  ✗ {label}  {detail}")

    for i, t in enumerate(turns[1:], start=1):
        ok(f"T{i} prompt has '玩家行动:' line",
           "玩家行动:" in t["event_prompt"])
        ok(f"T{i} incoming_action is non-empty",
           bool(t["incoming_action"]),
           f"got {t['incoming_action']!r}")

    # Outcome plumbing — only check turns where prev action contained a
    # combat keyword (since that's what triggers an outcome hint)
    combat_triggers = ["战斗", "攻击", "杀", "射击", "开枪", "刺", "砍", "冲",
                       "fight", "attack", "kill", "shoot", "swing", "stab", "charge"]
    for i, t in enumerate(turns[1:], start=1):
        prev_chosen = turns[i - 1]["chose_A_this_turn"].lower()
        if any(k in prev_chosen for k in combat_triggers):
            ok(f"T{i} combat-prev → outcome line present",
               bool(t["incoming_outcome"]),
               f"prev_A={turns[i-1]['chose_A_this_turn']!r} outcome={t['incoming_outcome']!r}")

    # ── Semantic check (soft): does narrative head actually reflect prev [A]? ─
    # Strip CJK punctuation, stopwords, single chars; build content set for
    # prev_A and narrative head. Count overlap.
    print("\n══════ SEMANTIC CHECK (narrative reflects prev [A]) ══════")
    STOP = set("的了是在也都很就和与及把被让使你我他她它这那有没不是之也都")

    def content_tokens(s):
        toks = set()
        s = re.sub(r"[，。！？、；：\"'\s（）()\[\]【】…—\-—]+", " ", s or "")
        # bigrams of CJK chars for signal
        cjk = re.findall(r"[\u4e00-\u9fff]", s)
        for j in range(len(cjk) - 1):
            bg = cjk[j] + cjk[j + 1]
            if bg[0] in STOP or bg[1] in STOP: continue
            toks.add(bg)
        return toks

    semantic_fail = 0
    for i, t in enumerate(turns[1:], start=1):
        action = t["incoming_action"]
        outcome = t["incoming_outcome"]
        head = t["narrative_head"]
        # Either the action OR the outcome's content should echo in the head
        targets = content_tokens(action) | content_tokens(outcome)
        head_toks = content_tokens(head)
        overlap = targets & head_toks
        if action or outcome:
            ok(f"T{i} narrative head echoes action or outcome",
               bool(overlap),
               f"action={action!r}  outcome={outcome!r}  head={head[:60]!r}  overlap={overlap}")
            if not overlap:
                semantic_fail += 1

    print(f"\n── Plumbing+semantic: {PASS} passed, {FAIL} failed ──")
    print(f"── Semantic-only failures: {semantic_fail} / {len(turns)-1} inter-turn comparisons ──")

    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
