"""Test LLM output quality — check for varied descriptions."""
import requests

SERVER = "http://127.0.0.1:8384"

def send_prompt(system, user_prompt):
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt + "\n/no_think"},
        ],
        "max_tokens": 400,
        "temperature": 0.7,
        "top_p": 0.9,
    }
    r = requests.post(f"{SERVER}/v1/chat/completions", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    return (msg.get("content") or "").strip()

SYSTEM = """You are the narrator of a zombie apocalypse text adventure. Second person, present tense. Short sentences. Vary your descriptions — use sounds, light, temperature, textures, weather, and small human details, not just blood and rot. Build tension through atmosphere, not gore.

RULES:
1. If a player action is given, your FIRST sentences must describe what happened when they did it. Then describe the new scene.
2. Do NOT assume the player picks up, grabs, or uses anything. Only describe what they SEE around them.
3. Write 80-200 words, then end with exactly 3 choices in this format:

[A] action option
[B] action option
[C] action option"""

SYSTEM_ZH = """你是丧尸末日文字冒险游戏的叙事者。用第二人称、现在时写作。短句为主。多样化你的描写——用声音、光线、温度、触感、天气、人文细节来营造氛围，不要只写血腥和腐烂。用气氛制造紧张感，而不是靠血腥场面。必须用中文回复。

规则：
1. 如果给出了玩家的行动，你的开头几句必须描述那个行动发生了什么。然后描述新场景。
2. 不要假设玩家拿起、抓取或使用任何东西。只描述玩家看到的。
3. 写80-200字叙事，然后以恰好3个选项结尾：

[A] 行动选项
[B] 行动选项
[C] 行动选项"""

# Test 1: Dawn, quiet scene
print("=" * 60)
print("TEST 1: Dawn, quiet apartment — atmosphere test")
print("=" * 60)

prompt1 = """Scene: Abandoned Apartment — A ransacked apartment on the third floor. The door barely holds.
Day 1, Dawn, Overcast. Threat 2/10. Weapon: kitchen knife.
Mood: pale light filters in, thick clouds press down.
Event: You spot what looks like a matchbox partially hidden nearby."""

print(f"\n{send_prompt(SYSTEM, prompt1)}")

# Test 2: Night, tense scene
print("\n" + "=" * 60)
print("TEST 2: Night, fog — atmosphere contrast")
print("=" * 60)

prompt2 = """Scene: Back Alley — Narrow alley reeking of rot. Dumpsters line both walls.
Day 3, Night, Fog. Threat 7/10. Weapon: crowbar.
Mood: every shadow could be moving, visibility is barely ten meters.
Event: A strange noise echoes from somewhere to the west."""

print(f"\n{send_prompt(SYSTEM, prompt2)}")

# Test 3: Chinese, afternoon calm
print("\n" + "=" * 60)
print("TEST 3: Chinese — afternoon, calm moment")
print("=" * 60)

prompt3 = """场景: 天台——被风吹拂的天台，可以俯瞰废墟般的天际线。相对安全。
第2天，下午，晴天。威胁1/10。武器: 菜刀。
氛围: 热浪从水泥地上升腾，天空苍白而空旷。
事件: 难得没有什么想要你命的东西。这份寂静令人不安。"""

print(f"\n{send_prompt(SYSTEM_ZH, prompt3)}")

# Test 4: Chinese, with action
print("\n" + "=" * 60)
print("TEST 4: Chinese — rainy morning, player action")
print("=" * 60)

prompt4 = """玩家行动: 搜索杂货店的储藏室
场景: 杂货店——货架基本被搬空了，但后面的储藏室可能还有物资。
第2天，上午，雨天。威胁6/10。武器: 菜刀。
氛围: 微弱的阳光穿透灰尘，雨水敲打着每一个表面。
事件: 你发现附近半隐半现的看起来像是罐装汤的东西。
先描述玩家行动的结果，再描述场景。"""

print(f"\n{send_prompt(SYSTEM_ZH, prompt4)}")

print("\n" + "=" * 60)
print("ALL TESTS DONE")
