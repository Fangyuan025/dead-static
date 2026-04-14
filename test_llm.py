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
        "temperature": 0.7,
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
2. Do NOT assume the player picks up, grabs, or uses anything. Only describe what they SEE around them.
3. Write 80-200 words, then end with exactly 3 choices in this format:

[A] action option
[B] action option
[C] action option"""

SYSTEM_ZH = """你是丧尸末日文字冒险游戏的叙事者。用第二人称、现在时写作。短句为主，冷硬风格。描述玩家看到、听到、闻到的一切。必须用中文回复。

规则：
1. 如果给出了玩家的行动，你的开头几句必须描述那个行动发生了什么。然后描述新场景。
2. 不要假设玩家拿起、抓取或使用任何东西。只描述玩家看到的。
3. 写80-200字叙事，然后以恰好3个选项结尾：

[A] 行动选项
[B] 行动选项
[C] 行动选项"""

# Test 1: First turn — no action
print("=" * 60)
print("TEST 1: First turn - no previous action")
print("=" * 60)

prompt1 = """Scene: Abandoned Apartment — A ransacked apartment on the third floor. The door barely holds.
Day 1, Dawn, Overcast. Threat 2/10. Weapon: kitchen knife.
Event: You spot what looks like a matchbox partially hidden nearby."""

print(f"\n{send_prompt(SYSTEM, prompt1)}")

# Test 2: Player moved to new location
print("\n" + "=" * 60)
print("TEST 2: Player action — moved to Main Street")
print("=" * 60)

prompt2 = """Player action: head toward Main Street
Scene: Main Street — A wide boulevard littered with wrecked cars and dried blood.
Day 1, Dawn, Overcast. Threat 5/10. Weapon: kitchen knife.
Event: A lone zombie stumbles into view, dragging one leg behind it.
Start by describing what happened when the player did this."""

print(f"\n{send_prompt(SYSTEM, prompt2)}")

# Test 3: Chinese mode
print("\n" + "=" * 60)
print("TEST 3: Chinese — player moved to Main Street")
print("=" * 60)

prompt3 = """玩家行动: 前往Main Street
场景: Main Street——宽阔的大街上散落着报废的汽车和干涸的血迹。
第1天，黎明，阴天。威胁5/10。武器: 菜刀。
事件: 一只丧尸跌跌撞撞地出现在视野中，拖着一条腿。
先描述玩家行动的结果，再描述场景。"""

print(f"\n{send_prompt(SYSTEM_ZH, prompt3)}")

# Test 4: Combat aftermath
print("\n" + "=" * 60)
print("TEST 4: After combat — player fought zombie")
print("=" * 60)

prompt4 = """Player action: fight the zombie with the kitchen knife (hit, dealt damage)
Scene: Main Street — A wide boulevard littered with wrecked cars and dried blood.
Day 1, Morning, Overcast. Threat 6/10. Weapon: kitchen knife.
Status: badly wounded
Event: The street falls silent. A pharmacy sign creaks in the wind nearby.
Start by describing what happened when the player did this."""

print(f"\n{send_prompt(SYSTEM, prompt4)}")

print("\n" + "=" * 60)
print("ALL TESTS DONE")
