"""Test LLM output quality by sending sample prompts."""
import requests

SERVER = "http://127.0.0.1:8384"

def send_prompt(system, user_prompt):
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt + "\n/no_think"},
        ],
        "max_tokens": 400,
        "temperature": 0.8,
        "top_p": 0.9,
    }
    r = requests.post(f"{SERVER}/v1/chat/completions", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    msg = data["choices"][0]["message"]
    return (msg.get("content") or "").strip()

SYSTEM = """You are the narrator of a zombie apocalypse text adventure. Write in second person, present tense. Short sentences. Grim tone. Show what the player sees, hears, smells.

RULES:
1. If a player action is given, your FIRST sentences must describe what happened when they did it. Then describe the new scene.
2. Write 80-200 words, then end with exactly 3 choices:
[A] action option
[B] action option
[C] action option
3. Never invent items the player doesn't have. Never break character."""

# Test 1: First turn
print("=" * 60)
print("TEST 1: First turn - no previous action")
print("=" * 60)

prompt1 = """Scene: Abandoned Apartment — A ransacked apartment on the third floor. The door barely holds.
Day 1, Dawn, Overcast. Threat 2/10. Weapon: kitchen knife.
You spot what looks like a matchbox partially hidden nearby."""

print(f"\n{send_prompt(SYSTEM, prompt1)}")

# Test 2: With player action
print("\n" + "=" * 60)
print("TEST 2: With player action")
print("=" * 60)

prompt2 = """Story so far: The barricade on the front door groans. It won't hold much longer. Then the player decided to head toward Main Street.
New scene: Main Street — A wide boulevard littered with wrecked cars and dried blood.
Day 1, Dawn, Overcast. Threat 5/10. Weapon: kitchen knife.
A lone walker stumbles into view, dragging one leg behind it.
Start by describing what happened when the player did this."""

print(f"\n{send_prompt(SYSTEM, prompt2)}")

# Test 3: Chinese
print("\n" + "=" * 60)
print("TEST 3: Chinese with player action")
print("=" * 60)

SYSTEM_ZH = """你是丧尸末日文字冒险游戏的叙事者。用第二人称、现在时写作。短句为主，冷硬风格。描述玩家看到、听到、闻到的一切。必须用中文回复。

规则：
1. 如果给出了玩家的行动，你的开头几句必须描述那个行动的后果。然后再描述新场景。
2. 写80-200字叙事，然后以恰好3个选项结尾：
[A] 行动选项
[B] 行动选项
[C] 行动选项
3. 不要凭空编造玩家没有的物品。不要打破角色。"""

prompt3 = """故事到目前为止: 前门的路障在呻吟。撑不了多久了。 然后玩家决定前往Main Street。
新场景: Main Street——宽阔的大街上散落着报废的汽车和干涸的血迹。
第1天，黎明，阴天。威胁5/10。武器: 菜刀。
一个独行尸跌跌撞撞地出现在视野中，拖着一条腿。
从玩家行动的后果开始写起。"""

print(f"\n{send_prompt(SYSTEM_ZH, prompt3)}")

# Test 4: Combat aftermath
print("\n" + "=" * 60)
print("TEST 4: After combat action")
print("=" * 60)

prompt4 = """Story so far: A lone walker stumbles into view, dragging one leg. The stench hits you first. Then the player decided to fight the walker with the kitchen knife (hit, dealt 15 damage).
New scene: Main Street — A wide boulevard littered with wrecked cars and dried blood.
Day 1, Morning, Overcast. Threat 6/10. Weapon: kitchen knife.
Status: badly wounded
The street falls silent after the struggle. A pharmacy sign creaks in the wind nearby.
Start by describing what happened when the player did this."""

print(f"\n{send_prompt(SYSTEM, prompt4)}")

print("\n" + "=" * 60)
print("ALL TESTS DONE")
