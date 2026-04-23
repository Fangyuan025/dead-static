"""Turn summarizer — uses the LLM to produce a compact, retrieval-friendly
summary of each turn's narrative.

Why not just store the raw narrative?
  * ~120-200 tokens each is too much to inject later
  * Flavor words dilute BM25 signal

Why not just the first sentence?
  * Often opens with weather/atmosphere, no plot beat

Solution: a second, small LLM call at end of turn. ~1-2s, low temperature,
max_tokens=60. Strict prompt → 1 concrete sentence with location + action + result.
"""

from __future__ import annotations


_SYS_ZH = (
    "你是一个末日求生游戏的剧情摘要器。输入一段场景叙述和玩家行动，"
    "你输出一句完整的中文句子：必须具体，融合地点、行动、关键结果；"
    "严禁使用'地点：X；行动：Y；结果：Z'这种字段化、列表化、分号或冒号分隔的写法——必须是一个流畅的句子。"
    "不要气氛描写、不要形容词堆砌；长度不超过 40 字；只输出摘要本身，不要任何前缀或标签。"
    "示例：'在医院药房的抽屉里找到半瓶抗生素，走廊尽头传来脚步声。'"
)

_SYS_EN = (
    "You are a post-apocalyptic game scene summarizer. Given a narrative and "
    "the player's action, output ONE flowing English sentence: concrete, "
    "weaving together location + action + key outcome. DO NOT use a "
    "'Location: X; Action: Y; Outcome: Z' template or any colon/semicolon "
    "field format — must be a natural sentence. No atmosphere, no adjectives; "
    "at most 20 words; output only the summary, no prefix or label. "
    "Example: 'Found half a bottle of antibiotics in a hospital pharmacy drawer as footsteps echoed down the hall.'"
)


def _build_prompt(narrative: str, action: str, location: str, outcome: str, lang: str) -> str:
    if lang == "zh":
        bits = [
            f"地点: {location}",
            f"玩家行动: {action}",
        ]
        if outcome.strip():
            bits.append(f"机械结果: {outcome}")
        bits.append(f"场景叙述:\n{narrative}")
        bits.append("请用一句话摘要本回合发生了什么（≤40字，具体，无气氛词）：")
        return "\n".join(bits)
    else:
        bits = [
            f"Location: {location}",
            f"Player action: {action}",
        ]
        if outcome.strip():
            bits.append(f"Mechanical outcome: {outcome}")
        bits.append(f"Narrative:\n{narrative}")
        bits.append("Summarize this turn in one sentence (≤20 words, concrete, no atmosphere):")
        return "\n".join(bits)


def summarize_turn(
    llm,                      # LLMClient from game.py (must have .generate())
    narrative: str,
    action: str,
    location: str,
    outcome: str = "",
    lang: str = "en",
    max_tokens: int = 60,
    temperature: float = 0.3,
) -> str | None:
    """Return a compact summary string, or None on failure.

    Uses a direct HTTP call (not llm.generate) so we can override sampling
    params without affecting the main narrative call.
    """
    if not narrative or not narrative.strip():
        return None

    try:
        import requests
        # Reach into Config via llm (caller passes LLMClient which knows server url).
        # Import locally to avoid circular import at module load time.
        from game import Config

        system = _SYS_ZH if lang == "zh" else _SYS_EN
        user = _build_prompt(narrative, action, location, outcome, lang) + "\n/no_think"

        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }
        r = requests.post(
            f"{Config.SERVER_URL}/v1/chat/completions",
            json=payload,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        text = (data["choices"][0]["message"].get("content") or "").strip()

        # Qwen3 sometimes returns an empty content but puts the answer in reasoning
        if not text:
            reasoning = (data["choices"][0]["message"].get("reasoning_content") or "").strip()
            if reasoning:
                # take the last non-empty line of reasoning
                for line in reversed(reasoning.splitlines()):
                    line = line.strip()
                    if line and not line.startswith(("<", "#")):
                        text = line
                        break

        # Strip common prefixes the model might slip in despite the system instruction
        for prefix in ("摘要：", "摘要:", "Summary:", "Summary：", "- ", "* ", "1. "):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        # Strip quotes if the model wrapped the summary
        if text.startswith(("\"", "“", "「")) and text.endswith(("\"", "”", "」")):
            text = text[1:-1]

        # De-template: if the model still produced "地点：X；行动：Y；结果：Z"
        # (or English equivalent), strip the labels and join the values.
        import re as _re
        # ZH: 地点：X；行动：Y；结果：Z  →  X Y Z  then reinsert as sentence
        if _re.search(r"(地点|场景|场地)\s*[：:]", text) or _re.search(r"(行动|动作)\s*[：:]", text):
            parts = _re.split(r"[；;]", text)
            cleaned = []
            for p in parts:
                p = _re.sub(r"^[^：:]*[：:]\s*", "", p).strip(" 。.;")
                if p:
                    cleaned.append(p)
            if cleaned:
                text = "，".join(cleaned)
                if not text.endswith("。"):
                    text += "。"
        # EN: "Location: X; Action: Y; Outcome: Z"
        if _re.search(r"\b(Location|Action|Outcome|Result)\s*:", text, _re.IGNORECASE):
            parts = _re.split(r"[;]", text)
            cleaned = []
            for p in parts:
                p = _re.sub(r"^\s*(Location|Action|Outcome|Result)\s*:\s*", "", p, flags=_re.IGNORECASE).strip(" .;")
                if p:
                    cleaned.append(p)
            if cleaned:
                text = ", ".join(cleaned)
                if not text.endswith("."):
                    text += "."

        # Clip just in case
        if lang == "zh":
            text = text[:80]
        else:
            text = " ".join(text.split()[:30])

        return text or None

    except Exception:
        return None
