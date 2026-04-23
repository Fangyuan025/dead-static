"""Quality test for the Phase 1.5 LLM turn summarizer.

Strategy
--------
Feed the summarizer several realistic narratives (Chinese and English) along
with the player's action and check:
  1. It returns a non-empty string
  2. Output length is within spec (ZH ≤80 chars, EN ≤30 words)
  3. Output contains a concrete key noun from the input (location or outcome)
  4. Output does NOT echo the system-prompt instruction verbatim

We also print the mechanical vs LLM summary side-by-side for human review.
"""

import os
import sys
import time

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game as g
from rag import summarize_turn


# ─── Fixtures ────────────────────────────────────────────────────

CASES = [
    # (lang, location, action, outcome, narrative, expected_keywords)
    ("zh", "医院", "在药房里翻找药品", "找到了抗生素",
     "你摸索着门框，湿滑的墙壁在你身后发出吱呀声。药房里药架大多被扫空，但角落里的抽屉还留着半瓶抗生素。"
     "你迅速把药瓶塞进背包，外面传来脚步声。",
     ["抗生素", "药房", "医院"]),

    ("zh", "加油站", "抽取残存的汽油", "找到了汽油",
     "加油站的泵早已干涸，但柜台后面有一个半满的油桶。你用一根橡皮管子开始吸油，一股刺鼻的气味涌上来。"
     "远处传来引擎声，像是有车在靠近。",
     ["汽油", "加油站", "油"]),

    ("zh", "废弃公寓", "翻找厨房寻找食物", "找到了一罐豆子",
     "厨房的抽屉被翻得乱七八糟，橱柜也早被扫荡过。你在水槽下方摸到一罐沾满灰尘的豆子——还没过期。"
     "冰箱里残留的味道让你胃部翻涌。",
     ["豆子", "厨房", "公寓"]),

    ("en", "Hospital", "search the pharmacy", "found antibiotics",
     "You push through the flickering fluorescent corridor. Most shelves are stripped "
     "clean but a drawer in the corner yields half a bottle of antibiotics. Footsteps "
     "echo somewhere down the hall.",
     ["antibiotics", "pharmacy", "hospital", "drawer"]),

    ("en", "Gas Station", "siphon fuel", "found a fuel can",
     "The pumps are dry, but a jerry can behind the counter is still half full. "
     "You kneel and start siphoning. A distant engine growls, getting closer.",
     ["fuel", "gas", "siphon", "jerry"]),
]


# ─── Sanity: server reachable? ──────────────────────────────────

import requests
try:
    r = requests.get(f"{g.Config.SERVER_URL}/health", timeout=3)
    r.raise_for_status()
except Exception as e:
    print(f"✗ llama-server not reachable — {e}")
    sys.exit(2)
print(f"✓ llama-server reachable at {g.Config.SERVER_URL}\n")


# Dummy LLMClient placeholder (summarizer doesn't actually use it — it reads Config directly)
class _Dummy: pass
dummy_llm = _Dummy()

PASS = FAIL = 0
def ok(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ✓ {label}")
    else:
        FAIL += 1; print(f"  ✗ {label}  {detail}")


# ─── Run each case ──────────────────────────────────────────────

def mechanical(loc, action, outcome):
    s = f"{loc}: {action}"
    if outcome:
        s += " — " + outcome
    return s

total_time = 0.0
for lang, location, action, outcome, narrative, keywords in CASES:
    print(f"══ {lang} · {location} — {action} ══")
    mech = mechanical(location, action, outcome)

    t0 = time.time()
    llm_sum = summarize_turn(
        dummy_llm,
        narrative=narrative,
        action=action,
        location=location,
        outcome=outcome,
        lang=lang,
        max_tokens=60,
        temperature=0.3,
    )
    dt = time.time() - t0
    total_time += dt

    print(f"  [mechanical]  {mech}")
    print(f"  [LLM  {dt:4.1f}s] {llm_sum}")

    # Assertions
    ok("LLM summary non-empty", bool(llm_sum and llm_sum.strip()),
       f"got {llm_sum!r}")
    if not llm_sum:
        print()
        continue

    if lang == "zh":
        ok("ZH summary ≤80 chars", len(llm_sum) <= 80,
           f"got {len(llm_sum)} chars")
    else:
        wc = len(llm_sum.split())
        ok("EN summary ≤30 words", wc <= 30, f"got {wc} words")

    has_keyword = any(kw.lower() in llm_sum.lower() for kw in keywords)
    ok(f"summary contains one of {keywords}", has_keyword,
       f"summary={llm_sum!r}")

    ok("does not echo system instruction",
       "末日求生" not in llm_sum and "post-apocalyptic" not in llm_sum.lower(),
       f"summary={llm_sum!r}")

    print()

print(f"── Results: {PASS} passed, {FAIL} failed | total LLM time: {total_time:.1f}s ──")
sys.exit(0 if FAIL == 0 else 1)
