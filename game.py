"""
DEAD STATIC — A Zombie Apocalypse Text Adventure
Powered by local LLM (llama.cpp server with GGUF Q4 quantized model)
"""

import json
import os
import random
import re
import time
import sys
import subprocess

# ─── Fix Chinese display on Windows CMD / PowerShell ───
if os.name == "nt":
    import ctypes
    import ctypes.wintypes

    # Switch console to UTF-8 code page
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)

    # Ensure Python stdout/stderr use UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Set console font to one that supports CJK characters
    try:
        LF_FACESIZE = 32
        STD_OUTPUT_HANDLE = -11

        class CONSOLE_FONT_INFOEX(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.ULONG),
                ("nFont", ctypes.wintypes.DWORD),
                ("dwFontSize", ctypes.wintypes.COORD),
                ("FontFamily", ctypes.c_uint),
                ("FontWeight", ctypes.c_uint),
                ("FaceName", ctypes.c_wchar * LF_FACESIZE),
            ]

        font = CONSOLE_FONT_INFOEX()
        font.cbSize = ctypes.sizeof(CONSOLE_FONT_INFOEX)
        handle = ctypes.windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        ctypes.windll.kernel32.GetCurrentConsoleFontEx(handle, False, ctypes.byref(font))
        current_font = font.FaceName
        # Only change font if current one is not CJK-capable
        cjk_fonts = {"NSimSun", "SimSun", "新宋体", "Microsoft YaHei", "MS Gothic",
                      "MingLiU", "PMingLiU", "KaiTi", "FangSong", "SimHei"}
        if current_font not in cjk_fonts:
            # Try CJK-capable fonts — prefer ones that look good at larger sizes
            for fname in ["SimSun-ExtB", "NSimSun", "SimSun", "新宋体"]:
                font.FaceName = fname
                font.dwFontSize.X = 0
                font.dwFontSize.Y = 20
                font.FontFamily = 0x36  # FF_MODERN | FIXED_PITCH | TrueType
                font.FontWeight = 400
                ok = ctypes.windll.kernel32.SetCurrentConsoleFontEx(
                    handle, False, ctypes.byref(font))
                if ok:
                    break
        else:
            # Already a CJK font — just ensure a comfortable size
            if font.dwFontSize.Y < 18:
                font.dwFontSize.X = 0
                font.dwFontSize.Y = 20
                ctypes.windll.kernel32.SetCurrentConsoleFontEx(
                    handle, False, ctypes.byref(font))
    except Exception:
        pass  # Non-critical
import atexit
import zipfile
import platform
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

import requests

# ─── Try to import RAG module (graceful degrade if deps missing) ───
try:
    from rag import EpisodicMemory, summarize_turn as _rag_summarize_turn, LoreStore
    HAS_RAG = True
except Exception:
    HAS_RAG = False
    EpisodicMemory = None  # type: ignore
    _rag_summarize_turn = None  # type: ignore
    LoreStore = None  # type: ignore

# ─── Try to import Rich for fancy TUI, fallback to plain text ───
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.columns import Columns
    from rich.text import Text
    from rich.table import Table
    from rich.markdown import Markdown
    from rich.progress import Progress, BarColumn, TextColumn
    from rich import box
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


# ══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # GGUF model settings
    HF_REPO_ID = "Goekdeniz-Guelmez/Josiefied-Qwen3-1.7B-abliterated-v1-gguf"
    GGUF_FILENAME = "josiefied-qwen3-1.7b-abliterated-v1.q4_0.gguf"
    MODEL_DIR = os.path.join(_BASE_DIR, "models")
    GGUF_MODEL_PATH = os.path.join(MODEL_DIR, GGUF_FILENAME)

    # llama-server binary settings
    RUNTIME_DIR = os.path.join(_BASE_DIR, "runtime")
    LLAMA_SERVER_EXE = os.path.join(RUNTIME_DIR, "llama-server.exe")
    # Release info for auto-download
    LLAMA_CPP_VERSION = "b8783"
    LLAMA_CPP_CUDA_ZIP = f"llama-{LLAMA_CPP_VERSION}-bin-win-cuda-13.1-x64.zip"
    LLAMA_CPP_CUDART_ZIP = f"cudart-llama-bin-win-cuda-13.1-x64.zip"
    LLAMA_CPP_CPU_ZIP = f"llama-{LLAMA_CPP_VERSION}-bin-win-cpu-x64.zip"
    LLAMA_CPP_RELEASE_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_CPP_VERSION}"

    # Server settings
    SERVER_HOST = "127.0.0.1"
    SERVER_PORT = 8384
    SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
    N_CTX = 4096
    N_GPU_LAYERS = 99  # offload all to GPU

    # Game settings
    SAVE_FILE = "dead_static_save.json"
    MAX_HISTORY = 8
    LLM_MAX_TOKENS = 250
    LLM_TEMPERATURE = 0.7
    LLM_TOP_P = 0.9

    # Language: "en" or "zh"
    LANG = "en"

    # RAG (Retrieval-Augmented Generation) — Phase 1: episodic memory
    # When enabled, each turn is summarized and stored; relevant past turns
    # are retrieved and injected into the LLM prompt to keep long games coherent.
    RAG_ENABLED = True
    RAG_DIR = os.path.join(_BASE_DIR, "rag_data")
    RAG_TOP_K = 3              # how many past memories to inject per turn
    RAG_MIN_SCORE = 0.5        # BM25 score threshold
    RAG_EXCLUDE_LAST = 1       # skip the N most recent turns (already in immediate ctx)
    RAG_MIN_TURN = 3           # only start injecting once game has > N turns of history
    # Phase 1.5: use a 2nd LLM call to produce compact turn summaries (better retrieval quality).
    # Adds ~1-2s per turn; disable if gameplay feels laggy.
    RAG_LLM_SUMMARY = True
    RAG_LLM_SUMMARY_MAX_TOKENS = 60

    # Phase 2: static lore corpus. Hand-authored per-location flavor +
    # atmosphere fragments retrieved by (location, weather, time) and
    # injected as "scene reference" so narrative stays tonally consistent.
    LORE_ENABLED = True
    LORE_TOP_K = 2             # how many lore lines to inject per turn
    LORE_INCLUDE_ATMOSPHERE = True  # also pull from generic weather/time fragments


# ══════════════════════════════════════════════════════════════════
# TRANSLATION SYSTEM
# ══════════════════════════════════════════════════════════════════

_TEXTS = {
    # Time & Weather
    "Dawn": {"zh": "黎明"}, "Daytime": {"zh": "白天"}, "Dusk": {"zh": "黄昏"}, "Night": {"zh": "夜晚"},
    "Clear skies": {"zh": "晴空"}, "Overcast": {"zh": "阴天"}, "Heavy rain": {"zh": "暴雨"},
    "Dense fog": {"zh": "浓雾"}, "Thunderstorm": {"zh": "雷暴"},

    # UI — Status bar
    "DAY": {"zh": "第 {0} 天"},
    "Threat:": {"zh": "威胁:"},
    "bare hands": {"zh": "赤手空拳"},
    "empty": {"zh": "空"},

    # UI — Menus
    "Choose: ": {"zh": "请选择: "},
    "[1] New Game    [2] Load Game    [3] Settings    [Q] Quit": {
        "zh": "[1] 新游戏    [2] 读取存档    [3] 设置    [Q] 退出"},
    "What is your name, survivor? ": {"zh": "幸存者，你叫什么名字？ "},
    "Survivor": {"zh": "幸存者"},
    "Good luck, {name}. You'll need it.": {"zh": "{name}，祝你好运。你会需要的。"},
    "Press Enter to begin...": {"zh": "按回车键开始..."},
    "Press Enter to exit...": {"zh": "按回车键退出..."},
    "Press Enter to continue...": {"zh": "按回车键继续..."},
    "No save file found.": {"zh": "未找到存档文件。"},
    "Game loaded.": {"zh": "游戏已加载。"},
    "Game saved.": {"zh": "游戏已保存。"},
    "Your choice: ": {"zh": "你的选择: "},
    "Invalid. Choose A, B, or C (or type 'help').": {"zh": "无效输入。请选择 A、B 或 C（或输入 'help'）。"},
    "Save before quitting? (y/n) ": {"zh": "退出前保存？(y/n) "},

    # Opening narrative
    "opening_narrative": {
        "en": (
            "\nYou wake to the sound of distant screaming.\n"
            "Day one. Or maybe two. Hard to tell anymore.\n"
            "The apartment around you has been ransacked. Broken glass, overturned furniture,\n"
            "and a barricaded door that won't hold forever.\n"
            "Outside, the city of the dead stretches in every direction.\n"
            "You need to survive. You need to find a way out.\n"
        ),
        "zh": (
            "\n你在远处的尖叫声中醒来。\n"
            "第一天。也许是第二天。已经分不清了。\n"
            "公寓被洗劫一空。碎玻璃、翻倒的家具，\n"
            "还有一扇撑不了多久的路障门。\n"
            "窗外，死亡之城向四面八方延伸。\n"
            "你必须活下去。你必须找到出路。\n"
        ),
    },
    "You find nearby:": {"zh": "你在附近找到了:"},

    # Settings
    "(Q4 quantized)": {"zh": "(Q4量化)"},
    "[1] Run diagnostics": {"zh": "[1] 运行诊断"},
    "[2] Re-download model & runtime": {"zh": "[2] 重新下载模型和运行时"},
    "[3] Language: {lang}": {"zh": "[3] 语言: {lang}"},
    "[B] Back": {"zh": "[B] 返回"},
    "Language switched to: {lang}": {"zh": "语言已切换为: {lang}"},
    "Settings": {"zh": "设置"},

    # Initialize LLM
    "First-time setup: downloading AI runtime...": {"zh": "首次设置：正在下载AI运行时..."},
    "Runtime download failed.": {"zh": "运行时下载失败。"},
    "Check your internet connection and try again.": {"zh": "请检查网络连接后重试。"},
    "Downloading AI model (one-time, ~1 GB)...": {"zh": "正在下载AI模型（仅需一次，约1 GB）..."},
    "Model download failed.": {"zh": "模型下载失败。"},
    "Starting AI engine...": {"zh": "正在启动AI引擎..."},
    "Failed to start AI engine.": {"zh": "AI引擎启动失败。"},
    "Try restarting the game.": {"zh": "请尝试重启游戏。"},
    "Could not initialize LLM. Check settings.": {"zh": "无法初始化语言模型，请检查设置。"},

    # Commands
    "Equipped {item}.": {"zh": "已装备 {item}。"},
    "Can't equip {item} as a weapon.": {"zh": "无法将 {item} 作为武器装备。"},
    "You don't have that.": {"zh": "你没有这个物品。"},
    "(Auto-generated choices for this turn)": {"zh": "（本回合自动生成选项）"},

    # Game over screens
    "YOU DIED": {"zh": "你 死 了"},
    "Survived {days} days.": {"zh": "存活了 {days} 天。"},
    "Zombies killed:": {"zh": "击杀丧尸:"},
    "People saved:": {"zh": "救助幸存者:"},
    "People left behind:": {"zh": "遗弃的人:"},
    "YOU TURNED": {"zh": "你 变 异 了"},
    "The infection claimed another soul.": {"zh": "感染吞噬了又一个灵魂。"},
    "You lasted {days} days before losing yourself.": {"zh": "你坚持了 {days} 天，最终失去了自我。"},
    "YOU ESCAPED": {"zh": "你 逃 出 生 天"},
    "The helicopter lifts off at dawn.": {"zh": "直升机在黎明时分起飞。"},
    "{days} days. {kills} kills. You made it.": {"zh": "{days} 天。击杀 {kills}。你活下来了。"},

    # Loading
    "The dead city speaks...": {"zh": "死寂之城在低语..."},
    "Thinking...": {"zh": "思考中..."},

    # Help
    "help_text": {
        "en": """COMMANDS (type during your turn):
  [A/B/C]    — Choose an action
  inventory  — View detailed inventory
  use <item> — Use an item (e.g., 'use canned beans')
  equip <item> — Equip a weapon
  map        — View known locations
  status     — Detailed player status
  save       — Save the game
  help       — Show this help
  quit       — Quit the game""",
        "zh": """命令（在你的回合中输入）:
  [A/B/C]    — 选择一个行动
  inventory  — 查看详细物品栏
  use <物品> — 使用物品（如 'use canned beans'）
  equip <物品> — 装备武器
  map        — 查看已知地点
  status     — 详细状态信息
  save       — 保存游戏
  help       — 显示此帮助
  quit       — 退出游戏""",
    },

    # Inventory & Status
    "Inventory": {"zh": "物品栏"},
    "Item": {"zh": "物品"}, "Type": {"zh": "类型"}, "Description": {"zh": "描述"},
    "Status": {"zh": "状态"}, "Map": {"zh": "地图"},
    "Name:": {"zh": "名字:"}, "Skills:": {"zh": "技能:"},
    "Combat": {"zh": "战斗"}, "Stealth": {"zh": "潜行"}, "Medical": {"zh": "医疗"},
    "Survival": {"zh": "生存"}, "Persuasion": {"zh": "说服"},
    "Kills:": {"zh": "击杀:"}, "Saved:": {"zh": "已救:"}, "Abandoned:": {"zh": "遗弃:"},
    "Days survived:": {"zh": "存活天数:"},
    "Current:": {"zh": "当前:"}, "Connected:": {"zh": "连通:"},
    "Discovered locations:": {"zh": "已发现地点:"},

    # Item types
    "food": {"zh": "食物"}, "water": {"zh": "水"}, "medical": {"zh": "医疗"},
    "weapon": {"zh": "武器"}, "utility": {"zh": "工具"}, "armor": {"zh": "护甲"},
    "ammo": {"zh": "弹药"}, "special": {"zh": "特殊"},

    # Title screen
    "A Zombie Apocalypse Text Adventure": {"zh": "末日丧尸文字冒险"},
    "Powered by Local LLM": {"zh": "由本地AI驱动"},
}


def t(key: str, **kwargs) -> str:
    """Translate a string key to the current language."""
    lang = Config.LANG
    entry = _TEXTS.get(key)
    if entry is None:
        text = key
    elif isinstance(entry, dict):
        text = entry.get(lang, entry.get("en", key))
    else:
        text = entry
    for k, v in kwargs.items():
        text = text.replace(f"{{{k}}}", str(v))
    return text


# ══════════════════════════════════════════════════════════════════
# DATA MODELS
# ══════════════════════════════════════════════════════════════════

class TimeOfDay(Enum):
    DAWN = "Dawn"
    DAY = "Daytime"
    DUSK = "Dusk"
    NIGHT = "Night"

class Weather(Enum):
    CLEAR = "Clear skies"
    OVERCAST = "Overcast"
    RAIN = "Heavy rain"
    FOG = "Dense fog"
    STORM = "Thunderstorm"

class GameOver(Enum):
    NONE = "none"
    DEAD = "dead"
    INFECTED = "infected"
    ESCAPED = "escaped"  # win condition

@dataclass
class Player:
    name: str = "Survivor"
    health: int = 100
    hunger: int = 100
    thirst: int = 100
    stamina: int = 100
    morale: int = 60
    infection: int = 0

    inventory: list = field(default_factory=list)
    max_inventory: int = 10
    equipped_weapon: str = ""

    skills: dict = field(default_factory=lambda: {
        "combat": 1,
        "stealth": 2,
        "medical": 1,
        "survival": 1,
        "persuasion": 1,
    })

    kills: int = 0
    days_survived: int = 0
    people_saved: int = 0
    people_abandoned: int = 0

@dataclass
class World:
    day: int = 1
    time_of_day: TimeOfDay = TimeOfDay.DAWN
    weather: Weather = Weather.OVERCAST
    location: str = "Abandoned Apartment"
    location_type: str = "shelter"  # shelter, street, building, wilderness
    threat_level: int = 2  # 0-10
    noise_level: int = 0  # attracted zombies
    discovered_locations: list = field(default_factory=lambda: ["Abandoned Apartment"])
    safe_zones_known: list = field(default_factory=list)
    npcs_alive: list = field(default_factory=list)
    npcs_dead: list = field(default_factory=list)
    story_flags: dict = field(default_factory=dict)

@dataclass
class GameState:
    player: Player = field(default_factory=Player)
    world: World = field(default_factory=World)
    history: list = field(default_factory=list)
    turn: int = 0
    game_over: GameOver = GameOver.NONE


# ══════════════════════════════════════════════════════════════════
# LOCATION DATABASE
# ══════════════════════════════════════════════════════════════════

LOCATIONS = {
    "Abandoned Apartment": {
        "type": "shelter", "base_threat": 2,
        "name_zh": "废弃公寓",
        "description": "A ransacked apartment on the third floor. The door barely holds.",
        "desc_zh": "三楼一间被洗劫的公寓。门勉强撑着。",
        "connections": ["Main Street", "Back Alley", "Rooftop"],
        "loot_table": ["kitchen knife", "canned beans", "dirty bandage", "matchbox"],
        "loot_chance": 0.3,
    },
    "Main Street": {
        "type": "street", "base_threat": 5,
        "name_zh": "主街",
        "description": "A wide boulevard littered with wrecked cars and dried blood.",
        "desc_zh": "宽阔的大街上散落着报废的汽车和干涸的血迹。",
        "connections": ["Abandoned Apartment", "Grocery Store", "Police Station", "Hospital"],
        "loot_table": ["glass bottle", "car battery", "pipe wrench"],
        "loot_chance": 0.2,
    },
    "Back Alley": {
        "type": "street", "base_threat": 4,
        "name_zh": "后巷",
        "description": "Narrow alley reeking of rot. Dumpsters line both walls.",
        "desc_zh": "狭窄的小巷弥漫着腐臭。两侧排列着垃圾箱。",
        "connections": ["Abandoned Apartment", "Pawn Shop", "Sewer Entrance"],
        "loot_table": ["crowbar", "rat meat", "plastic tarp", "duct tape"],
        "loot_chance": 0.4,
    },
    "Rooftop": {
        "type": "shelter", "base_threat": 1,
        "name_zh": "天台",
        "description": "Wind-swept rooftop with a view of the ruined skyline. Relatively safe.",
        "desc_zh": "被风吹拂的天台，可以俯瞰废墟般的天际线。相对安全。",
        "connections": ["Abandoned Apartment"],
        "loot_table": ["rainwater bottle", "signal flare"],
        "loot_chance": 0.15,
    },
    "Grocery Store": {
        "type": "building", "base_threat": 6,
        "name_zh": "杂货店",
        "description": "Shelves mostly bare, but the back storage room might still have supplies.",
        "desc_zh": "货架基本被搬空了，但后面的储藏室可能还有物资。",
        "connections": ["Main Street"],
        "loot_table": ["canned soup", "bottled water", "energy bar", "bleach", "canned beans"],
        "loot_chance": 0.5,
    },
    "Police Station": {
        "type": "building", "base_threat": 7,
        "name_zh": "警察局",
        "description": "Barricaded front, broken windows. Could have weapons — or worse.",
        "desc_zh": "正门被封锁，窗户破碎。可能有武器——也可能有更糟的东西。",
        "connections": ["Main Street"],
        "loot_table": ["pistol", "ammo clip", "body armor vest", "first aid kit", "radio"],
        "loot_chance": 0.35,
    },
    "Hospital": {
        "type": "building", "base_threat": 8,
        "name_zh": "医院",
        "description": "The west wing collapsed. East wing is dark and full of shuffling sounds.",
        "desc_zh": "西翼已经坍塌。东翼一片漆黑，到处是拖行的声音。",
        "connections": ["Main Street", "Hospital Basement"],
        "loot_table": ["antibiotics", "surgical kit", "morphine syringe", "medical mask", "first aid kit"],
        "loot_chance": 0.4,
    },
    "Hospital Basement": {
        "type": "building", "base_threat": 9,
        "name_zh": "医院地下室",
        "description": "Emergency generators still hum. Smells like formaldehyde and death.",
        "desc_zh": "应急发电机还在嗡嗡作响。空气中弥漫着福尔马林和死亡的气味。",
        "connections": ["Hospital"],
        "loot_table": ["experimental antiviral", "hazmat suit", "defibrillator"],
        "loot_chance": 0.25,
    },
    "Pawn Shop": {
        "type": "building", "base_threat": 4,
        "name_zh": "当铺",
        "description": "Iron bars on the windows. The owner didn't make it, but his stock did.",
        "desc_zh": "窗户上装着铁栏。店主没活下来，但他的货物还在。",
        "connections": ["Back Alley"],
        "loot_table": ["machete", "hunting knife", "baseball bat", "binoculars", "lockpick set"],
        "loot_chance": 0.45,
    },
    "Sewer Entrance": {
        "type": "wilderness", "base_threat": 6,
        "name_zh": "下水道入口",
        "description": "A rusted grate leads into the sewer tunnels. Quiet, but claustrophobic.",
        "desc_zh": "一扇锈蚀的铁栅通向下水道。安静，但令人窒息。",
        "connections": ["Back Alley", "Sewer Tunnels"],
        "loot_table": ["flashlight", "rubber boots", "gas mask"],
        "loot_chance": 0.3,
    },
    "Sewer Tunnels": {
        "type": "wilderness", "base_threat": 7,
        "name_zh": "下水道隧道",
        "description": "Ankle-deep water, echoing drips. Something moved in the dark ahead.",
        "desc_zh": "齐踝深的水，回荡的水滴声。黑暗前方有什么东西动了。",
        "connections": ["Sewer Entrance", "River Bridge"],
        "loot_table": ["military MRE", "glow stick", "waterproof bag"],
        "loot_chance": 0.35,
    },
    "River Bridge": {
        "type": "street", "base_threat": 5,
        "name_zh": "河桥",
        "description": "The bridge is partially collapsed but crossable. The other side looks... different.",
        "desc_zh": "桥面部分坍塌但还能通行。对岸看起来……不一样。",
        "connections": ["Sewer Tunnels", "Military Checkpoint"],
        "loot_table": ["rope", "signal flare", "binoculars"],
        "loot_chance": 0.2,
    },
    "Military Checkpoint": {
        "type": "building", "base_threat": 6,
        "name_zh": "军事检查站",
        "description": "Sandbags, razor wire, and silence. The soldiers are long gone — or turned.",
        "desc_zh": "沙袋、铁丝网，一片死寂。士兵们早已离去——或者已经变异。",
        "connections": ["River Bridge", "Evacuation Zone"],
        "loot_table": ["assault rifle", "ammo box", "MRE pack", "military radio", "body armor vest"],
        "loot_chance": 0.4,
    },
    "Evacuation Zone": {
        "type": "building", "base_threat": 3,
        "name_zh": "撤离区",
        "description": "A fenced compound with helicopter pads. The last broadcast said rescue comes at dawn.",
        "desc_zh": "一个有直升机停机坪的围栏营地。最后一次广播说救援会在黎明到来。",
        "connections": ["Military Checkpoint"],
        "loot_table": [],
        "loot_chance": 0.0,
    },
}

# ══════════════════════════════════════════════════════════════════
# ITEM DATABASE
# ══════════════════════════════════════════════════════════════════

ITEMS = {
    # Food & Water
    "canned beans":      {"type": "food", "hunger_restore": 25, "desc": "Dented but sealed", "name_zh": "罐装豆子", "desc_zh": "凹了但密封完好"},
    "canned soup":       {"type": "food", "hunger_restore": 30, "desc": "Chicken noodle, lukewarm", "name_zh": "罐装汤", "desc_zh": "鸡肉面条汤，微温"},
    "energy bar":        {"type": "food", "hunger_restore": 15, "desc": "Expired but edible", "name_zh": "能量棒", "desc_zh": "过期了但还能吃"},
    "rat meat":          {"type": "food", "hunger_restore": 20, "desc": "Cooked over an open flame... hopefully", "name_zh": "鼠肉", "desc_zh": "用明火烤过的……但愿是"},
    "military MRE":      {"type": "food", "hunger_restore": 45, "desc": "Meals Ready to Eat. Tastes like cardboard salvation", "name_zh": "军用口粮", "desc_zh": "即食餐。味如嚼蜡的救赎"},
    "MRE pack":          {"type": "food", "hunger_restore": 45, "desc": "Standard military ration", "name_zh": "口粮包", "desc_zh": "标准军用配给"},
    "bottled water":     {"type": "water", "thirst_restore": 40, "desc": "Clean, sealed", "name_zh": "瓶装水", "desc_zh": "干净、密封"},
    "rainwater bottle":  {"type": "water", "thirst_restore": 25, "desc": "Collected from the rooftop", "name_zh": "雨水瓶", "desc_zh": "从天台收集的"},

    # Medical
    "dirty bandage":     {"type": "medical", "heal": 10, "infection_risk": 10, "desc": "Better than nothing", "name_zh": "脏绷带", "desc_zh": "聊胜于无"},
    "first aid kit":     {"type": "medical", "heal": 35, "infection_risk": 0, "desc": "Standard trauma kit", "name_zh": "急救包", "desc_zh": "标准创伤急救包"},
    "surgical kit":      {"type": "medical", "heal": 50, "infection_risk": 0, "desc": "Professional-grade", "name_zh": "手术工具", "desc_zh": "专业级"},
    "antibiotics":       {"type": "medical", "heal": 10, "infection_reduce": 30, "desc": "Could slow the infection", "name_zh": "抗生素", "desc_zh": "也许能延缓感染"},
    "morphine syringe":  {"type": "medical", "heal": 5, "morale_restore": 30, "desc": "Numbs everything", "name_zh": "吗啡注射器", "desc_zh": "麻痹一切"},
    "experimental antiviral": {"type": "medical", "infection_reduce": 80, "desc": "Labeled 'TRIAL PHASE III'. Might work", "name_zh": "实验性抗病毒药", "desc_zh": "标签写着'三期临床'。也许有效"},
    "medical mask":      {"type": "armor", "protection": 5, "desc": "Thin barrier between you and the air", "name_zh": "医用口罩", "desc_zh": "你和空气之间薄薄的屏障"},
    "bleach":            {"type": "utility", "desc": "Can purify water or clean wounds (painfully)", "name_zh": "漂白剂", "desc_zh": "可以净水或清洗伤口（很疼）"},

    # Weapons
    "kitchen knife":     {"type": "weapon", "damage": 10, "desc": "Dull but desperate", "name_zh": "菜刀", "desc_zh": "钝了但绝望时够用"},
    "hunting knife":     {"type": "weapon", "damage": 15, "desc": "Serrated edge, good grip", "name_zh": "猎刀", "desc_zh": "锯齿刃，握感好"},
    "crowbar":           {"type": "weapon", "damage": 18, "desc": "Heavy, reliable, opens doors too", "name_zh": "撬棍", "desc_zh": "沉重、可靠，还能撬门"},
    "pipe wrench":       {"type": "weapon", "damage": 15, "desc": "Blunt and brutal", "name_zh": "管钳", "desc_zh": "钝重而凶狠"},
    "machete":           {"type": "weapon", "damage": 22, "desc": "Clean cuts. Keep it sharp", "name_zh": "砍刀", "desc_zh": "干脆利落。保持锋利"},
    "baseball bat":      {"type": "weapon", "damage": 16, "desc": "Aluminum. Dented but solid", "name_zh": "棒球棍", "desc_zh": "铝制。凹了但结实"},
    "pistol":            {"type": "weapon", "damage": 30, "noise": 8, "desc": "9mm. Loud. Attracts attention", "name_zh": "手枪", "desc_zh": "9mm。很响。会引来注意"},
    "assault rifle":     {"type": "weapon", "damage": 45, "noise": 10, "desc": "Full auto. Last resort", "name_zh": "突击步枪", "desc_zh": "全自动。最后手段"},
    "glass bottle":      {"type": "weapon", "damage": 8, "desc": "Breaks after one hit", "name_zh": "玻璃瓶", "desc_zh": "一击即碎"},

    # Utility
    "matchbox":          {"type": "utility", "desc": "Half-empty. Precious in the dark", "name_zh": "火柴盒", "desc_zh": "半空的。黑暗中的珍宝"},
    "flashlight":        {"type": "utility", "desc": "Beam cuts through the dark. Batteries unknown", "name_zh": "手电筒", "desc_zh": "光束划破黑暗。电量未知"},
    "signal flare":      {"type": "utility", "desc": "One shot. Make it count", "name_zh": "信号弹", "desc_zh": "只有一发。用在刀刃上"},
    "binoculars":        {"type": "utility", "desc": "Scout ahead without getting close", "name_zh": "望远镜", "desc_zh": "不用靠近就能侦察前方"},
    "lockpick set":      {"type": "utility", "desc": "For doors that won't budge", "name_zh": "开锁工具", "desc_zh": "对付打不开的门"},
    "duct tape":         {"type": "utility", "desc": "Fixes everything. Almost", "name_zh": "胶带", "desc_zh": "万能修补。差不多万能"},
    "plastic tarp":      {"type": "utility", "desc": "Shelter, rain catch, or makeshift stretcher", "name_zh": "塑料布", "desc_zh": "遮蔽、接雨或临时担架"},
    "rope":              {"type": "utility", "desc": "20 feet of nylon. Infinite uses", "name_zh": "绳索", "desc_zh": "6米尼龙绳。用途无限"},
    "glow stick":        {"type": "utility", "desc": "Soft green glow. 8 hours", "name_zh": "荧光棒", "desc_zh": "柔和的绿光。持续8小时"},
    "waterproof bag":    {"type": "utility", "desc": "Keeps gear dry", "name_zh": "防水袋", "desc_zh": "保持装备干燥"},
    "car battery":       {"type": "utility", "desc": "Heavy. Could power something", "name_zh": "汽车电瓶", "desc_zh": "沉重。也许能给什么供电"},
    "radio":             {"type": "utility", "desc": "Handheld two-way radio", "name_zh": "对讲机", "desc_zh": "手持双向对讲机"},
    "military radio":    {"type": "utility", "desc": "Long-range military frequency radio", "name_zh": "军用电台", "desc_zh": "远程军用频率电台"},
    "rubber boots":      {"type": "utility", "desc": "Keeps your feet dry in the sewers", "name_zh": "橡胶靴", "desc_zh": "在下水道里保持双脚干燥"},
    "gas mask":          {"type": "armor", "protection": 10, "desc": "Filters out the worst of it", "name_zh": "防毒面具", "desc_zh": "过滤掉最糟糕的东西"},
    "hazmat suit":       {"type": "armor", "protection": 25, "desc": "Full body protection", "name_zh": "防化服", "desc_zh": "全身防护"},
    "body armor vest":   {"type": "armor", "protection": 20, "desc": "Kevlar. Stops bites too", "name_zh": "防弹背心", "desc_zh": "凯夫拉材质。也能防咬"},

    # Ammo
    "ammo clip":         {"type": "ammo", "rounds": 12, "desc": "9mm magazine", "name_zh": "弹夹", "desc_zh": "9mm弹匣"},
    "ammo box":          {"type": "ammo", "rounds": 30, "desc": "Mixed caliber box", "name_zh": "弹药箱", "desc_zh": "混合口径弹药箱"},

    # Special
    "defibrillator":     {"type": "special", "desc": "Portable AED. Could save a life — or restart a heart that shouldn't beat", "name_zh": "除颤器", "desc_zh": "便携式AED。能救一条命——或重启一颗不该跳动的心"},
}


def _item_name(key: str) -> str:
    """Return localized item name."""
    if Config.LANG == "zh":
        item = ITEMS.get(key)
        if item and "name_zh" in item:
            return item["name_zh"]
    return key


def _item_key_from_input(name: str) -> Optional[str]:
    """Resolve a user-typed item name (English or Chinese) to the canonical English key."""
    name = name.strip().lower()
    # Direct match (English key)
    if name in ITEMS:
        return name
    # Chinese name lookup
    for key, item in ITEMS.items():
        if item.get("name_zh", "").lower() == name or key.lower() == name:
            return key
    # Partial match (substring)
    for key, item in ITEMS.items():
        if name in key.lower() or name in item.get("name_zh", "").lower():
            return key
    return None


def _item_desc(key: str) -> str:
    """Return localized item description."""
    item = ITEMS.get(key, {})
    if Config.LANG == "zh" and "desc_zh" in item:
        return item["desc_zh"]
    return item.get("desc", "")


def _loc_name(key: str) -> str:
    """Return localized location name."""
    if Config.LANG == "zh":
        loc = LOCATIONS.get(key)
        if loc and "name_zh" in loc:
            return loc["name_zh"]
    return key


# ══════════════════════════════════════════════════════════════════
# EVENT SYSTEM
# ══════════════════════════════════════════════════════════════════

EVENT_POOL = {
    "exploration": [
        {
            "id": "scavenge", "weight": 30, "min_day": 1,
            "title": "Scavenging opportunity", "title_zh": "搜刮机会",
            "template": "You spot {item_hint} partially hidden nearby.",
            "template_zh": "你发现附近半隐半现的{item_hint}。",
        },
        {
            "id": "zombie_encounter", "weight": 25, "min_day": 1,
            "title": "Zombie encounter", "title_zh": "丧尸遭遇",
            "template": "A {zombie_type} stumbles into view, {zombie_desc}.",
            "template_zh": "一个{zombie_type}跌跌撞撞地出现在视野中，{zombie_desc}。",
        },
        {
            "id": "survivor_encounter", "weight": 15, "min_day": 2,
            "title": "Survivor encounter", "title_zh": "幸存者遭遇",
            "template": "A {survivor_desc} emerges from the shadows.",
            "template_zh": "一个{survivor_desc}从阴影中走出。",
        },
        {
            "id": "locked_door", "weight": 10, "min_day": 2,
            "title": "Locked door", "title_zh": "上锁的门",
            "template": "A reinforced door blocks your path. {door_hint}.",
            "template_zh": "一扇加固的门挡住了你的去路。{door_hint}。",
        },
        {
            "id": "environmental_hazard", "weight": 10, "min_day": 3,
            "title": "Environmental hazard", "title_zh": "环境危险",
            "template": "The {hazard_type} ahead looks dangerous.",
            "template_zh": "前方的{hazard_type}看起来很危险。",
        },
        {
            "id": "quiet_moment", "weight": 10, "min_day": 1,
            "title": "A moment of calm", "title_zh": "片刻的宁静",
            "template": "For once, nothing is trying to kill you. The silence feels {silence_desc}.",
            "template_zh": "难得没有什么想要你命的东西。这份寂静{silence_desc}。",
        },
    ],
    "night": [
        {
            "id": "horde_passing", "weight": 30,
            "title": "Horde movement", "title_zh": "尸潮涌动",
            "template": "The ground vibrates. A horde of {horde_size} shambles past your hiding spot.",
            "template_zh": "地面在震动。{horde_size}的尸群从你的藏身处旁拖行而过。",
        },
        {
            "id": "night_visitor", "weight": 20,
            "title": "Midnight visitor", "title_zh": "午夜访客",
            "template": "A knock at the {barrier}. Three slow raps. Then silence.",
            "template_zh": "{barrier}传来敲击声。三下，缓慢的。然后是沉默。",
        },
        {
            "id": "nightmare", "weight": 10,
            "title": "Nightmare", "title_zh": "噩梦",
            "template": "You had a bad dream. It felt {dream_quality}. Now you are awake.",
            "template_zh": "你做了个噩梦，梦境{dream_quality}。现在你醒了。",
        },
        {
            "id": "night_noise", "weight": 15,
            "title": "Strange noise", "title_zh": "诡异声响",
            "template": "A {noise_type} echoes from somewhere {direction}.",
            "template_zh": "{direction}传来{noise_type}的回声。",
        },
        {
            "id": "night_rest", "weight": 10,
            "title": "Restful sleep", "title_zh": "安稳的睡眠",
            "template": "You manage a few hours of unbroken sleep. A small mercy.",
            "template_zh": "你总算睡了几个小时的安稳觉。难得的恩赐。",
        },
    ],
    "story": [
        {
            "id": "radio_signal",
            "trigger_day": 3, "once": True,
            "title": "Radio signal", "title_zh": "无线电信号",
            "template": "Static crackles. Then a voice: 'If anyone can hear this... evacuation point Delta... bridge crossing... we leave at dawn on day fifteen. This is not a drill.'",
            "template_zh": '电台嘶嘶作响。然后一个声音:\u201c如果有人能听到\u2026\u2026撤离点Delta\u2026\u2026过桥\u2026\u2026第十五天黎明我们出发。这不是演习。\u201d',
        },
        {
            "id": "first_horde",
            "trigger_day": 5, "once": True,
            "title": "The first horde", "title_zh": "第一波尸潮",
            "template": "The street below fills with the dead. Hundreds. Moving east like a slow river of rot. Your location is no longer safe long-term.",
            "template_zh": "楼下的街道被死者填满。数以百计。像一条缓慢的腐烂之河向东流去。你的位置不再是长期安全的了。",
        },
        {
            "id": "military_broadcast",
            "trigger_day": 8, "once": True,
            "title": "Military broadcast", "title_zh": "军事广播",
            "template": "A military frequency crackles to life: 'Napalm strike on sectors 7 through 12. All survivors move north of the river. You have 72 hours.'",
            "template_zh": '军用频率突然活了:\u201c对7至12区实施凝固汽油弹打击。所有幸存者向河北岸转移。你们还有72小时。\u201d',
        },
        {
            "id": "final_broadcast",
            "trigger_day": 13, "once": True,
            "title": "Final broadcast", "title_zh": "最后的广播",
            "template": "The radio hisses one last time: 'Last helicopter. Dawn. Day fifteen. Bridge checkpoint. No exceptions.' Then silence forever.",
            "template_zh": '电台最后一次嘶鸣:\u201c最后一架直升机。黎明。第十五天。桥头检查站。没有例外。\u201d 然后永远沉默了。',
        },
        {
            "id": "smoke_on_horizon",
            "trigger_day": 4, "once": True,
            "title": "Smoke on the horizon", "title_zh": "地平线上的浓烟",
            "template": "Thick black smoke rises from the east side of the city. Something big is burning. Gunshots echo faintly — someone is still fighting over there.",
            "template_zh": "城市东侧升起浓厚的黑烟。什么大型建筑在燃烧。隐约传来枪声——那边还有人在战斗。",
        },
        {
            "id": "power_grid_failure",
            "trigger_day": 6, "once": True,
            "title": "Power grid failure", "title_zh": "电网崩溃",
            "template": "The last working streetlights flicker and die. The city plunges into true darkness. From now on, nights will be pitch black.",
            "template_zh": "最后还亮着的路灯闪了几下，熄灭了。城市陷入真正的黑暗。从今往后，夜晚将是伸手不见五指的。",
        },
        {
            "id": "refugee_camp_fallen",
            "trigger_day": 7, "once": True,
            "title": "Screams in the distance", "title_zh": "远处的尖叫",
            "template": "A wave of screaming erupts from the south — then cuts off abruptly. The refugee camp at the school must have fallen. You hear the horde moving.",
            "template_zh": "南方爆发出一阵尖叫——然后戛然而止。学校的难民营一定沦陷了。你听到尸群在移动。",
        },
        {
            "id": "airdrop",
            "trigger_day": 9, "once": True,
            "title": "Supply airdrop", "title_zh": "空投补给",
            "template": "A military cargo plane roars overhead. A crate drops with a parachute, landing somewhere to the north. Others will have seen it too.",
            "template_zh": "一架军用运输机从头顶轰鸣而过。一个带降落伞的箱子落在北边某处。别人肯定也看到了。",
        },
        {
            "id": "rain_of_ash",
            "trigger_day": 10, "once": True,
            "title": "Rain of ash", "title_zh": "灰烬之雨",
            "template": "Grey ash drifts down like snow. The napalm strikes have started in the outer sectors. The air smells of burning plastic and something worse.",
            "template_zh": "灰烬像雪一样飘落。外围区域的凝固汽油弹打击已经开始。空气中弥漫着燃烧塑料的味道，还有更糟的东西。",
        },
        {
            "id": "dead_soldiers",
            "trigger_day": 11, "once": True,
            "title": "Abandoned checkpoint", "title_zh": "废弃的检查站",
            "template": "You find a military checkpoint. The soldiers are dead — some shot, some bitten. Their radio plays static. A map on the wall shows the evacuation route marked in red.",
            "template_zh": "你发现了一个军事检查站。士兵们已经死了——有的中弹，有的被咬。他们的电台只有静电噪音。墙上的地图用红线标出了撤离路线。",
        },
    ],
}

ZOMBIE_TYPES = [
    ("lone walker", "dragging one leg behind it"),
    ("bloated corpse", "skin stretched tight and glistening"),
    ("child-sized figure", "still wearing a school backpack"),
    ("fast runner", "head twitching, locked onto your movement"),
    ("crawling torso", "pulling itself along with broken fingernails"),
    ("fresh one", "barely turned — you can still see who they were"),
]
ZOMBIE_TYPES_ZH = [
    ("独行尸", "拖着一条腿"),
    ("膨胀的尸体", "皮肤绷紧，泛着油光"),
    ("小孩大小的身影", "还背着书包"),
    ("飞奔者", "脑袋抽搐，锁定了你的动作"),
    ("爬行的残躯", "用断裂的指甲拖着自己前进"),
    ("刚变异的", "才刚变——你还能看出他们生前的样子"),
]

SURVIVOR_TYPES = [
    "woman clutching a baseball bat, eyes darting",
    "teenage boy with a bandaged arm, shaking",
    "old man with a hunting rifle and hollow cheeks",
    "pair of siblings, no older than twelve",
    "soldier in torn fatigues, thousand-yard stare",
    "nurse still in scrubs, hands stained red",
]
SURVIVOR_TYPES_ZH = [
    "紧握棒球棍的女人，眼神四处游移",
    "手臂缠着绷带的少年，在发抖",
    "拿着猎枪的老人，面颊凹陷",
    "一对不超过十二岁的兄妹",
    "穿着破烂军服的士兵，目光空洞",
    "还穿着手术服的护士，双手染红",
]

HAZARD_TYPES = ["collapsed overpass", "gas leak from a ruptured pipe", "flooded basement with sparking wires", "field of broken glass and tangled wire"]
HAZARD_TYPES_ZH = ["坍塌的立交桥", "破裂管道的燃气泄漏", "电线冒火花的积水地下室", "碎玻璃和铁丝纠缠的地带"]
SILENCE_DESCS = ["almost worse", "like a held breath", "suspicious", "fragile", "like the world forgot you"]
SILENCE_DESCS_ZH = ["几乎更可怕", "像屏住的呼吸", "令人起疑", "脆弱不堪", "好像世界忘记了你"]
HORDE_SIZES = ["dozens", "at least fifty", "hundreds", "an endless column"]
HORDE_SIZES_ZH = ["几十只", "至少五十只", "数以百计", "无尽的队列"]
BARRIER_TYPES = ["door", "barricade", "window shutter", "fire escape gate"]
BARRIER_TYPES_ZH = ["门", "路障", "窗板", "消防梯门"]
DREAM_QUALITIES = ["too real", "like a memory you can't place", "like drowning in warm water", "like the world before"]
DREAM_QUALITIES_ZH = ["太真实了", "像一段无法定位的记忆", "像溺在温水中", "像末日之前的世界"]
NOISE_TYPES = ["scream", "gunshot", "scraping sound", "child crying", "glass shattering"]
NOISE_TYPES_ZH = ["尖叫", "枪声", "刮擦声", "孩子的哭声", "玻璃破碎声"]
DIRECTIONS = ["below", "to the east", "above you", "very close", "far away but echoing"]
DIRECTIONS_ZH = ["下方", "东边", "头顶上方", "很近的地方", "远处但回声阵阵"]


class EventSystem:
    def __init__(self):
        self.triggered_story = set()

    def generate_event(self, state: GameState) -> dict:
        events = []
        zh = Config.LANG == "zh"

        # Check story triggers
        for evt in EVENT_POOL["story"]:
            if (evt.get("trigger_day") == state.world.day
                    and evt["id"] not in self.triggered_story
                    and state.world.time_of_day == TimeOfDay.DAWN):
                self.triggered_story.add(evt["id"])
                return {
                    "id": evt["id"],
                    "title": evt.get("title_zh", evt["title"]) if zh else evt["title"],
                    "description": evt.get("template_zh", evt["template"]) if zh else evt["template"],
                    "is_story": True,
                }

        # Pick pool based on time
        pool_key = "night" if state.world.time_of_day == TimeOfDay.NIGHT else "exploration"
        pool = [e for e in EVENT_POOL[pool_key] if e.get("min_day", 0) <= state.world.day]

        if not pool:
            if zh:
                return {"id": "nothing", "title": "寂静", "description": "什么都没发生。不知为何，这更令人不安。", "is_story": False}
            return {"id": "nothing", "title": "Silence", "description": "Nothing happens. Somehow that's worse.", "is_story": False}

        chosen = random.choices(pool, weights=[e["weight"] for e in pool], k=1)[0]
        description = self._fill_template(chosen, state)

        return {
            "id": chosen["id"],
            "title": chosen.get("title_zh", chosen["title"]) if zh else chosen["title"],
            "description": description,
            "is_story": False,
        }

    def _fill_template(self, event: dict, state: GameState) -> str:
        zh = Config.LANG == "zh"
        template = event.get("template_zh", event["template"]) if zh else event["template"]

        zt = random.choice(ZOMBIE_TYPES_ZH if zh else ZOMBIE_TYPES)
        loc = LOCATIONS.get(state.world.location, {})
        loot = loc.get("loot_table", [])

        if zh:
            item_hint_val = f"看起来像是{_item_name(random.choice(loot))}的东西" if loot else "废墟中的什么东西"
            door_hint_val = "你的开锁工具也许能派上用场" if "lockpick set" in state.player.inventory else "一套开锁工具可能有用"
        else:
            item_hint_val = f"what looks like a {random.choice(loot)}" if loot else "something in the rubble"
            door_hint_val = "Your lockpick set could open this" if "lockpick set" in state.player.inventory else "A lockpick set might help"

        replacements = {
            "zombie_type": zt[0],
            "zombie_desc": zt[1],
            "survivor_desc": random.choice(SURVIVOR_TYPES_ZH if zh else SURVIVOR_TYPES),
            "item_hint": item_hint_val,
            "hazard_type": random.choice(HAZARD_TYPES_ZH if zh else HAZARD_TYPES),
            "silence_desc": random.choice(SILENCE_DESCS_ZH if zh else SILENCE_DESCS),
            "horde_size": random.choice(HORDE_SIZES_ZH if zh else HORDE_SIZES),
            "barrier": random.choice(BARRIER_TYPES_ZH if zh else BARRIER_TYPES),
            "dream_quality": random.choice(DREAM_QUALITIES_ZH if zh else DREAM_QUALITIES),
            "noise_type": random.choice(NOISE_TYPES_ZH if zh else NOISE_TYPES),
            "direction": random.choice(DIRECTIONS_ZH if zh else DIRECTIONS),
            "door_hint": door_hint_val,
        }

        for key, val in replacements.items():
            template = template.replace(f"{{{key}}}", val)

        return template

    def to_dict(self):
        return {"triggered_story": list(self.triggered_story)}

    @classmethod
    def from_dict(cls, data):
        es = cls()
        es.triggered_story = set(data.get("triggered_story", []))
        return es


# ══════════════════════════════════════════════════════════════════
# RULES ENGINE
# ══════════════════════════════════════════════════════════════════

class RulesEngine:

    @staticmethod
    def tick_survival(player: Player, weather: Weather = Weather.CLEAR):
        """Per-turn resource drain. Weather affects drain rates."""
        hunger_drain = random.randint(4, 7)
        thirst_drain = random.randint(5, 9)
        stamina_drain = random.randint(3, 6)

        # Weather modifiers
        if weather == Weather.RAIN:
            thirst_drain = max(1, thirst_drain - 2)  # Rain helps thirst slightly
            stamina_drain += 2  # But drains stamina (cold, wet)
        elif weather == Weather.STORM:
            stamina_drain += 3  # Storms are exhausting
            player.morale -= 2  # Demoralizing
        elif weather == Weather.FOG:
            pass  # Fog: no survival effect, but affects threat (handled in advance_time)

        player.hunger = max(0, player.hunger - hunger_drain)
        player.thirst = max(0, player.thirst - thirst_drain)
        player.stamina = max(0, player.stamina - stamina_drain)

        if player.hunger <= 0:
            player.health -= random.randint(5, 10)
        if player.thirst <= 0:
            player.health -= random.randint(8, 15)
        if player.stamina <= 0:
            player.morale -= 5

        # Infection ticks
        if player.infection > 0:
            player.infection = min(100, player.infection + random.randint(1, 3))

        # Morale consequences
        if player.morale <= 10:
            # Despair: lose health slowly, refuse to eat/drink efficiently
            player.health -= random.randint(1, 3)
        elif player.morale <= 25:
            # Demoralized: stamina drains faster
            player.stamina = max(0, player.stamina - 2)
        elif player.morale >= 80:
            # High spirits: slight stamina recovery
            player.stamina = min(100, player.stamina + 1)

        # Morale bounds
        player.morale = max(0, min(100, player.morale))

    @staticmethod
    def resolve_combat(player: Player, threat_level: int) -> dict:
        """Returns combat result dict."""
        weapon_bonus = 0
        weapon_noise = 0
        if player.equipped_weapon and player.equipped_weapon in ITEMS:
            weapon_bonus = ITEMS[player.equipped_weapon].get("damage", 0)
            weapon_noise = ITEMS[player.equipped_weapon].get("noise", 0)

        roll = random.randint(1, 20)
        # Morale affects combat effectiveness
        morale_mod = -2 if player.morale <= 20 else (1 if player.morale >= 75 else 0)
        player_power = roll + player.skills["combat"] * 3 + weapon_bonus // 5 + morale_mod
        enemy_power = threat_level * 3 + random.randint(1, 10)

        result = {"noise_generated": weapon_noise}

        if player_power > enemy_power + 5:
            # Clean win
            result["outcome"] = "clean_win"
            result["damage_taken"] = 0
            result["narrative_hint"] = "You dispatched it efficiently."
            player.kills += 1
            player.skills["combat"] = min(10, player.skills["combat"] + 0.2)
        elif player_power > enemy_power:
            # Messy win
            dmg = random.randint(5, 15)
            player.health -= dmg
            result["outcome"] = "messy_win"
            result["damage_taken"] = dmg
            result["narrative_hint"] = f"You took it down, but not before it got a hit in. (-{dmg} HP)"
            player.kills += 1
            if random.random() < 0.15:
                player.infection += random.randint(5, 15)
                result["narrative_hint"] += " You feel a burning sensation where it scratched you."
        elif player_power > enemy_power - 5:
            # Narrow escape
            dmg = random.randint(15, 30)
            player.health -= dmg
            result["outcome"] = "narrow_escape"
            result["damage_taken"] = dmg
            result["narrative_hint"] = f"You barely got away. (-{dmg} HP)"
            if random.random() < 0.3:
                player.infection += random.randint(10, 25)
                result["narrative_hint"] += " Its teeth grazed your skin. That's not good."
        else:
            # Bad outcome
            dmg = random.randint(25, 45)
            player.health -= dmg
            result["outcome"] = "defeat"
            result["damage_taken"] = dmg
            result["narrative_hint"] = f"It overpowered you. (-{dmg} HP)"
            if random.random() < 0.5:
                player.infection += random.randint(15, 35)
                result["narrative_hint"] += " You've been bitten."

        return result

    @staticmethod
    def resolve_stealth(player: Player, threat_level: int, weather: Weather = Weather.CLEAR) -> dict:
        roll = random.randint(1, 20)
        stealth_power = roll + player.skills["stealth"] * 3
        # Fog and rain provide stealth bonuses
        if weather == Weather.FOG:
            stealth_power += 3
        elif weather in (Weather.RAIN, Weather.STORM):
            stealth_power += 2  # Noise cover

        if stealth_power > threat_level * 2 + 5:
            player.skills["stealth"] = min(10, player.skills["stealth"] + 0.2)
            return {"outcome": "undetected", "narrative_hint": "You slipped past without a sound."}
        elif stealth_power > threat_level * 2:
            return {"outcome": "close_call", "narrative_hint": "It almost saw you. Your heart hammers in your chest."}
        else:
            return {"outcome": "detected", "narrative_hint": "It spotted you. No choice now but to run or fight."}

    @staticmethod
    def use_item(player: Player, item_name: str) -> dict:
        if item_name not in player.inventory:
            return {"success": False, "message": "You don't have that."}

        item = ITEMS.get(item_name)
        if not item:
            return {"success": False, "message": "Unknown item."}

        result = {"success": True, "message": "", "consumed": True}

        if item["type"] == "food":
            restore = item.get("hunger_restore", 0)
            player.hunger = min(100, player.hunger + restore)
            result["message"] = f"You eat the {item_name}. (+{restore} hunger)"
        elif item["type"] == "water":
            restore = item.get("thirst_restore", 0)
            player.thirst = min(100, player.thirst + restore)
            result["message"] = f"You drink the {item_name}. (+{restore} thirst)"
        elif item["type"] == "medical":
            heal = item.get("heal", 0)
            inf_reduce = item.get("infection_reduce", 0)
            inf_risk = item.get("infection_risk", 0)
            morale_r = item.get("morale_restore", 0)
            player.health = min(100, player.health + heal)
            player.infection = max(0, player.infection - inf_reduce)
            player.morale = min(100, player.morale + morale_r)
            if inf_risk > 0 and random.random() < inf_risk / 100:
                player.infection += 5
                result["message"] = f"Used {item_name}. (+{heal} HP) But the wound might be contaminated..."
            else:
                msg = f"Used {item_name}."
                if heal: msg += f" (+{heal} HP)"
                if inf_reduce: msg += f" (-{inf_reduce} infection)"
                if morale_r: msg += f" (+{morale_r} morale)"
                result["message"] = msg
        elif item["type"] == "weapon":
            player.equipped_weapon = item_name
            result["message"] = f"You equip the {item_name}."
            result["consumed"] = False
        else:
            result["message"] = f"You're not sure how to use {item_name} right now."
            result["consumed"] = False

        if result["consumed"] and item_name in player.inventory:
            player.inventory.remove(item_name)

        return result

    @staticmethod
    def check_game_over(state: GameState) -> GameOver:
        if state.player.health <= 0:
            return GameOver.DEAD
        if state.player.infection >= 100:
            return GameOver.INFECTED
        # Win: reach Evacuation Zone on day 14 (dusk/night) or day 15 (dawn)
        if state.world.location == "Evacuation Zone":
            if (state.world.day == 15 and state.world.time_of_day == TimeOfDay.DAWN):
                return GameOver.ESCAPED
            if (state.world.day == 14 and state.world.time_of_day in (TimeOfDay.DUSK, TimeOfDay.NIGHT)):
                return GameOver.ESCAPED
            if state.world.day >= 15 and state.world.time_of_day != TimeOfDay.DAWN:
                # Missed the helicopter
                pass
        # Day 16+: too late, helicopter left (forced death by despair)
        if state.world.day > 15:
            state.player.morale = 0
            state.player.health -= 50  # Despair: missed evacuation
        return GameOver.NONE

    @staticmethod
    def advance_time(world: World):
        order = [TimeOfDay.DAWN, TimeOfDay.DAY, TimeOfDay.DUSK, TimeOfDay.NIGHT]
        idx = order.index(world.time_of_day)
        if idx < len(order) - 1:
            world.time_of_day = order[idx + 1]
        else:
            world.time_of_day = TimeOfDay.DAWN
            world.day += 1
            # Weather change
            world.weather = random.choice(list(Weather))

        # Threat fluctuation
        loc = LOCATIONS.get(world.location, {})
        base = loc.get("base_threat", 3)
        time_mod = 2 if world.time_of_day == TimeOfDay.NIGHT else (1 if world.time_of_day == TimeOfDay.DUSK else 0)
        day_mod = min(world.day // 3, 3)
        # Weather affects threat: fog reduces visibility (higher threat), storms scatter zombies (lower)
        weather_mod = 0
        if world.weather == Weather.FOG:
            weather_mod = 1  # Harder to see threats coming
        elif world.weather == Weather.STORM:
            weather_mod = -1  # Thunder scatters zombies
        world.threat_level = min(10, max(0, base + time_mod + day_mod + weather_mod + random.randint(-1, 1)))
        world.noise_level = max(0, world.noise_level - 1)


# ══════════════════════════════════════════════════════════════════
# LLM INTERFACE
# ══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_EN = """You narrate a zombie text adventure. Second person, present tense. Be concise.

RULES:
1. The EVENT is the most important part. Your narrative MUST describe what the event says.
2. If a player action is given, describe the result FIRST, then the event.
3. Describe concrete things the player sees, hears, or can interact with.
4. Do NOT assume the player picks up, grabs, or uses anything. Choices should be actions like "search", "move to", "hide", "talk to", not "pick up X".
5. Choices must be realistic actions a person could actually do in the scene.
6. Write 50-100 words, then end with exactly 3 choices:

[A] action
[B] action
[C] action"""

SYSTEM_PROMPT_ZH = """你是丧尸文字冒险的叙事者。第二人称，现在时。简洁有力。必须用中文。

规则：
1. 事件是最重要的部分。你的叙述必须描写事件中发生的事。
2. 如果给了玩家行动，先描述行动结果，再描述事件。
3. 描写玩家看到、听到、能互动的具体事物。
4. 不要假设玩家拿起或使用任何东西。选项应该是"搜索""前往""躲藏""交谈"等动作，不要写"拿起X"。
5. 选项必须是场景中一个人真的能做的合理行动。
6. 写50-100字叙事，然后给恰好3个选项：

[A] 行动
[B] 行动
[C] 行动"""


def _get_system_prompt() -> str:
    return SYSTEM_PROMPT_ZH if Config.LANG == "zh" else SYSTEM_PROMPT_EN


def build_prompt(state: GameState, event: dict,
                 action_context: str = "", prev_narrative: str = "",
                 memory_snippets: str = "",
                 revisit_memory: str = "",
                 lore_snippets: str = "") -> str:
    """Build prompt with labeled structure for small (1-3B) models.

    Labels help the model produce structured output (proper [A][B][C]).
    No old narrative is included — it bleeds into new output.
    Action goes first so the model addresses it immediately.
    """
    p = state.player
    w = state.world
    loc = LOCATIONS.get(w.location, {})
    zh = Config.LANG == "zh"

    loc_desc = loc.get("desc_zh", loc.get("description", "")) if zh else loc.get("description", "")
    weapon_str = _item_name(p.equipped_weapon) if p.equipped_weapon else t("bare hands")

    # ── Player state: graded (not binary) so the model can gauge severity.
    # Small models ignore status tags like "badly wounded" — they need the
    # actual number AND a severity label AND a body-directive.
    state_parts = []
    if zh:
        if p.health < 100:
            sev = "重伤" if p.health < 30 else ("受伤" if p.health < 70 else "")
            state_parts.append(f"HP {p.health}/100" + (f"（{sev}）" if sev else ""))
        if p.hunger < 100:
            sev = "严重饥饿" if p.hunger < 20 else ("饥饿" if p.hunger < 50 else "")
            state_parts.append(f"饱食 {p.hunger}/100" + (f"（{sev}）" if sev else ""))
        if p.thirst < 100:
            sev = "脱水" if p.thirst < 20 else ("口渴" if p.thirst < 50 else "")
            state_parts.append(f"水分 {p.thirst}/100" + (f"（{sev}）" if sev else ""))
        if p.stamina < 60:
            sev = "精疲力竭" if p.stamina < 20 else "疲惫"
            state_parts.append(f"体力 {p.stamina}/100（{sev}）")
        if p.infection > 0:
            sev = "感染恶化" if p.infection >= 40 else "感染中"
            state_parts.append(f"感染 {p.infection}%（{sev}）")
        if p.morale < 40:
            sev = "崩溃边缘" if p.morale < 20 else "士气低迷"
            state_parts.append(f"士气 {p.morale}/100（{sev}）")
    else:
        if p.health < 100:
            sev = "badly wounded" if p.health < 30 else ("wounded" if p.health < 70 else "")
            state_parts.append(f"HP {p.health}/100" + (f" ({sev})" if sev else ""))
        if p.hunger < 100:
            sev = "starving" if p.hunger < 20 else ("hungry" if p.hunger < 50 else "")
            state_parts.append(f"food {p.hunger}/100" + (f" ({sev})" if sev else ""))
        if p.thirst < 100:
            sev = "dehydrated" if p.thirst < 20 else ("thirsty" if p.thirst < 50 else "")
            state_parts.append(f"water {p.thirst}/100" + (f" ({sev})" if sev else ""))
        if p.stamina < 60:
            sev = "exhausted" if p.stamina < 20 else "tired"
            state_parts.append(f"stamina {p.stamina}/100 ({sev})")
        if p.infection > 0:
            sev = "infection worsening" if p.infection >= 40 else "infected"
            state_parts.append(f"infection {p.infection}% ({sev})")
        if p.morale < 40:
            sev = "breaking down" if p.morale < 20 else "low morale"
            state_parts.append(f"morale {p.morale}/100 ({sev})")
    state_str = " | ".join(state_parts)

    # ── Inventory always visible so the model knows what the player carries.
    # This is the single biggest lever: without it the model never has the
    # player eat food they're holding, use antibiotics for infection, etc.
    inv_str = ""
    if p.inventory:
        inv_names = [_item_name(k) for k in p.inventory]
        # dedupe-with-count if duplicates exist
        from collections import Counter
        counts = Counter(inv_names)
        parts = [(n if c == 1 else f"{n}×{c}") for n, c in counts.items()]
        sep = "、" if zh else ", "
        if zh:
            inv_str = f"背包({len(p.inventory)}/{p.max_inventory}): {sep.join(parts)}"
        else:
            inv_str = f"Pack ({len(p.inventory)}/{p.max_inventory}): {sep.join(parts)}"

    # ── Available relief hints — let the model connect bad state ↔ carried items.
    relief_hints = []
    has_food = any(ITEMS.get(k, {}).get("type") == "food" for k in p.inventory)
    has_water = any(ITEMS.get(k, {}).get("type") == "water" for k in p.inventory)
    has_medical = any(ITEMS.get(k, {}).get("type") == "medical" for k in p.inventory)
    has_antiinfect = any(k in ("antibiotics", "experimental antiviral") for k in p.inventory)
    if zh:
        if p.hunger < 40 and has_food:       relief_hints.append("背包里有食物")
        if p.thirst < 40 and has_water:      relief_hints.append("背包里有水")
        if p.health < 50 and has_medical:    relief_hints.append("背包里有医疗用品")
        if p.infection >= 25 and has_antiinfect: relief_hints.append("背包里有抗感染药")
    else:
        if p.hunger < 40 and has_food:       relief_hints.append("food in pack")
        if p.thirst < 40 and has_water:      relief_hints.append("water in pack")
        if p.health < 50 and has_medical:    relief_hints.append("medical supplies in pack")
        if p.infection >= 25 and has_antiinfect: relief_hints.append("anti-infection meds in pack")

    # ── Decide whether to emit the "body-directive" instruction line.
    compromised = (p.health < 70 or p.hunger < 40 or p.thirst < 40
                   or p.stamina < 30 or p.infection >= 20 or p.morale < 30)

    loc_name = _loc_name(w.location)

    # Concrete detail hint — one random specific thing to anchor the scene
    # These are small, concrete objects/sounds, not vague atmosphere
    details_en = [
        "a child's shoe lies in the doorway", "a car alarm goes off two blocks away",
        "a calendar on the wall shows last month", "a shopping cart blocks the path",
        "graffiti on the wall reads HELP US", "a fire escape ladder hangs loose",
        "a cat watches from a windowsill", "a bicycle lies twisted on the ground",
        "a payphone receiver dangles off the hook", "a vending machine hums with power",
        "broken glass crunches underfoot", "a newspaper flutters in the wind",
        "a backpack sits abandoned by the curb", "a water pipe drips from the ceiling",
        "tire tracks in the mud lead south", "a flashlight blinks on and off nearby",
    ]
    details_zh = [
        "门口躺着一只童鞋", "两条街外传来汽车警报声",
        "墙上的日历停在上个月", "一辆购物车挡住了路",
        "墙上的涂鸦写着'救救我们'", "消防梯松松垮垮地挂着",
        "一只猫从窗台上注视着你", "一辆自行车扭曲地倒在地上",
        "公用电话的听筒悬挂着", "一台自动售货机还在嗡嗡运转",
        "脚下碎玻璃嘎吱作响", "一张报纸在风中翻飞",
        "路边有一个被遗弃的背包", "天花板上的水管在滴水",
        "泥地里的轮胎痕迹朝南延伸", "附近有手电筒一闪一闪",
    ]

    detail = random.choice(details_zh if zh else details_en)

    is_story = event.get("is_story", False)

    lines = []
    if zh:
        if action_context:
            lines.append(f"玩家行动: {action_context}")
        if state_str:
            lines.append(f"玩家状态: {state_str}")
        if inv_str:
            lines.append(inv_str)
        if relief_hints:
            lines.append(f"可用资源: {'，'.join(relief_hints)}（玩家可能选择使用）")
        lines.append(f"场景: {loc_name}——{loc_desc}")
        lines.append(f"第{w.day}天，{t(w.time_of_day.value)}，{t(w.weather.value)}。威胁{w.threat_level}/10。武器: {weapon_str}。")
        lines.append(f"细节: {detail}。")
        if memory_snippets:
            lines.append("往事回响（之前经历过的片段，保持前后一致）:")
            lines.append(memory_snippets)
        if lore_snippets:
            lines.append("场景参考（可以借鉴其中的意象和词汇，但不要照抄原句）:")
            lines.append(lore_snippets)
        lines.append(f"事件: {event['description']}")
        # Strong directive for revisit: same location as a past memory.
        # Small models respond better to an imperative placed close to the generation point.
        if revisit_memory:
            lines.append(
                f"重要：这不是玩家第一次来这里。上次：{revisit_memory}。"
                f"叙述开头必须点出'再次'，可以顺带呼应上次在这里发生的事。"
            )
        if is_story:
            lines.append("重要：这是关键剧情事件，你必须围绕这个事件展开叙述。")
        # Body-directive: force the narrative to physically reflect current state.
        # Without this, small models write the scene as if the player were fine.
        if compromised:
            lines.append(
                "重要：叙述必须体现玩家当前的身体/精神状态——根据「玩家状态」里的标签，"
                "让动作带上相应的吃力、颤抖、呼吸粗重、伤口灼痛、视线模糊、脚步发软、"
                "或心理动摇等具体反应。不能写成健康状态。"
            )
        if action_context:
            lines.append("先描述玩家行动的结果，再描述事件。")
    else:
        if action_context:
            lines.append(f"Player action: {action_context}")
        if state_str:
            lines.append(f"Player status: {state_str}")
        if inv_str:
            lines.append(inv_str)
        if relief_hints:
            lines.append(f"Available resources: {', '.join(relief_hints)} (the player may choose to use them)")
        lines.append(f"Scene: {w.location} — {loc_desc}")
        lines.append(f"Day {w.day}, {w.time_of_day.value}, {w.weather.value}. Threat {w.threat_level}/10. Weapon: {weapon_str}.")
        lines.append(f"Detail: {detail}.")
        if memory_snippets:
            lines.append("Past echoes (prior events — keep continuity):")
            lines.append(memory_snippets)
        if lore_snippets:
            lines.append("Scene reference (borrow imagery and vocabulary — do not copy verbatim):")
            lines.append(lore_snippets)
        lines.append(f"Event: {event['description']}")
        if revisit_memory:
            lines.append(
                f"IMPORTANT: The player has been here before. Last time: {revisit_memory}. "
                f"The opening must use 'again'; feel free to briefly echo what happened here."
            )
        if is_story:
            lines.append("IMPORTANT: This is a key story event. Your narrative MUST focus on this event.")
        if compromised:
            lines.append(
                "IMPORTANT: The narrative MUST physically reflect the player's current state — "
                "use labored movements, shaking, heavy breathing, burning wounds, blurred vision, "
                "weak legs, or mental fraying depending on the Player status tags. "
                "Do NOT write the scene as if the player were healthy."
            )
        if action_context:
            lines.append("Start by describing what happened when the player did this.")

    return "\n".join(lines)


def _print_msg(console, text, style=None):
    """Helper to print via Rich console or plain print."""
    if console and HAS_RICH and style:
        console.print(f"  [{style}]{text}[/]")
    elif console and HAS_RICH:
        console.print(f"  {text}")
    else:
        print(f"  {text}")


def _download_file(url: str, dest: str, console=None, label: str = ""):
    """Download a file with progress display."""
    _print_msg(console, f"Downloading {label or url.split('/')[-1]}...")
    resp = requests.get(url, stream=True, timeout=30)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    downloaded = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
            downloaded += len(chunk)
            if total > 0:
                pct = downloaded * 100 // total
                mb = downloaded / 1_000_000
                total_mb = total / 1_000_000
                print(f"\r  [{pct:3d}%] {mb:.0f} / {total_mb:.0f} MB", end="", flush=True)
    print()


class RuntimeManager:
    """Manages downloading llama-server binary and GGUF model."""

    # ── Server binary ──

    @staticmethod
    def is_server_installed() -> bool:
        return os.path.isfile(Config.LLAMA_SERVER_EXE)

    @staticmethod
    def _detect_nvidia_gpu() -> bool:
        """Check if an NVIDIA GPU is available."""
        try:
            result = subprocess.run(
                ["nvidia-smi"], capture_output=True, timeout=5,
                creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def download_server(console=None) -> bool:
        """Download the llama-server binary from GitHub releases."""
        has_gpu = RuntimeManager._detect_nvidia_gpu()
        if has_gpu:
            _print_msg(console, "NVIDIA GPU detected — downloading CUDA build...", "bold yellow")
            zip_names = [Config.LLAMA_CPP_CUDA_ZIP, Config.LLAMA_CPP_CUDART_ZIP]
        else:
            _print_msg(console, "No NVIDIA GPU — downloading CPU build...", "bold yellow")
            zip_names = [Config.LLAMA_CPP_CPU_ZIP]

        os.makedirs(Config.RUNTIME_DIR, exist_ok=True)

        try:
            for zip_name in zip_names:
                url = f"{Config.LLAMA_CPP_RELEASE_URL}/{zip_name}"
                zip_path = os.path.join(Config.RUNTIME_DIR, zip_name)
                _download_file(url, zip_path, console, zip_name)

                # Extract
                _print_msg(console, f"Extracting {zip_name}...")
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(Config.RUNTIME_DIR)
                os.remove(zip_path)

            if not os.path.isfile(Config.LLAMA_SERVER_EXE):
                _print_msg(console, "✗ llama-server.exe not found after extraction", "bold red")
                return False

            _print_msg(console, "✓ llama-server installed!", "bold green")
            return True
        except Exception as e:
            _print_msg(console, f"✗ Download failed: {e}", "bold red")
            return False

    # ── Model ──

    @staticmethod
    def is_model_downloaded() -> bool:
        return os.path.isfile(Config.GGUF_MODEL_PATH)

    @staticmethod
    def get_model_size_str() -> str:
        if not os.path.isfile(Config.GGUF_MODEL_PATH):
            return "not downloaded"
        size = os.path.getsize(Config.GGUF_MODEL_PATH)
        if size > 1_000_000_000:
            return f"{size / 1_000_000_000:.2f} GB"
        return f"{size / 1_000_000:.0f} MB"

    @staticmethod
    def download_model(console=None) -> bool:
        """Download the GGUF model from HuggingFace."""
        _print_msg(console, f"Downloading AI model: {Config.GGUF_FILENAME} (~1.05 GB)...", "bold yellow")
        try:
            from huggingface_hub import hf_hub_download
            os.makedirs(Config.MODEL_DIR, exist_ok=True)
            hf_hub_download(
                repo_id=Config.HF_REPO_ID,
                filename=Config.GGUF_FILENAME,
                local_dir=Config.MODEL_DIR,
            )
            _print_msg(console, "✓ Model downloaded!", "bold green")
            return True
        except ImportError:
            # Fallback: direct download without huggingface_hub
            _print_msg(console, "huggingface-hub not found, using direct download...", "dim")
            try:
                url = f"https://huggingface.co/{Config.HF_REPO_ID}/resolve/main/{Config.GGUF_FILENAME}"
                _download_file(url, Config.GGUF_MODEL_PATH, console, Config.GGUF_FILENAME)
                _print_msg(console, "✓ Model downloaded!", "bold green")
                return True
            except Exception as e:
                _print_msg(console, f"✗ Download failed: {e}", "bold red")
                return False
        except Exception as e:
            _print_msg(console, f"✗ Download failed: {e}", "bold red")
            return False

    # ── Server process ──

    _server_process = None

    _server_log_path = os.path.join(_BASE_DIR, "llama_server.log")

    @classmethod
    def start_server(cls, console=None) -> bool:
        """Start llama-server as a background subprocess."""
        if cls._is_server_running():
            _print_msg(console, "✓ Server already running", "bold green")
            return True

        _print_msg(console, "Starting llama-server...", "dim")

        cmd = [
            Config.LLAMA_SERVER_EXE,
            "--model", Config.GGUF_MODEL_PATH,
            "--host", Config.SERVER_HOST,
            "--port", str(Config.SERVER_PORT),
            "--ctx-size", str(Config.N_CTX),
            "--n-gpu-layers", str(Config.N_GPU_LAYERS),
        ]

        _print_msg(console, f"Command: {' '.join(cmd)}", "dim")

        try:
            # Write server output to log file for debugging
            cls._log_file = open(cls._server_log_path, "w", encoding="utf-8")
            cls._server_process = subprocess.Popen(
                cmd,
                stdout=cls._log_file,
                stderr=subprocess.STDOUT,
                creationflags=0x00000008 if os.name == "nt" else 0,  # DETACHED_PROCESS
            )
            # Register cleanup on exit
            atexit.register(cls.stop_server)

            # Wait for server to be ready (up to 60 seconds)
            _print_msg(console, "Waiting for model to load...", "dim")
            for i in range(120):
                time.sleep(0.5)
                if cls._is_server_running():
                    _print_msg(console, "✓ Server ready!", "bold green")
                    return True
                # Check if process died
                if cls._server_process.poll() is not None:
                    _print_msg(console, "✗ Server process exited unexpectedly", "bold red")
                    # Show last few lines of log
                    cls._log_file.close()
                    try:
                        with open(cls._server_log_path, "r", encoding="utf-8") as f:
                            log_tail = f.read()[-500:]
                        _print_msg(console, f"Server log:\n{log_tail}", "dim")
                    except Exception:
                        pass
                    return False
                if (i + 1) % 10 == 0:
                    _print_msg(console, f"  Still loading... ({(i+1)//2}s)", "dim")

            _print_msg(console, "✗ Server failed to start (timeout 60s)", "bold red")
            return False
        except Exception as e:
            _print_msg(console, f"✗ Failed to start server: {e}", "bold red")
            return False

    @classmethod
    def stop_server(cls):
        """Stop the llama-server subprocess."""
        if cls._server_process and cls._server_process.poll() is None:
            cls._server_process.terminate()
            try:
                cls._server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls._server_process.kill()
            cls._server_process = None
        if hasattr(cls, '_log_file') and cls._log_file and not cls._log_file.closed:
            cls._log_file.close()

    @staticmethod
    def _is_server_running() -> bool:
        """Check if the llama-server is responding."""
        try:
            resp = requests.get(f"{Config.SERVER_URL}/health", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    # ── Diagnostics ──

    @staticmethod
    def full_diagnostics() -> str:
        lines = ["─── Runtime Diagnostics ───"]

        # Server binary
        if RuntimeManager.is_server_installed():
            lines.append(f"✓ llama-server installed at: {Config.RUNTIME_DIR}")
        else:
            lines.append("✗ llama-server NOT installed")
            lines.append("  → Will download automatically on first game start")

        # GPU
        if RuntimeManager._detect_nvidia_gpu():
            lines.append("✓ NVIDIA GPU detected (CUDA acceleration)")
        else:
            lines.append("△ No NVIDIA GPU — using CPU mode")

        # Model
        if RuntimeManager.is_model_downloaded():
            lines.append(f"✓ Model downloaded ({RuntimeManager.get_model_size_str()})")
        else:
            lines.append("✗ Model NOT downloaded")
            lines.append("  → Will download automatically on first game start")

        # Server status
        if RuntimeManager._is_server_running():
            lines.append(f"✓ Server running at {Config.SERVER_URL}")
        else:
            lines.append(f"△ Server not running (starts with game)")

        return "\n".join(lines)


class LLMClient:
    """Communicates with llama-server via OpenAI-compatible HTTP API."""

    def _build_payload(self, system: str, prompt: str, stream: bool = False) -> dict:
        prompt_with_flag = prompt + "\n/no_think"
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt_with_flag},
            ],
            "max_tokens": Config.LLM_MAX_TOKENS,
            "temperature": Config.LLM_TEMPERATURE,
            "top_p": Config.LLM_TOP_P,
        }
        if stream:
            payload["stream"] = True
        return payload

    @staticmethod
    def _fallback(error_msg: str = "") -> str:
        if Config.LANG == "zh":
            base = "寂静持续蔓延。你的电台嘶嘶作响，但什么也没收到。"
            if error_msg:
                base = f"寂静持续蔓延。你的思绪飘散了…（{error_msg}）"
            return f"{base}\n\n[A] 再试一次\n[B] 四处看看\n[C] 等待"
        base = "The silence stretches on. Your radio crackles but finds nothing."
        if error_msg:
            base = f"The silence stretches on. Your mind drifts... ({error_msg})"
        return f"{base}\n\n[A] Try again\n[B] Look around\n[C] Wait"

    def generate_stream(self, system: str, prompt: str, on_token=None) -> str:
        """Stream tokens from the LLM. Calls on_token(str) for each chunk.
        Returns the full accumulated text."""
        try:
            payload = self._build_payload(system, prompt, stream=True)
            resp = requests.post(
                f"{Config.SERVER_URL}/v1/chat/completions",
                json=payload,
                timeout=120,
                stream=True,
            )
            resp.raise_for_status()
            # Force UTF-8 decoding — llama-server may not set charset header,
            # causing requests to default to latin-1 and garble CJK text
            resp.encoding = "utf-8"

            full_text = ""
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]  # strip "data: "
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_text += token
                        if on_token:
                            on_token(token)
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue

            content = full_text.strip()
            if content:
                return content

            # Empty stream — try reasoning extraction fallback
            return self._fallback()

        except requests.ConnectionError:
            return self._fallback()
        except Exception as e:
            return self._fallback(f"LLM error: {e}")

    def generate(self, system: str, prompt: str) -> str:
        """Non-streaming generate (used for repair prompts)."""
        try:
            payload = self._build_payload(system, prompt)
            resp = requests.post(
                f"{Config.SERVER_URL}/v1/chat/completions",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip()

            if not content:
                reasoning = (msg.get("reasoning_content") or "").strip()
                if reasoning:
                    content = self._extract_from_reasoning(reasoning)

            if content:
                return content
            return self._fallback()

        except requests.ConnectionError:
            return self._fallback()
        except Exception as e:
            return self._fallback(f"LLM error: {e}")

    @staticmethod
    def _extract_from_reasoning(reasoning: str) -> str:
        """Try to extract narrative + choices from Qwen3's reasoning output."""
        # Look for quoted narrative or choice patterns in the reasoning
        # The model often drafts its response inside the reasoning block
        lines = reasoning.split("\n")
        # Find lines that look like narrative or choices (e.g., [A], [B], [C])
        narrative_lines = []
        choice_lines = []
        in_draft = False
        for line in lines:
            stripped = line.strip()
            # Detect choice patterns
            if re.match(r'^\[?[A-C]\]?\s*[:.)]\s*.+', stripped, re.IGNORECASE):
                choice_lines.append(stripped)
                in_draft = True
            elif stripped.startswith('"') or in_draft or len(stripped) > 60:
                # Likely narrative text
                clean = stripped.strip('"').strip("'")
                if clean and not clean.startswith(("Okay", "Let me", "I need", "The user", "So ")):
                    narrative_lines.append(clean)
        if narrative_lines or choice_lines:
            result = "\n".join(narrative_lines[-6:])  # last ~6 lines of narrative
            if choice_lines:
                result += "\n\n" + "\n".join(choice_lines[-3:])
            return result.strip()
        return ""


def parse_llm_output(raw: str, state: GameState = None) -> dict:
    """
    Extract narrative and choices from LLM output.
    Handles many format variations that local models produce:
      [A] text, A) text, A. text, A: text, **A** text,
      1. text, 1) text, - text, * text, numbered lists, etc.
    """
    if not raw or not raw.strip():
        fallback_narrative = "世界屏住了呼吸。万物静止。" if Config.LANG == "zh" else "The world holds its breath. Nothing moves."
        return {
            "narrative": fallback_narrative,
            "options": _generate_fallback_choices(state),
            "parse_failed": True,
        }

    options = {}
    narrative = raw.strip()

    # ── Strategy 1: [A] / [B] / [C] (intended format) ──
    pattern1 = r'\[([A-Da-d])\]\s*(.+?)(?=\[[A-Da-d]\]|$)'
    matches = re.findall(pattern1, raw, re.DOTALL)
    if len(matches) >= 2:
        for key, val in matches:
            options[key.upper().strip()] = _clean_choice(val)
        narrative = re.split(r'\[[A-Da-d]\]', raw)[0].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 2: **[A]** or **A** (markdown bold brackets) ──
    pattern2 = r'\*\*\[?([A-Da-d])\]?\*\*[:\s]*(.+?)(?=\*\*\[?[A-Da-d]\]?\*\*|$)'
    matches = re.findall(pattern2, raw, re.DOTALL)
    if len(matches) >= 2:
        for key, val in matches:
            options[key.upper().strip()] = _clean_choice(val)
        narrative = re.split(r'\*\*\[?[A-Da-d]\]?\*\*', raw)[0].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 3: A) text / B) text / C) text ──
    pattern3 = r'(?:^|\n)\s*([A-Da-d])\)\s*(.+?)(?=(?:^|\n)\s*[A-Da-d]\)|$)'
    matches = re.findall(pattern3, raw, re.DOTALL)
    if len(matches) >= 2:
        for key, val in matches:
            options[key.upper().strip()] = _clean_choice(val)
        narrative = re.split(r'(?:^|\n)\s*[A-Da-d]\)', raw)[0].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 4: A. text / B. text / C. text ──
    pattern4 = r'(?:^|\n)\s*([A-Da-d])\.\s+(.+?)(?=(?:^|\n)\s*[A-Da-d]\.\s|$)'
    matches = re.findall(pattern4, raw, re.DOTALL)
    if len(matches) >= 2:
        for key, val in matches:
            options[key.upper().strip()] = _clean_choice(val)
        narrative = re.split(r'(?:^|\n)\s*[A-Da-d]\.\s', raw)[0].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 5: A: text / B: text  or  Option A: text ──
    pattern5 = r'(?:^|\n)\s*(?:Option\s+)?([A-Da-d])[:\-]\s*(.+?)(?=(?:^|\n)\s*(?:Option\s+)?[A-Da-d][:\-]|$)'
    matches = re.findall(pattern5, raw, re.DOTALL | re.IGNORECASE)
    if len(matches) >= 2:
        for key, val in matches:
            options[key.upper().strip()] = _clean_choice(val)
        narrative = re.split(r'(?:^|\n)\s*(?:Option\s+)?[A-Da-d][:\-]', raw, flags=re.IGNORECASE)[0].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 6: Numbered list  1. / 1) / 1: ──
    pattern6 = r'(?:^|\n)\s*([1-4])[.):\-]\s*(.+?)(?=(?:^|\n)\s*[1-4][.):\-]|$)'
    matches = re.findall(pattern6, raw, re.DOTALL)
    if len(matches) >= 2:
        labels = "ABCD"
        for i, (_, val) in enumerate(matches[:4]):
            options[labels[i]] = _clean_choice(val)
        narrative = re.split(r'(?:^|\n)\s*[1-4][.):\-]', raw)[0].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 7: Bullet points  - text / * text (last 3+ bullets) ──
    bullet_pattern = r'(?:^|\n)\s*[-*•]\s+(.+)'
    bullets = re.findall(bullet_pattern, raw)
    if len(bullets) >= 2:
        labels = "ABCD"
        # Take last 3-4 bullets as choices
        choice_bullets = bullets[-min(len(bullets), 4):]
        for i, val in enumerate(choice_bullets):
            options[labels[i]] = _clean_choice(val)
        # Narrative = everything before the first bullet used as a choice
        first_choice = choice_bullets[0]
        idx = raw.rfind(first_choice)
        if idx > 0:
            # Walk back to the bullet marker
            search_area = raw[:idx]
            last_bullet = max(search_area.rfind('\n-'), search_area.rfind('\n*'), search_area.rfind('\n•'))
            if last_bullet > 0:
                narrative = raw[:last_bullet].strip()
        return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── Strategy 8: Last resort — look for any action-like sentences at the end ──
    lines = [l.strip() for l in raw.strip().split('\n') if l.strip()]
    if len(lines) >= 4:
        # Assume last 3 lines might be choices
        potential = lines[-3:]
        # Check if they look like short action sentences (under 80 chars, not too long)
        if all(len(l) < 100 for l in potential) and all(len(l) > 5 for l in potential):
            labels = "ABC"
            for i, line in enumerate(potential):
                # Strip leading markers
                cleaned = re.sub(r'^[\d\-\*•\[\]A-Da-d.):]+\s*', '', line).strip()
                if cleaned:
                    options[labels[i]] = _clean_choice(cleaned)
            if len(options) >= 2:
                narrative = '\n'.join(lines[:-3]).strip()
                return {"narrative": narrative, "options": options, "parse_failed": False}

    # ── All strategies failed → use fallback choices ──
    return {
        "narrative": narrative,
        "options": _generate_fallback_choices(state),
        "parse_failed": True,
    }


def _clean_choice(text: str) -> str:
    """Clean up a parsed choice string."""
    text = text.strip()
    # Take first line only
    text = text.split('\n')[0].strip()
    # Remove trailing punctuation clutter
    text = text.rstrip('.')
    # Remove markdown bold/italic
    text = re.sub(r'\*+', '', text).strip()
    # Remove leading dashes/bullets
    text = re.sub(r'^[-•*]\s*', '', text).strip()
    # Cap length
    if len(text) > 80:
        text = text[:77] + "..."
    return text if text else "Do something"


def _generate_fallback_choices(state: GameState = None) -> dict:
    """Generate context-aware fallback choices based on game state."""
    zh = Config.LANG == "zh"
    if state is None:
        if zh:
            return {"A": "搜索周围区域", "B": "保持警觉，观察四周", "C": "休息，保存体力"}
        return {
            "A": "Search the immediate area",
            "B": "Stay alert and observe",
            "C": "Rest and conserve energy",
        }

    options = {}
    loc = LOCATIONS.get(state.world.location, {})
    connections = loc.get("connections", [])
    p = state.player

    # Choice A: Always an exploration/action option
    if connections:
        target = random.choice(connections)
        options["A"] = f"前往{target}" if zh else f"Head toward {target}"
    else:
        options["A"] = "搜索周围区域" if zh else "Search the surrounding area"

    # Choice B: Context-sensitive
    if p.health < 40 and any(ITEMS.get(i, {}).get("type") == "medical" for i in p.inventory):
        med = next(i for i in p.inventory if ITEMS.get(i, {}).get("type") == "medical")
        options["B"] = f"用{med}包扎伤口" if zh else f"Use your {med} to patch up"
    elif p.hunger < 30 and any(ITEMS.get(i, {}).get("type") == "food" for i in p.inventory):
        food = next(i for i in p.inventory if ITEMS.get(i, {}).get("type") == "food")
        options["B"] = f"吃掉{food}" if zh else f"Eat the {food}"
    elif p.thirst < 30 and any(ITEMS.get(i, {}).get("type") == "water" for i in p.inventory):
        water = next(i for i in p.inventory if ITEMS.get(i, {}).get("type") == "water")
        options["B"] = f"喝掉{water}" if zh else f"Drink the {water}"
    elif state.world.threat_level >= 6:
        options["B"] = "找个藏身处，保持安静" if zh else "Find a hiding spot and stay quiet"
    else:
        options["B"] = "搜刮附近的物资" if zh else "Scavenge for supplies nearby"

    # Choice C: Always a cautious/rest option
    if p.stamina < 30:
        options["C"] = "找个庇护所休息" if zh else "Find shelter and rest"
    elif state.world.time_of_day == TimeOfDay.NIGHT:
        options["C"] = "加固入口，睡一会儿" if zh else "Barricade the entrance and sleep"
    else:
        options["C"] = "待在原地，观察周围" if zh else "Stay put and observe your surroundings"

    return options


REPAIR_PROMPT_EN = """Your previous response did not include action choices in the correct format.
Based on the scene you just described, provide EXACTLY 3 choices in this format:

[A] first action
[B] second action
[C] third action

Only output the three choices. Nothing else."""

REPAIR_PROMPT_ZH = """你之前的回复没有包含正确格式的行动选项。
根据你刚才描述的场景，请提供恰好3个选项，使用以下格式：

[A] 第一个行动
[B] 第二个行动
[C] 第三个行动

只输出三个选项。不要输出其他内容。"""


def _get_repair_prompt() -> str:
    return REPAIR_PROMPT_ZH if Config.LANG == "zh" else REPAIR_PROMPT_EN


# ══════════════════════════════════════════════════════════════════
# DISPLAY / UI
# ══════════════════════════════════════════════════════════════════

class Display:
    def __init__(self):
        if HAS_RICH:
            self.console = Console()
        else:
            self.console = None

    def clear(self):
        os.system('cls' if os.name == 'nt' else 'clear')

    def print_title_screen(self):
        title = r"""
    ██████╗ ███████╗ █████╗ ██████╗     ███████╗████████╗ █████╗ ████████╗██╗ ██████╗
    ██╔══██╗██╔════╝██╔══██╗██╔══██╗    ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔════╝
    ██║  ██║█████╗  ███████║██║  ██║    ███████╗   ██║   ███████║   ██║   ██║██║
    ██║  ██║██╔══╝  ██╔══██║██║  ██║    ╚════██║   ██║   ██╔══██║   ██║   ██║██║
    ██████╔╝███████╗██║  ██║██████╔╝    ███████║   ██║   ██║  ██║   ██║   ██║╚██████╗
    ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝     ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝
        """
        if HAS_RICH:
            self.console.print(title, style="bold red")
            self.console.print(f"              {t('A Zombie Apocalypse Text Adventure')}", style="dim white")
            self.console.print(f"              {t('Powered by Local LLM')}\n", style="dim")
            self.console.print(f"    {t('[1] New Game    [2] Load Game    [3] Settings    [Q] Quit')}\n", style="bold")
        else:
            print(title)
            print(f"              {t('A Zombie Apocalypse Text Adventure')}")
            print(f"              {t('Powered by Local LLM')}\n")
            print(f"    {t('[1] New Game    [2] Load Game    [3] Settings    [Q] Quit')}\n")

    def print_status_bar(self, state: GameState):
        p = state.player
        w = state.world

        def bar(val, max_val=100, length=10):
            filled = int((val / max_val) * length)
            return '█' * filled + '░' * (length - filled)

        def color_val(val, thresholds=(30, 60)):
            if val <= thresholds[0]: return "bold red"
            if val <= thresholds[1]: return "yellow"
            return "green"

        zh = Config.LANG == "zh"
        time_str = t(w.time_of_day.value)
        weather_str = t(w.weather.value)
        weapon_str = p.equipped_weapon or t("bare hands")
        threat_label = t("Threat:")

        if HAS_RICH:
            # Top bar
            header = Text()
            if zh:
                header.append(f" {t('DAY', **{'0': str(w.day)})} ", style="bold white on red")
            else:
                header.append(f" DAY {w.day} ", style="bold white on red")
            header.append(f" {time_str} ", style="bold white on dark_red")
            header.append(f" {weather_str} ", style="dim")
            header.append(f" ☠ {threat_label} {w.threat_level}/10 ", style="bold red" if w.threat_level >= 7 else "yellow" if w.threat_level >= 4 else "green")
            self.console.print(header)

            # Location
            loc_data = LOCATIONS.get(w.location, {})
            loc_name = _loc_name(w.location)
            self.console.print(f" 📍 {loc_name}", style="bold cyan")

            # Stats
            stats = Table(box=None, padding=(0, 1), show_header=False, expand=True)
            stats.add_column(width=25)
            stats.add_column(width=25)
            stats.add_column(width=25)

            if zh:
                stats.add_row(
                    Text(f"❤ 生命 {bar(p.health)} {p.health}", style=color_val(p.health)),
                    Text(f"🍖 饥饿 {bar(p.hunger)} {p.hunger}", style=color_val(p.hunger)),
                    Text(f"💧 口渴 {bar(p.thirst)} {p.thirst}", style=color_val(p.thirst)),
                )
                stats.add_row(
                    Text(f"⚡ 体力 {bar(p.stamina)} {p.stamina}", style=color_val(p.stamina)),
                    Text(f"🧠 士气 {bar(p.morale)} {p.morale}", style=color_val(p.morale)),
                    Text(f"🦠 感染 {bar(p.infection)} {p.infection}", style="bold red" if p.infection > 0 else "green"),
                )
            else:
                stats.add_row(
                    Text(f"❤ HP  {bar(p.health)} {p.health}", style=color_val(p.health)),
                    Text(f"🍖 Fed {bar(p.hunger)} {p.hunger}", style=color_val(p.hunger)),
                    Text(f"💧 H₂O {bar(p.thirst)} {p.thirst}", style=color_val(p.thirst)),
                )
                stats.add_row(
                    Text(f"⚡ Stm {bar(p.stamina)} {p.stamina}", style=color_val(p.stamina)),
                    Text(f"🧠 Mor {bar(p.morale)} {p.morale}", style=color_val(p.morale)),
                    Text(f"🦠 Inf {bar(p.infection)} {p.infection}", style="bold red" if p.infection > 0 else "green"),
                )

            self.console.print(Panel(stats, border_style="dim", padding=0))

            # Weapon & inventory
            inv_line = f"🔪 {_item_name(p.equipped_weapon) if p.equipped_weapon else t('bare hands')}  |  🎒 {len(p.inventory)}/{p.max_inventory}: {', '.join(_item_name(i) for i in p.inventory[:5])}"
            if len(p.inventory) > 5:
                inv_line += f" (+{len(p.inventory) - 5})"
            self.console.print(f" {inv_line}", style="dim")
            self.console.print("─" * 75, style="dim")
        else:
            if zh:
                print(f"\n═══ {t('DAY', **{'0': str(w.day)})} | {time_str} | {weather_str} | {threat_label} {w.threat_level}/10 ═══")
            else:
                print(f"\n═══ DAY {w.day} | {time_str} | {weather_str} | Threat: {w.threat_level}/10 ═══")
            print(f"{'位置' if zh else 'Location'}: {_loc_name(w.location)}")
            if zh:
                print(f"生命: {p.health} | 饥饿: {p.hunger} | 口渴: {p.thirst} | 体力: {p.stamina} | 士气: {p.morale} | 感染: {p.infection}")
            else:
                print(f"HP: {p.health} | Hunger: {p.hunger} | Thirst: {p.thirst} | Stamina: {p.stamina} | Morale: {p.morale} | Infection: {p.infection}")
            print(f"{'武器' if zh else 'Weapon'}: {_item_name(p.equipped_weapon) if p.equipped_weapon else t('bare hands')} | {'物品栏' if zh else 'Inventory'}: {', '.join(_item_name(i) for i in p.inventory) or t('empty')}")
            print("─" * 60)

    def print_narrative(self, text: str):
        if HAS_RICH:
            self.console.print(f"\n{text}\n", style="white")
        else:
            print(f"\n{text}\n")

    def start_narrative_stream(self):
        """Print a newline to begin streaming narrative output."""
        self._stream_buf = ""
        self._stream_choices_started = False
        print()

    def print_token(self, token: str):
        """Print a single token during streaming, suppressing [A][B][C] choices."""
        if self._stream_choices_started:
            return
        # Buffer to detect choice markers that may arrive across tokens
        self._stream_buf += token
        # Check if we've hit a choice marker
        if re.search(r'\[A\]', self._stream_buf):
            # Print everything before the choice marker
            before = re.split(r'\[A\]', self._stream_buf, maxsplit=1)[0]
            if before:
                print(before, end="", flush=True)
            self._stream_choices_started = True
            return
        # Flush buffer but keep last 3 chars (in case [A] spans tokens)
        if len(self._stream_buf) > 3:
            to_print = self._stream_buf[:-3]
            self._stream_buf = self._stream_buf[-3:]
            print(to_print, end="", flush=True)

    def end_narrative_stream(self):
        """Flush remaining buffer and print newline."""
        if not self._stream_choices_started and self._stream_buf:
            print(self._stream_buf, end="", flush=True)
        print("\n")

    def print_choices(self, options: dict):
        if HAS_RICH:
            for key, val in options.items():
                self.console.print(f"  [{key}] {val}", style="bold cyan")
        else:
            for key, val in options.items():
                print(f"  [{key}] {val}")

    def print_system_message(self, text: str):
        if HAS_RICH:
            self.console.print(f"  ⚙ {text}", style="dim yellow")
        else:
            print(f"  >> {text}")

    def print_event_title(self, title: str, is_story: bool = False):
        if HAS_RICH:
            style = "bold red on black" if is_story else "bold yellow"
            self.console.print(f"\n  ▸ {title}", style=style)
        else:
            prefix = "*** " if is_story else ">> "
            print(f"\n{prefix}{title}")

    def print_death_screen(self, state: GameState):
        self.clear()
        zh = Config.LANG == "zh"
        if HAS_RICH:
            self.console.print("\n\n")
            if zh:
                self.console.print("    ╔═══════════════════════════════════╗", style="bold red")
                self.console.print("    ║          你   死   了             ║", style="bold red")
                self.console.print("    ╚═══════════════════════════════════╝", style="bold red")
            else:
                self.console.print("    ╔═══════════════════════════════════╗", style="bold red")
                self.console.print("    ║          Y O U   D I E D         ║", style="bold red")
                self.console.print("    ╚═══════════════════════════════════╝", style="bold red")
            self.console.print(f"\n    {t('Survived {days} days.', days=state.world.day)}", style="dim")
            self.console.print(f"    {t('Zombies killed:')} {state.player.kills}", style="dim")
            self.console.print(f"    {t('People saved:')} {state.player.people_saved}", style="dim")
            self.console.print(f"    {t('People left behind:')} {state.player.people_abandoned}\n", style="dim")
        else:
            print(f"\n\n    ═══ {t('YOU DIED')} ═══")
            print(f"    {t('Survived {days} days.', days=state.world.day)} {t('Zombies killed:')} {state.player.kills}")

    def print_infected_screen(self, state: GameState):
        self.clear()
        zh = Config.LANG == "zh"
        if HAS_RICH:
            self.console.print("\n\n")
            if zh:
                self.console.print("    ╔═══════════════════════════════════════════╗", style="bold green")
                self.console.print("    ║         你   变   异   了                ║", style="bold green")
                self.console.print("    ║   感染吞噬了又一个灵魂。                ║", style="bold green")
                self.console.print("    ╚═══════════════════════════════════════════╝", style="bold green")
            else:
                self.console.print("    ╔═══════════════════════════════════════════╗", style="bold green")
                self.console.print("    ║       Y O U   T U R N E D               ║", style="bold green")
                self.console.print("    ║   The infection claimed another soul.    ║", style="bold green")
                self.console.print("    ╚═══════════════════════════════════════════╝", style="bold green")
            self.console.print(f"\n    {t('You lasted {days} days before losing yourself.', days=state.world.day)}", style="dim")
        else:
            print(f"\n\n    ═══ {t('YOU TURNED')} ═══")
            print(f"    {t('You lasted {days} days before losing yourself.', days=state.world.day)}")

    def print_victory_screen(self, state: GameState):
        self.clear()
        zh = Config.LANG == "zh"
        if HAS_RICH:
            self.console.print("\n\n")
            if zh:
                self.console.print("    ╔═══════════════════════════════════════════╗", style="bold green")
                self.console.print("    ║       你   逃   出   生   天             ║", style="bold green")
                self.console.print("    ║   直升机在黎明时分起飞。                ║", style="bold green")
                self.console.print("    ╚═══════════════════════════════════════════╝", style="bold green")
            else:
                self.console.print("    ╔═══════════════════════════════════════════╗", style="bold green")
                self.console.print("    ║       Y O U   E S C A P E D              ║", style="bold green")
                self.console.print("    ║   The helicopter lifts off at dawn.      ║", style="bold green")
                self.console.print("    ╚═══════════════════════════════════════════╝", style="bold green")
            self.console.print(f"\n    {t('{days} days. {kills} kills. You made it.', days=state.world.day, kills=state.player.kills)}", style="bold white")
        else:
            print(f"\n\n    ═══ {t('YOU ESCAPED')} ═══")
            print(f"    {t('{days} days. {kills} kills. You made it.', days=state.world.day, kills=state.player.kills)}")

    def get_input(self, prompt_text: str = "> ") -> str:
        if HAS_RICH:
            return self.console.input(f"\n [bold white]{prompt_text}[/] ").strip()
        else:
            return input(f"\n{prompt_text}").strip()

    def print_loading(self):
        if HAS_RICH:
            self.console.print(f"\n  [dim]{t('The dead city speaks...')}[/]", end="")
        else:
            print(f"\n  {t('Thinking...')}", end="", flush=True)

    def print_help(self):
        help_text = t("help_text")
        if HAS_RICH:
            title = "帮助" if Config.LANG == "zh" else "Help"
            self.console.print(Panel(help_text.strip(), title=title, border_style="cyan"))
        else:
            print(help_text)


# ══════════════════════════════════════════════════════════════════
# SAVE / LOAD
# ══════════════════════════════════════════════════════════════════

def save_game(state: GameState, event_system: EventSystem, filepath: str = Config.SAVE_FILE):
    data = {
        "player": asdict(state.player),
        "world": {
            **asdict(state.world),
            "time_of_day": state.world.time_of_day.value,
            "weather": state.world.weather.value,
        },
        "history": state.history,
        "turn": state.turn,
        "event_system": event_system.to_dict(),
    }
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)

def load_game(filepath: str = Config.SAVE_FILE) -> tuple:
    with open(filepath, 'r') as f:
        data = json.load(f)

    state = GameState()
    # Restore player
    for k, v in data["player"].items():
        setattr(state.player, k, v)
    # Restore world
    for k, v in data["world"].items():
        if k == "time_of_day":
            state.world.time_of_day = TimeOfDay(v)
        elif k == "weather":
            state.world.weather = Weather(v)
        else:
            setattr(state.world, k, v)
    state.history = data.get("history", [])
    state.turn = data.get("turn", 0)

    event_system = EventSystem.from_dict(data.get("event_system", {}))
    return state, event_system


# ══════════════════════════════════════════════════════════════════
# MAIN GAME LOOP
# ══════════════════════════════════════════════════════════════════

class DeadStaticGame:
    def __init__(self):
        self.state = GameState()
        self.events = EventSystem()
        self.rules = RulesEngine()
        self.display = Display()
        self.llm = None
        self.current_options = {}
        self.last_action_context = ""  # Tracks what the player did last turn
        self.last_narrative = ""  # LLM's previous narrative output for continuity
        # RAG: episodic memory (long-horizon coherence via BM25 retrieval).
        # Session id defaults to "default" and is refreshed on each new_game().
        self.memory = None
        if HAS_RAG and Config.RAG_ENABLED:
            try:
                self.memory = EpisodicMemory("current", Config.RAG_DIR)
            except Exception:
                self.memory = None

        # RAG Phase 2: static lore corpus (per-location flavor + atmosphere).
        # Loaded once from the corpus module; no disk I/O after init.
        self.lore = None
        if HAS_RAG and LoreStore is not None and Config.LORE_ENABLED:
            try:
                self.lore = LoreStore()
            except Exception:
                self.lore = None

    def initialize_llm(self):
        """Initialize the LLM: download runtime + model if needed, start server."""
        console = self.display.console if HAS_RICH else None

        # Step 1: Download llama-server binary if not present
        if not RuntimeManager.is_server_installed():
            self.display.print_system_message(t("First-time setup: downloading AI runtime..."))
            if not RuntimeManager.download_server(console):
                self.display.print_system_message(
                    f"{t('Runtime download failed.')}\n"
                    f"  → {t('Check your internet connection and try again.')}"
                )
                input(f"\n  {t('Press Enter to exit...')}")
                return False

        # Step 2: Download model if not present
        if not RuntimeManager.is_model_downloaded():
            self.display.print_system_message(t("Downloading AI model (one-time, ~1 GB)..."))
            if not RuntimeManager.download_model(console):
                self.display.print_system_message(
                    f"{t('Model download failed.')}\n"
                    f"  → {t('Check your internet connection and try again.')}"
                )
                input(f"\n  {t('Press Enter to exit...')}")
                return False
        else:
            size = RuntimeManager.get_model_size_str()
            self.display.print_system_message(f"Model found ({size})")

        # Step 3: Start llama-server
        self.display.print_system_message(t("Starting AI engine..."))
        if not RuntimeManager.start_server(console):
            self.display.print_system_message(
                f"{t('Failed to start AI engine.')}\n"
                f"  → {t('Try restarting the game.')}"
            )
            input(f"\n  {t('Press Enter to exit...')}")
            return False

        self.llm = LLMClient()
        return True

    def title_screen(self):
        while True:
            self.display.clear()
            self.display.print_title_screen()

            choice = self.display.get_input(t("Choose: ")).strip()
            if choice == '1':
                self.new_game()
                return True
            elif choice == '2':
                if os.path.exists(Config.SAVE_FILE):
                    self.state, self.events = load_game()
                    self.display.print_system_message(t("Game loaded."))
                    return True
                else:
                    self.display.print_system_message(t("No save file found."))
                    input(f"\n  {t('Press Enter to continue...')}")
            elif choice == '3':
                self.settings_menu()
                # Loop back to redraw title screen with potentially new language
            elif choice.upper() == 'Q':
                return False

    def new_game(self):
        self.state = GameState()
        self.events = EventSystem()
        # Reset episodic memory for a fresh playthrough
        if self.memory is not None:
            try:
                self.memory.reset()
            except Exception:
                pass

        self.display.clear()
        name = self.display.get_input(t("What is your name, survivor? ")) or t("Survivor")
        self.state.player.name = name

        self.display.print_system_message(t("Good luck, {name}. You'll need it.", name=name))
        time.sleep(1)

        # Opening flavor
        opening = t("opening_narrative")
        self.display.print_narrative(opening)

        # Starting items (random)
        starter_items = random.sample(["kitchen knife", "canned beans", "bottled water", "matchbox", "dirty bandage"], k=3)
        self.state.player.inventory = starter_items
        self.display.print_system_message(f"{t('You find nearby:')} {', '.join(_item_name(i) for i in starter_items)}")

        input(f"\n  {t('Press Enter to begin...')}")

    def settings_menu(self):
        while True:
            self.display.clear()
            lang_display = "中文" if Config.LANG == "zh" else "English"
            print(f"\n  ── {t('Settings')} ──")
            print(f"\n  Model: {Config.GGUF_FILENAME} {t('(Q4 quantized)')}")
            print(f"  Server: llama-server ({Config.LLAMA_CPP_VERSION})")
            model_status = f"✓ Downloaded ({RuntimeManager.get_model_size_str()})" if RuntimeManager.is_model_downloaded() else "✗ Not downloaded"
            server_status = "✓ Installed" if RuntimeManager.is_server_installed() else "✗ Not installed"
            print(f"  Model: {model_status}")
            print(f"  Runtime: {server_status}")

            # Memory (RAG) status line
            if HAS_RAG:
                rag_status = "ON" if Config.RAG_ENABLED else "OFF"
                sum_status = "ON" if Config.RAG_LLM_SUMMARY else "OFF"
                lore_status = "ON" if Config.LORE_ENABLED else "OFF"
                if Config.LANG == "zh":
                    rag_label = f"  剧情记忆 (RAG): {rag_status}  |  LLM 摘要: {sum_status}  |  场景参考: {lore_status}"
                else:
                    rag_label = f"  Story memory (RAG): {rag_status}  |  LLM summary: {sum_status}  |  Scene lore: {lore_status}"
                print(f"\n{rag_label}")

            print(f"\n  {t('[1] Run diagnostics')}")
            print(f"  {t('[2] Re-download model & runtime')}")
            print(f"  {t('[3] Language: {lang}', lang=lang_display)}")
            if HAS_RAG:
                if Config.LANG == "zh":
                    print(f"  [4] 切换剧情记忆 (RAG)")
                    print(f"  [5] 切换 LLM 摘要（慢但更准）")
                    print(f"  [6] 切换场景参考（静态地点描述）")
                else:
                    print(f"  [4] Toggle story memory (RAG)")
                    print(f"  [5] Toggle LLM summary (slower but sharper)")
                    print(f"  [6] Toggle scene lore (static location flavor)")
            print(f"  {t('[B] Back')}")

            choice = self.display.get_input(t("Choose: ")).strip()
            if choice == '1':
                print(f"\n{RuntimeManager.full_diagnostics()}")
                input(f"\n  {t('Press Enter to continue...')}")
            elif choice == '2':
                console = self.display.console if HAS_RICH else None
                RuntimeManager.download_server(console)
                RuntimeManager.download_model(console)
                input(f"\n  {t('Press Enter to continue...')}")
            elif choice == '3':
                Config.LANG = "en" if Config.LANG == "zh" else "zh"
                new_lang = "中文" if Config.LANG == "zh" else "English"
                self.display.print_system_message(t("Language switched to: {lang}", lang=new_lang))
                time.sleep(0.5)
            elif choice == '4' and HAS_RAG:
                Config.RAG_ENABLED = not Config.RAG_ENABLED
                state = "ON" if Config.RAG_ENABLED else "OFF"
                msg = f"剧情记忆已{'开启' if Config.RAG_ENABLED else '关闭'}" if Config.LANG == "zh" else f"Story memory: {state}"
                self.display.print_system_message(msg)
                time.sleep(0.5)
            elif choice == '5' and HAS_RAG:
                Config.RAG_LLM_SUMMARY = not Config.RAG_LLM_SUMMARY
                state = "ON" if Config.RAG_LLM_SUMMARY else "OFF"
                msg = f"LLM 摘要已{'开启' if Config.RAG_LLM_SUMMARY else '关闭'}" if Config.LANG == "zh" else f"LLM summary: {state}"
                self.display.print_system_message(msg)
                time.sleep(0.5)
            elif choice == '6' and HAS_RAG:
                Config.LORE_ENABLED = not Config.LORE_ENABLED
                state = "ON" if Config.LORE_ENABLED else "OFF"
                msg = f"场景参考已{'开启' if Config.LORE_ENABLED else '关闭'}" if Config.LANG == "zh" else f"Scene lore: {state}"
                self.display.print_system_message(msg)
                time.sleep(0.5)
            elif choice.upper() == 'B':
                break

    def handle_command(self, user_input: str) -> bool:
        """Handle meta-commands. Returns True if command was handled."""
        cmd = user_input.lower().strip()

        if cmd == "help":
            self.display.print_help()
            return True
        elif cmd == "inventory" or cmd == "inv" or cmd == "i":
            self._show_inventory()
            return True
        elif cmd == "status" or cmd == "stats":
            self._show_status()
            return True
        elif cmd == "map" or cmd == "m":
            self._show_map()
            return True
        elif cmd == "save":
            save_game(self.state, self.events)
            self.display.print_system_message(t("Game saved."))
            return True
        elif cmd.startswith("use "):
            raw_name = cmd[4:].strip()
            item_key = _item_key_from_input(raw_name)
            if item_key:
                result = self.rules.use_item(self.state.player, item_key)
                self.display.print_system_message(result["message"])
            else:
                self.display.print_system_message(t("You don't have that."))
            return True
        elif cmd.startswith("equip "):
            raw_name = cmd[6:].strip()
            item_key = _item_key_from_input(raw_name)
            if item_key and item_key in self.state.player.inventory:
                item = ITEMS.get(item_key, {})
                if item.get("type") == "weapon":
                    self.state.player.equipped_weapon = item_key
                    self.display.print_system_message(t("Equipped {item}.", item=_item_name(item_key)))
                else:
                    self.display.print_system_message(t("Can't equip {item} as a weapon.", item=_item_name(item_key)))
            else:
                self.display.print_system_message(t("You don't have that."))
            return True
        elif cmd == "quit" or cmd == "exit":
            save_q = self.display.get_input(t("Save before quitting? (y/n) "))
            if save_q.lower() == 'y':
                save_game(self.state, self.events)
            sys.exit(0)

        return False

    def _show_inventory(self):
        p = self.state.player
        inv_title = f"{t('Inventory')} ({len(p.inventory)}/{p.max_inventory})"
        if HAS_RICH:
            table = Table(title=inv_title, box=box.SIMPLE)
            table.add_column(t("Item"), style="cyan")
            table.add_column(t("Type"), style="dim")
            table.add_column(t("Description"), style="white")
            for item_key in p.inventory:
                item = ITEMS.get(item_key, {})
                equipped = " ⚔" if item_key == p.equipped_weapon else ""
                item_type = t(item.get("type", "?"))
                table.add_row(_item_name(item_key) + equipped, item_type, _item_desc(item_key))
            self.display.console.print(table)
        else:
            print(f"\n{inv_title}:")
            for item_key in p.inventory:
                eq = " [EQUIPPED]" if item_key == p.equipped_weapon else ""
                print(f"  - {_item_name(item_key)}{eq}: {_item_desc(item_key)}")

    def _show_status(self):
        p = self.state.player
        if HAS_RICH:
            txt = f"""{t('Name:')} {p.name}
{t('Skills:')} {t('Combat')} {p.skills['combat']:.0f} | {t('Stealth')} {p.skills['stealth']:.0f} | {t('Medical')} {p.skills['medical']:.0f} | {t('Survival')} {p.skills['survival']:.0f} | {t('Persuasion')} {p.skills['persuasion']:.0f}
{t('Kills:')} {p.kills} | {t('Saved:')} {p.people_saved} | {t('Abandoned:')} {p.people_abandoned}
{t('Days survived:')} {self.state.world.day}"""
            self.display.console.print(Panel(txt, title=t("Status"), border_style="cyan"))
        else:
            print(f"\n{t('Name:')} {p.name}")
            print(f"{t('Skills:')} {p.skills}")
            print(f"{t('Kills:')} {p.kills} | {t('Days survived:')} {self.state.world.day}")

    def _show_map(self):
        w = self.state.world
        current = w.location
        loc = LOCATIONS.get(current, {})
        connections = loc.get("connections", [])
        discovered = w.discovered_locations

        if HAS_RICH:
            lines = [f"[bold cyan]{t('Current:')} {_loc_name(current)}[/]", f"{t('Connected:')}"]
            for c in connections:
                threat = LOCATIONS.get(c, {}).get("base_threat", "?")
                known = "✓" if c in discovered else "?"
                lines.append(f"  [{known}] {_loc_name(c)} ({t('Threat:')} {threat})")
            lines.append(f"\n{t('Discovered locations:')} {', '.join(_loc_name(d) for d in discovered)}")
            self.display.console.print(Panel('\n'.join(lines), title=t("Map"), border_style="cyan"))
        else:
            print(f"\n{t('Current:')} {_loc_name(current)}")
            print(f"{t('Connected:')} {', '.join(_loc_name(c) for c in connections)}")
            print(f"{t('Discovered locations:')} {', '.join(_loc_name(d) for d in discovered)}")

    def game_turn(self):
        """One full game turn."""
        # 1. Tick survival resources (weather affects drain rates)
        self.rules.tick_survival(self.state.player, self.state.world.weather)

        # 2. Check game over from resource drain
        go = self.rules.check_game_over(self.state)
        if go != GameOver.NONE:
            self.state.game_over = go
            return

        # 3. Generate event
        event = self.events.generate_event(self.state)

        # 4. Display
        self.display.clear()
        self.display.print_status_bar(self.state)
        self.display.print_event_title(event["title"], event.get("is_story", False))

        # 5. Build prompt with previous narrative + action for story continuity.
        #    RAG: retrieve relevant past memories (location / weather / action based)
        #    and inject as "past echoes" so long games keep continuity.
        memory_snippets = ""
        revisit_memory = ""
        if (self.memory is not None
                and Config.RAG_ENABLED
                and self.state.turn >= Config.RAG_MIN_TURN):
            try:
                query_parts = [
                    self.state.world.location,
                    LOCATIONS.get(self.state.world.location, {}).get("name_zh", ""),
                    self.state.world.time_of_day.value,
                    self.state.world.weather.value,
                    event.get("title", ""),
                    event.get("description", ""),
                    self.last_action_context,
                ]
                query_text = " ".join(p for p in query_parts if p)
                hits = self.memory.query(
                    query_text,
                    k=Config.RAG_TOP_K,
                    exclude_last=Config.RAG_EXCLUDE_LAST,
                    min_score=Config.RAG_MIN_SCORE,
                )
                memory_snippets = self.memory.format_for_prompt(hits, lang=Config.LANG)

                # Revisit detection: is the player back at a location they were
                # at before? Find the most recent past entry with the same location.
                # Small models need a pointed instruction to actually use context.
                # Prefer the LLM-generated summary (semantic content like "found
                # antibiotics") over raw_narrative_head (atmospheric opener), since
                # the summary is what we actually want the model to echo.
                current_loc = self.state.world.location
                for entry in reversed(self.memory.entries[:-Config.RAG_EXCLUDE_LAST]
                                      if Config.RAG_EXCLUDE_LAST > 0
                                      else self.memory.entries):
                    if entry.location == current_loc:
                        fragment = (entry.summary or entry.raw_narrative_head or "").strip()
                        if len(fragment) > 100:
                            fragment = fragment[:100] + "…"
                        revisit_memory = fragment
                        break
            except Exception:
                memory_snippets = ""
                revisit_memory = ""

        # RAG Phase 2: retrieve static lore for this location / weather / time.
        # Separate from episodic — runs every turn (no warm-up), location-filtered,
        # injected as "scene reference" so the model borrows consistent imagery.
        lore_snippets = ""
        if self.lore is not None and Config.LORE_ENABLED:
            try:
                lore_hits = self.lore.query(
                    location=self.state.world.location,
                    weather=self.state.world.weather.value,
                    time_of_day=self.state.world.time_of_day.value,
                    query_text=" ".join([
                        event.get("title", ""),
                        event.get("description", ""),
                        self.last_action_context,
                    ]),
                    k=Config.LORE_TOP_K,
                    include_atmosphere=Config.LORE_INCLUDE_ATMOSPHERE,
                )
                lore_snippets = self.lore.format_for_prompt(lore_hits, lang=Config.LANG)
            except Exception:
                lore_snippets = ""

        prompt = build_prompt(
            self.state, event,
            action_context=self.last_action_context,
            prev_narrative=self.last_narrative,
            memory_snippets=memory_snippets,
            revisit_memory=revisit_memory,
            lore_snippets=lore_snippets,
        )
        self.display.print_loading()

        # 5a. Stream LLM output token-by-token for live display
        self.display.start_narrative_stream()
        raw_output = self.llm.generate_stream(
            _get_system_prompt(), prompt,
            on_token=self.display.print_token,
        )
        self.display.end_narrative_stream()

        # 5b. Parse the full output to extract choices
        parsed = parse_llm_output(raw_output, self.state)

        # 5c. If parsing failed, try a repair prompt (non-streaming)
        if parsed.get("parse_failed"):
            repair_input = raw_output + "\n\n" + _get_repair_prompt()
            repair_raw = self.llm.generate(_get_system_prompt(), repair_input)
            repair_parsed = parse_llm_output(repair_raw, self.state)
            if not repair_parsed.get("parse_failed"):
                parsed["options"] = repair_parsed["options"]
                parsed["parse_failed"] = False
            else:
                self.display.print_system_message(t("(Auto-generated choices for this turn)"))

        # 6. Store narrative for next turn's continuity
        #    (narrative already displayed via streaming, so only print choices)
        self.last_narrative = parsed["narrative"]
        self.current_options = parsed["options"]
        self.display.print_choices(self.current_options)
        # Show command hints
        if Config.LANG == "zh":
            hint = "  (输入 save 保存 | inventory 物品栏 | help 帮助 | quit 退出)"
        else:
            hint = "  (save | inventory | help | quit)"
        if HAS_RICH:
            self.display.console.print(hint, style="dim")
        else:
            print(hint)

        # 7. Player input loop
        while True:
            user_input = self.display.get_input(t("Your choice: ")).strip()

            if not user_input:
                continue

            # Check meta-commands first
            if self.handle_command(user_input):
                self.display.print_choices(self.current_options)
                continue

            # Check if it's a valid choice
            choice_key = user_input.upper()
            if choice_key in self.current_options:
                break

            # Check if they typed the action text directly
            for k, v in self.current_options.items():
                if user_input.lower() in v.lower():
                    choice_key = k
                    break
            else:
                self.display.print_system_message(t("Invalid. Choose A, B, or C (or type 'help')."))
                continue
            break

        chosen_action = self.current_options.get(choice_key, user_input)

        # 8. Resolve action mechanically
        extra_context = []

        # Movement detection (match English name, Chinese name, or partial)
        loc = LOCATIONS.get(self.state.world.location, {})
        action_lower = chosen_action.lower()
        for conn in loc.get("connections", []):
            conn_zh = LOCATIONS.get(conn, {}).get("name_zh", "")
            if conn.lower() in action_lower or (conn_zh and conn_zh in chosen_action):
                self.state.world.location = conn
                if conn not in self.state.world.discovered_locations:
                    self.state.world.discovered_locations.append(conn)
                extra_context.append(f"[Moved to {conn}]")
                break

        # Combat detection
        combat_keywords = ["fight", "attack", "kill", "shoot", "swing", "stab", "confront", "charge",
                           "战斗", "攻击", "杀", "射击", "开枪", "刺", "砍", "冲", "举起武器", "武器"]
        if any(kw in chosen_action.lower() for kw in combat_keywords):
            result = self.rules.resolve_combat(self.state.player, self.state.world.threat_level)
            extra_context.append(f"[Combat: {result['outcome']}. {result['narrative_hint']}]")
            self.state.world.noise_level += result.get("noise_generated", 0)

        # Stealth detection
        stealth_keywords = ["sneak", "hide", "stealth", "quiet", "avoid", "creep", "slip past",
                            "潜行", "躲", "藏", "安静", "避开", "悄悄", "绕过", "隐蔽"]
        if any(kw in chosen_action.lower() for kw in stealth_keywords):
            result = self.rules.resolve_stealth(self.state.player, self.state.world.threat_level, self.state.world.weather)
            extra_context.append(f"[Stealth: {result['outcome']}. {result['narrative_hint']}]")

        # Scavenging / loot
        search_keywords = ["search", "loot", "scavenge", "look for", "check", "rummage", "open", "grab",
                           "搜索", "搜刮", "搜寻", "查看", "检查", "翻找", "打开", "拿"]
        if any(kw in chosen_action.lower() for kw in search_keywords) and event["id"] in ("scavenge", "quiet_moment", "free_roam", "locked_door"):
            loc_data = LOCATIONS.get(self.state.world.location, {})
            if random.random() < loc_data.get("loot_chance", 0.2) and loc_data.get("loot_table"):
                found = random.choice(loc_data["loot_table"])
                if len(self.state.player.inventory) < self.state.player.max_inventory:
                    self.state.player.inventory.append(found)
                    extra_context.append(f"[Found: {_item_name(found)}]")
                else:
                    extra_context.append(f"[Spotted {_item_name(found)} but inventory is full]")

        # NPC interaction detection (survivor encounters)
        help_keywords = ["help", "save", "assist", "protect", "share", "give", "aid", "together",
                         "帮", "救", "协助", "保护", "分享", "给", "援助", "一起", "带上", "收留"]
        abandon_keywords = ["ignore", "leave", "abandon", "walk away", "alone", "refuse",
                            "忽略", "离开", "抛弃", "走开", "独自", "拒绝", "不管", "丢下"]
        if event["id"] == "survivor_encounter":
            if any(kw in chosen_action.lower() for kw in help_keywords):
                self.state.player.people_saved += 1
                self.state.player.morale = min(100, self.state.player.morale + random.randint(5, 15))
                # Helping costs resources but boosts morale
                self.state.player.hunger = max(0, self.state.player.hunger - random.randint(5, 10))
                zh = Config.LANG == "zh"
                extra_context.append(f"[{'救助了一名幸存者，士气提升' if zh else 'Helped a survivor. Morale boosted'}]")
            elif any(kw in chosen_action.lower() for kw in abandon_keywords):
                self.state.player.people_abandoned += 1
                self.state.player.morale = max(0, self.state.player.morale - random.randint(5, 15))
                zh = Config.LANG == "zh"
                extra_context.append(f"[{'抛弃了一名幸存者，士气下降' if zh else 'Abandoned a survivor. Morale dropped'}]")

        # Rest detection
        rest_keywords = ["rest", "sleep", "camp", "wait", "recover",
                         "休息", "睡", "扎营", "等待", "恢复", "歇"]
        if any(kw in chosen_action.lower() for kw in rest_keywords):
            stamina_restore = random.randint(15, 30)
            hp_restore = random.randint(3, 8)
            self.state.player.stamina = min(100, self.state.player.stamina + stamina_restore)
            self.state.player.health = min(100, self.state.player.health + hp_restore)
            morale_change = random.randint(-5, 10)
            self.state.player.morale = max(0, min(100, self.state.player.morale + morale_change))
            extra_context.append(f"[Rested. +{stamina_restore} stamina, +{hp_restore} HP]")

        # 9. Save the action + outcome for next turn's LLM prompt
        self.last_action_context = chosen_action
        if extra_context:
            # Convert mechanical tags to narrative hints
            hints = []
            zh = Config.LANG == "zh"
            for ctx in extra_context:
                ctx = ctx.strip("[]")
                if ctx.startswith("Combat:"):
                    hints.append(ctx.replace("Combat: ", ""))
                elif ctx.startswith("Stealth:"):
                    hints.append(ctx.replace("Stealth: ", ""))
                elif ctx.startswith("Found:"):
                    item = ctx.replace("Found: ", "")
                    hints.append(f"找到了{item}" if zh else f"found {item}")
                elif ctx.startswith("Spotted"):
                    item = ctx.replace("Spotted ", "").replace(" but inventory is full", "")
                    hints.append(f"看到了{item}但背包满了" if zh else ctx)
                elif ctx.startswith("Moved to"):
                    pass  # movement is obvious from location change
                elif ctx.startswith("Rested"):
                    hints.append("休息并恢复了一些体力" if zh else "rested and recovered some energy")
                else:
                    hints.append(ctx)
            if hints:
                self.last_action_context += " (" + "; ".join(hints) + ")"

        # 10. Update history
        summary = f"Day {self.state.world.day} {self.state.world.time_of_day.value}: {chosen_action}"
        if extra_context:
            summary += " " + " ".join(extra_context)
        self.state.history.append(summary)

        # 10b. Episodic memory: record this turn so future turns can retrieve it.
        if self.memory is not None and Config.RAG_ENABLED:
            try:
                outcome_str = " ".join(extra_context) if extra_context else ""
                # Short narrative head — the first sentence is usually the meat
                head = (self.last_narrative or "").strip()
                for sep in ["。", ".", "\n"]:
                    if sep in head:
                        head = head.split(sep, 1)[0] + sep
                        break
                head = head[:160]
                # Auto-generated summary for retrieval: action + outcome, in either language
                zh = Config.LANG == "zh"
                loc_display = (
                    LOCATIONS.get(self.state.world.location, {}).get("name_zh", self.state.world.location)
                    if zh else self.state.world.location
                )
                auto_summary = f"{loc_display}: {chosen_action}"
                if outcome_str:
                    auto_summary += " — " + outcome_str
                auto_summary = auto_summary[:200]

                # Phase 1.5: upgrade summary with a quick LLM call when enabled.
                # Never overwrite the mechanical summary if the LLM call fails —
                # we keep auto_summary as the robust fallback.
                if (Config.RAG_LLM_SUMMARY and _rag_summarize_turn is not None
                        and self.llm is not None and self.last_narrative):
                    llm_summary = _rag_summarize_turn(
                        self.llm,
                        narrative=self.last_narrative,
                        action=chosen_action,
                        location=loc_display,
                        outcome=outcome_str,
                        lang=Config.LANG,
                        max_tokens=Config.RAG_LLM_SUMMARY_MAX_TOKENS,
                    )
                    if llm_summary:
                        auto_summary = llm_summary

                self.memory.record(
                    turn=self.state.turn,
                    day=self.state.world.day,
                    time_of_day=self.state.world.time_of_day.value,
                    location=self.state.world.location,
                    weather=self.state.world.weather.value,
                    action=chosen_action,
                    outcome=outcome_str,
                    summary=auto_summary,
                    raw_narrative_head=head,
                )
            except Exception:
                pass  # never let memory failures break a turn

        # 10. Advance time
        self.rules.advance_time(self.state.world)
        self.state.turn += 1
        self.state.player.days_survived = self.state.world.day

        # 11. Check game over
        go = self.rules.check_game_over(self.state)
        if go != GameOver.NONE:
            self.state.game_over = go

    def run(self):
        """Main entry point."""
        if not self.title_screen():
            return

        if not self.initialize_llm():
            self.display.print_system_message(t("Could not initialize LLM. Check settings."))
            return

        self._play_loop()

    def _play_loop(self, restart=False):
        """Core game loop. Can be called again on restart without re-initializing LLM."""
        self.current_options = {}
        self.last_action_context = ""
        self.last_narrative = ""
        if restart:
            self.new_game()

        while self.state.game_over == GameOver.NONE:
            try:
                self.game_turn()
            except KeyboardInterrupt:
                self.display.print_system_message("\nInterrupted. Saving...")
                save_game(self.state, self.events)
                return

        # Game over screens
        if self.state.game_over == GameOver.DEAD:
            self.display.print_death_screen(self.state)
        elif self.state.game_over == GameOver.INFECTED:
            self.display.print_infected_screen(self.state)
        elif self.state.game_over == GameOver.ESCAPED:
            self.display.print_victory_screen(self.state)

        # Restart or quit
        if self._ask_restart():
            self._play_loop(restart=True)

    def _ask_restart(self) -> bool:
        """Ask the player if they want to play again."""
        if Config.LANG == "zh":
            prompt = "\n  [R] 重新开始    [Q] 退出"
        else:
            prompt = "\n  [R] Play Again    [Q] Quit"
        if HAS_RICH:
            self.display.console.print(prompt, style="bold")
        else:
            print(prompt)
        while True:
            choice = self.display.get_input(t("Your choice: ")).strip().upper()
            if choice in ("R", "重"):
                return True
            if choice in ("Q", "退", ""):
                return False


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    game = DeadStaticGame()
    game.run()
