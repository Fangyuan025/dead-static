"""
DEAD STATIC — A Zombie Apocalypse Text Adventure
Powered by local LLM (Ollama or llama-cpp-python)
"""

import json
import os
import random
import re
import time
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

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

# ─── Try to import LLM backends ───
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from llama_cpp import Llama
    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False


# ══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════

class Config:
    # LLM Backend: "ollama" or "llama_cpp"
    LLM_BACKEND = "ollama"

    # Ollama settings
    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "dolphin-phi"

    # llama.cpp settings
    GGUF_MODEL_PATH = "./model.gguf"
    N_CTX = 4096
    N_GPU_LAYERS = -1  # -1 = offload all to GPU

    # Game settings
    SAVE_FILE = "dead_static_save.json"
    MAX_HISTORY = 8
    LLM_MAX_TOKENS = 400
    LLM_TEMPERATURE = 0.8
    LLM_TOP_P = 0.9


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
        "description": "A ransacked apartment on the third floor. The door barely holds.",
        "connections": ["Main Street", "Back Alley", "Rooftop"],
        "loot_table": ["kitchen knife", "canned beans", "dirty bandage", "matchbox"],
        "loot_chance": 0.3,
    },
    "Main Street": {
        "type": "street", "base_threat": 5,
        "description": "A wide boulevard littered with wrecked cars and dried blood.",
        "connections": ["Abandoned Apartment", "Grocery Store", "Police Station", "Hospital"],
        "loot_table": ["glass bottle", "car battery", "pipe wrench"],
        "loot_chance": 0.2,
    },
    "Back Alley": {
        "type": "street", "base_threat": 4,
        "description": "Narrow alley reeking of rot. Dumpsters line both walls.",
        "connections": ["Abandoned Apartment", "Pawn Shop", "Sewer Entrance"],
        "loot_table": ["crowbar", "rat meat", "plastic tarp", "duct tape"],
        "loot_chance": 0.4,
    },
    "Rooftop": {
        "type": "shelter", "base_threat": 1,
        "description": "Wind-swept rooftop with a view of the ruined skyline. Relatively safe.",
        "connections": ["Abandoned Apartment"],
        "loot_table": ["rainwater bottle", "signal flare"],
        "loot_chance": 0.15,
    },
    "Grocery Store": {
        "type": "building", "base_threat": 6,
        "description": "Shelves mostly bare, but the back storage room might still have supplies.",
        "connections": ["Main Street"],
        "loot_table": ["canned soup", "bottled water", "energy bar", "bleach", "canned beans"],
        "loot_chance": 0.5,
    },
    "Police Station": {
        "type": "building", "base_threat": 7,
        "description": "Barricaded front, broken windows. Could have weapons — or worse.",
        "connections": ["Main Street"],
        "loot_table": ["pistol", "ammo clip", "body armor vest", "first aid kit", "radio"],
        "loot_chance": 0.35,
    },
    "Hospital": {
        "type": "building", "base_threat": 8,
        "description": "The west wing collapsed. East wing is dark and full of shuffling sounds.",
        "connections": ["Main Street", "Hospital Basement"],
        "loot_table": ["antibiotics", "surgical kit", "morphine syringe", "medical mask", "first aid kit"],
        "loot_chance": 0.4,
    },
    "Hospital Basement": {
        "type": "building", "base_threat": 9,
        "description": "Emergency generators still hum. Smells like formaldehyde and death.",
        "connections": ["Hospital"],
        "loot_table": ["experimental antiviral", "hazmat suit", "defibrillator"],
        "loot_chance": 0.25,
    },
    "Pawn Shop": {
        "type": "building", "base_threat": 4,
        "description": "Iron bars on the windows. The owner didn't make it, but his stock did.",
        "connections": ["Back Alley"],
        "loot_table": ["machete", "hunting knife", "baseball bat", "binoculars", "lockpick set"],
        "loot_chance": 0.45,
    },
    "Sewer Entrance": {
        "type": "wilderness", "base_threat": 6,
        "description": "A rusted grate leads into the sewer tunnels. Quiet, but claustrophobic.",
        "connections": ["Back Alley", "Sewer Tunnels"],
        "loot_table": ["flashlight", "rubber boots", "gas mask"],
        "loot_chance": 0.3,
    },
    "Sewer Tunnels": {
        "type": "wilderness", "base_threat": 7,
        "description": "Ankle-deep water, echoing drips. Something moved in the dark ahead.",
        "connections": ["Sewer Entrance", "River Bridge"],
        "loot_table": ["military MRE", "glow stick", "waterproof bag"],
        "loot_chance": 0.35,
    },
    "River Bridge": {
        "type": "street", "base_threat": 5,
        "description": "The bridge is partially collapsed but crossable. The other side looks... different.",
        "connections": ["Sewer Tunnels", "Military Checkpoint"],
        "loot_table": ["rope", "signal flare", "binoculars"],
        "loot_chance": 0.2,
    },
    "Military Checkpoint": {
        "type": "building", "base_threat": 6,
        "description": "Sandbags, razor wire, and silence. The soldiers are long gone — or turned.",
        "connections": ["River Bridge", "Evacuation Zone"],
        "loot_table": ["assault rifle", "ammo box", "MRE pack", "military radio", "body armor vest"],
        "loot_chance": 0.4,
    },
    "Evacuation Zone": {
        "type": "building", "base_threat": 3,
        "description": "A fenced compound with helicopter pads. The last broadcast said rescue comes at dawn.",
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
    "canned beans":      {"type": "food", "hunger_restore": 25, "desc": "Dented but sealed"},
    "canned soup":       {"type": "food", "hunger_restore": 30, "desc": "Chicken noodle, lukewarm"},
    "energy bar":        {"type": "food", "hunger_restore": 15, "desc": "Expired but edible"},
    "rat meat":          {"type": "food", "hunger_restore": 20, "desc": "Cooked over an open flame... hopefully"},
    "military MRE":      {"type": "food", "hunger_restore": 45, "desc": "Meals Ready to Eat. Tastes like cardboard salvation"},
    "MRE pack":          {"type": "food", "hunger_restore": 45, "desc": "Standard military ration"},
    "bottled water":     {"type": "water", "thirst_restore": 40, "desc": "Clean, sealed"},
    "rainwater bottle":  {"type": "water", "thirst_restore": 25, "desc": "Collected from the rooftop"},

    # Medical
    "dirty bandage":     {"type": "medical", "heal": 10, "infection_risk": 10, "desc": "Better than nothing"},
    "first aid kit":     {"type": "medical", "heal": 35, "infection_risk": 0, "desc": "Standard trauma kit"},
    "surgical kit":      {"type": "medical", "heal": 50, "infection_risk": 0, "desc": "Professional-grade"},
    "antibiotics":       {"type": "medical", "heal": 10, "infection_reduce": 30, "desc": "Could slow the infection"},
    "morphine syringe":  {"type": "medical", "heal": 5, "morale_restore": 30, "desc": "Numbs everything"},
    "experimental antiviral": {"type": "medical", "infection_reduce": 80, "desc": "Labeled 'TRIAL PHASE III'. Might work"},
    "medical mask":      {"type": "armor", "protection": 5, "desc": "Thin barrier between you and the air"},
    "bleach":            {"type": "utility", "desc": "Can purify water or clean wounds (painfully)"},

    # Weapons
    "kitchen knife":     {"type": "weapon", "damage": 10, "desc": "Dull but desperate"},
    "hunting knife":     {"type": "weapon", "damage": 15, "desc": "Serrated edge, good grip"},
    "crowbar":           {"type": "weapon", "damage": 18, "desc": "Heavy, reliable, opens doors too"},
    "pipe wrench":       {"type": "weapon", "damage": 15, "desc": "Blunt and brutal"},
    "machete":           {"type": "weapon", "damage": 22, "desc": "Clean cuts. Keep it sharp"},
    "baseball bat":      {"type": "weapon", "damage": 16, "desc": "Aluminum. Dented but solid"},
    "pistol":            {"type": "weapon", "damage": 30, "noise": 8, "desc": "9mm. Loud. Attracts attention"},
    "assault rifle":     {"type": "weapon", "damage": 45, "noise": 10, "desc": "Full auto. Last resort"},
    "glass bottle":      {"type": "weapon", "damage": 8, "desc": "Breaks after one hit"},

    # Utility
    "matchbox":          {"type": "utility", "desc": "Half-empty. Precious in the dark"},
    "flashlight":        {"type": "utility", "desc": "Beam cuts through the dark. Batteries unknown"},
    "signal flare":      {"type": "utility", "desc": "One shot. Make it count"},
    "binoculars":        {"type": "utility", "desc": "Scout ahead without getting close"},
    "lockpick set":      {"type": "utility", "desc": "For doors that won't budge"},
    "duct tape":         {"type": "utility", "desc": "Fixes everything. Almost"},
    "plastic tarp":      {"type": "utility", "desc": "Shelter, rain catch, or makeshift stretcher"},
    "rope":              {"type": "utility", "desc": "20 feet of nylon. Infinite uses"},
    "glow stick":        {"type": "utility", "desc": "Soft green glow. 8 hours"},
    "waterproof bag":    {"type": "utility", "desc": "Keeps gear dry"},
    "car battery":       {"type": "utility", "desc": "Heavy. Could power something"},
    "radio":             {"type": "utility", "desc": "Handheld two-way radio"},
    "military radio":    {"type": "utility", "desc": "Long-range military frequency radio"},
    "rubber boots":      {"type": "utility", "desc": "Keeps your feet dry in the sewers"},
    "gas mask":          {"type": "armor", "protection": 10, "desc": "Filters out the worst of it"},
    "hazmat suit":       {"type": "armor", "protection": 25, "desc": "Full body protection"},
    "body armor vest":   {"type": "armor", "protection": 20, "desc": "Kevlar. Stops bites too"},

    # Ammo
    "ammo clip":         {"type": "ammo", "rounds": 12, "desc": "9mm magazine"},
    "ammo box":          {"type": "ammo", "rounds": 30, "desc": "Mixed caliber box"},

    # Special
    "defibrillator":     {"type": "special", "desc": "Portable AED. Could save a life — or restart a heart that shouldn't beat"},
}


# ══════════════════════════════════════════════════════════════════
# EVENT SYSTEM
# ══════════════════════════════════════════════════════════════════

EVENT_POOL = {
    "exploration": [
        {
            "id": "scavenge", "weight": 30, "min_day": 1,
            "title": "Scavenging opportunity",
            "template": "You spot {item_hint} partially hidden nearby.",
        },
        {
            "id": "zombie_encounter", "weight": 25, "min_day": 1,
            "title": "Zombie encounter",
            "template": "A {zombie_type} stumbles into view, {zombie_desc}.",
        },
        {
            "id": "survivor_encounter", "weight": 15, "min_day": 2,
            "title": "Survivor encounter",
            "template": "A {survivor_desc} emerges from the shadows.",
        },
        {
            "id": "locked_door", "weight": 10, "min_day": 2,
            "title": "Locked door",
            "template": "A reinforced door blocks your path. {door_hint}.",
        },
        {
            "id": "environmental_hazard", "weight": 10, "min_day": 3,
            "title": "Environmental hazard",
            "template": "The {hazard_type} ahead looks dangerous.",
        },
        {
            "id": "quiet_moment", "weight": 10, "min_day": 1,
            "title": "A moment of calm",
            "template": "For once, nothing is trying to kill you. The silence feels {silence_desc}.",
        },
    ],
    "night": [
        {
            "id": "horde_passing", "weight": 30,
            "title": "Horde movement",
            "template": "The ground vibrates. A horde of {horde_size} shambles past your hiding spot.",
        },
        {
            "id": "night_visitor", "weight": 20,
            "title": "Midnight visitor",
            "template": "A knock at the {barrier}. Three slow raps. Then silence.",
        },
        {
            "id": "nightmare", "weight": 25,
            "title": "Nightmare",
            "template": "You jolt awake, drenched in sweat. The dream felt {dream_quality}.",
        },
        {
            "id": "night_noise", "weight": 15,
            "title": "Strange noise",
            "template": "A {noise_type} echoes from somewhere {direction}.",
        },
        {
            "id": "night_rest", "weight": 10,
            "title": "Restful sleep",
            "template": "You manage a few hours of unbroken sleep. A small mercy.",
        },
    ],
    "story": [
        {
            "id": "radio_signal",
            "trigger_day": 3, "once": True,
            "title": "Radio signal",
            "template": "Static crackles. Then a voice: 'If anyone can hear this... evacuation point Delta... bridge crossing... we leave at dawn on day fifteen. This is not a drill.'",
        },
        {
            "id": "first_horde",
            "trigger_day": 5, "once": True,
            "title": "The first horde",
            "template": "The street below fills with the dead. Hundreds. Moving east like a slow river of rot. Your location is no longer safe long-term.",
        },
        {
            "id": "military_broadcast",
            "trigger_day": 8, "once": True,
            "title": "Military broadcast",
            "template": "A military frequency crackles to life: 'Napalm strike on sectors 7 through 12. All survivors move north of the river. You have 72 hours.'",
        },
        {
            "id": "final_broadcast",
            "trigger_day": 13, "once": True,
            "title": "Final broadcast",
            "template": "The radio hisses one last time: 'Last helicopter. Dawn. Day fifteen. Bridge checkpoint. No exceptions.' Then silence forever.",
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

SURVIVOR_TYPES = [
    "woman clutching a baseball bat, eyes darting",
    "teenage boy with a bandaged arm, shaking",
    "old man with a hunting rifle and hollow cheeks",
    "pair of siblings, no older than twelve",
    "soldier in torn fatigues, thousand-yard stare",
    "nurse still in scrubs, hands stained red",
]

HAZARD_TYPES = ["collapsed overpass", "gas leak from a ruptured pipe", "flooded basement with sparking wires", "field of broken glass and tangled wire"]
SILENCE_DESCS = ["almost worse", "like a held breath", "suspicious", "fragile", "like the world forgot you"]
HORDE_SIZES = ["dozens", "at least fifty", "hundreds", "an endless column"]
BARRIER_TYPES = ["door", "barricade", "window shutter", "fire escape gate"]
DREAM_QUALITIES = ["too real", "like a memory you can't place", "like drowning in warm water", "like the world before"]
NOISE_TYPES = ["scream", "gunshot", "scraping sound", "child crying", "glass shattering"]
DIRECTIONS = ["below", "to the east", "above you", "very close", "far away but echoing"]


class EventSystem:
    def __init__(self):
        self.triggered_story = set()

    def generate_event(self, state: GameState) -> dict:
        events = []

        # Check story triggers
        for evt in EVENT_POOL["story"]:
            if (evt.get("trigger_day") == state.world.day
                    and evt["id"] not in self.triggered_story
                    and state.world.time_of_day == TimeOfDay.DAWN):
                self.triggered_story.add(evt["id"])
                return {
                    "id": evt["id"],
                    "title": evt["title"],
                    "description": evt["template"],
                    "is_story": True,
                }

        # Pick pool based on time
        pool_key = "night" if state.world.time_of_day == TimeOfDay.NIGHT else "exploration"
        pool = [e for e in EVENT_POOL[pool_key] if e.get("min_day", 0) <= state.world.day]

        if not pool:
            return {"id": "nothing", "title": "Silence", "description": "Nothing happens. Somehow that's worse.", "is_story": False}

        chosen = random.choices(pool, weights=[e["weight"] for e in pool], k=1)[0]
        description = self._fill_template(chosen, state)

        return {
            "id": chosen["id"],
            "title": chosen["title"],
            "description": description,
            "is_story": False,
        }

    def _fill_template(self, event: dict, state: GameState) -> str:
        template = event["template"]

        zt = random.choice(ZOMBIE_TYPES)
        loc = LOCATIONS.get(state.world.location, {})

        replacements = {
            "zombie_type": zt[0],
            "zombie_desc": zt[1],
            "survivor_desc": random.choice(SURVIVOR_TYPES),
            "item_hint": f"what looks like a {random.choice(loc.get('loot_table', ['something useful']))}" if loc.get("loot_table") else "something in the rubble",
            "hazard_type": random.choice(HAZARD_TYPES),
            "silence_desc": random.choice(SILENCE_DESCS),
            "horde_size": random.choice(HORDE_SIZES),
            "barrier": random.choice(BARRIER_TYPES),
            "dream_quality": random.choice(DREAM_QUALITIES),
            "noise_type": random.choice(NOISE_TYPES),
            "direction": random.choice(DIRECTIONS),
            "door_hint": "A lockpick set might help" if "lockpick set" not in state.player.inventory else "Your lockpick set could open this",
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
    def tick_survival(player: Player):
        """Per-turn resource drain."""
        player.hunger = max(0, player.hunger - random.randint(4, 7))
        player.thirst = max(0, player.thirst - random.randint(5, 9))
        player.stamina = max(0, player.stamina - random.randint(3, 6))

        if player.hunger <= 0:
            player.health -= random.randint(5, 10)
        if player.thirst <= 0:
            player.health -= random.randint(8, 15)
        if player.stamina <= 0:
            player.morale -= 5

        # Infection ticks
        if player.infection > 0:
            player.infection = min(100, player.infection + random.randint(1, 3))

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
        player_power = roll + player.skills["combat"] * 3 + weapon_bonus // 5
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
    def resolve_stealth(player: Player, threat_level: int) -> dict:
        roll = random.randint(1, 20)
        stealth_power = roll + player.skills["stealth"] * 3

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
        if (state.world.location == "Evacuation Zone"
                and state.world.day >= 15
                and state.world.time_of_day == TimeOfDay.DAWN):
            return GameOver.ESCAPED
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
        world.threat_level = min(10, base + time_mod + day_mod + random.randint(-1, 1))
        world.noise_level = max(0, world.noise_level - 1)


# ══════════════════════════════════════════════════════════════════
# LLM INTERFACE
# ══════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """You are the narrator of DEAD STATIC, a grim zombie apocalypse text adventure game.

VOICE & STYLE:
- Second person, present tense ("You hear...", "The door creaks...")
- Terse, Cormac McCarthy meets The Road. Short sentences. No purple prose.
- Show, don't tell. Describe what the player SEES, HEARS, SMELLS.
- Occasional dark humor is fine. Hope is rare and earned.
- Never break character. Never mention game mechanics directly.

STRICT RULES:
- Describe ONLY the current scene based on the provided game state.
- NEVER invent items the player doesn't have.
- NEVER advance the story beyond the current moment.
- NEVER claim the player did something they didn't choose.
- Keep responses between 80-200 words (before the choices).
- If the player is injured/infected, weave symptoms into the narration naturally.
- Adapt tone to morale: high morale = grim determination, low = despair creeping in.

CRITICAL — CHOICE FORMAT:
You MUST end EVERY response with EXACTLY 3 choices. Use this EXACT format with square brackets:

[A] First action option
[B] Second action option
[C] Third action option

Each choice must be a short, concrete action (5-15 words). One should be risky, one cautious.
Do NOT use any other format like "A)", "1.", "Option A:", or bullet points.
Do NOT put anything after the three choices.

EXAMPLE OUTPUT:
The hallway stretches ahead, dark and silent. Glass crunches under your boots. Something moved behind the far door — a shadow, quick and wrong. The air tastes like copper. Your flashlight flickers once, twice, then holds.

[A] Push through the door with weapon raised
[B] Retreat back the way you came
[C] Kill the flashlight and listen in the dark"""


def build_prompt(state: GameState, event: dict, action_context: str = "") -> str:
    p = state.player
    w = state.world
    loc = LOCATIONS.get(w.location, {})

    # Status summary
    status_warnings = []
    if p.health < 30: status_warnings.append("CRITICAL: Health dangerously low")
    if p.hunger < 20: status_warnings.append("Starving")
    if p.thirst < 20: status_warnings.append("Severely dehydrated")
    if p.infection > 0: status_warnings.append(f"Infection spreading ({p.infection}%)")
    if p.morale < 20: status_warnings.append("On the verge of breaking down")

    warnings_str = " | ".join(status_warnings) if status_warnings else "Stable"

    connections = loc.get("connections", [])

    prompt = f"""[GAME STATE]
Day {w.day} — {w.time_of_day.value} — {w.weather.value}
Location: {w.location} ({loc.get('description', '')})
Threat Level: {w.threat_level}/10
Connected Areas: {', '.join(connections)}

[PLAYER STATUS] {warnings_str}
Health: {p.health}/100 | Hunger: {p.hunger}/100 | Thirst: {p.thirst}/100
Stamina: {p.stamina}/100 | Morale: {p.morale}/100 | Infection: {p.infection}/100
Weapon: {p.equipped_weapon or 'bare hands'}
Inventory: {', '.join(p.inventory) if p.inventory else 'empty'}

[CURRENT EVENT]
{event['description']}

[RECENT HISTORY]
{chr(10).join(state.history[-Config.MAX_HISTORY:]) if state.history else 'You woke up alone in a ransacked apartment. The city outside is dead.'}
"""

    if action_context:
        prompt += f"\n[PLAYER ACTION]\n{action_context}\n\nNarrate the result of this action and present the next scene with 3 choices."
    else:
        prompt += "\nDescribe the current scene and present 3 choices."

    return prompt


class OllamaHelper:
    """Diagnostic and utility methods for Ollama backend."""

    BASE_URL = "http://localhost:11434"

    @staticmethod
    def is_running() -> bool:
        """Check if Ollama server is reachable."""
        if not HAS_REQUESTS:
            return False
        try:
            resp = requests.get(f"{OllamaHelper.BASE_URL}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def list_models() -> list:
        """Return list of installed model names, e.g. ['qwen2.5:3b', 'llama3.2:3b']."""
        if not HAS_REQUESTS:
            return []
        try:
            resp = requests.get(f"{OllamaHelper.BASE_URL}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            models = []
            for m in data.get("models", []):
                name = m.get("name", "") or m.get("model", "")
                if name:
                    models.append(name)
            return models
        except Exception:
            return []

    @staticmethod
    def try_start_server() -> bool:
        """Attempt to start Ollama server in the background."""
        import subprocess
        try:
            # Try common install locations on Windows, then PATH
            ollama_paths = ["ollama", "ollama.exe"]
            if os.name == 'nt':
                local_app = os.environ.get("LOCALAPPDATA", "")
                if local_app:
                    ollama_paths.insert(0, os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))
                program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
                ollama_paths.insert(1, os.path.join(program_files, "Ollama", "ollama.exe"))

            for path in ollama_paths:
                try:
                    subprocess.Popen(
                        [path, "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=0x00000008 if os.name == 'nt' else 0,  # DETACHED_PROCESS on Windows
                    )
                    # Wait for server to come up
                    for _ in range(10):
                        time.sleep(1)
                        if OllamaHelper.is_running():
                            return True
                    return False
                except FileNotFoundError:
                    continue
            return False
        except Exception:
            return False

    @staticmethod
    def validate_model(model_name: str) -> dict:
        """Check if a specific model is available. Returns status dict."""
        models = OllamaHelper.list_models()
        if not models:
            return {"valid": False, "reason": "no_models", "available": []}

        # Exact match
        if model_name in models:
            return {"valid": True, "model": model_name, "available": models}

        # Partial match (e.g., user has 'qwen2.5:3b-instruct' but config says 'qwen2.5:3b')
        partial = [m for m in models if model_name.split(":")[0] in m]
        if partial:
            return {"valid": False, "reason": "partial_match", "suggestions": partial, "available": models}

        return {"valid": False, "reason": "not_found", "available": models}

    @staticmethod
    def full_diagnostics() -> str:
        """Return a human-readable diagnostic string."""
        lines = []
        lines.append("─── Ollama Diagnostics ───")

        if not HAS_REQUESTS:
            lines.append("✗ 'requests' library not installed")
            return "\n".join(lines)

        if OllamaHelper.is_running():
            lines.append("✓ Ollama server is running")
        else:
            lines.append("✗ Ollama server is NOT running")
            lines.append("  → Try running 'ollama serve' in a terminal")
            return "\n".join(lines)

        models = OllamaHelper.list_models()
        if models:
            lines.append(f"✓ Installed models ({len(models)}):")
            for m in models:
                marker = " ◀ selected" if m == Config.OLLAMA_MODEL else ""
                lines.append(f"    • {m}{marker}")
        else:
            lines.append("✗ No models installed")
            lines.append("  → Run: ollama pull qwen2.5:3b")

        check = OllamaHelper.validate_model(Config.OLLAMA_MODEL)
        if check["valid"]:
            lines.append(f"✓ Selected model '{Config.OLLAMA_MODEL}' is ready")
        else:
            lines.append(f"✗ Selected model '{Config.OLLAMA_MODEL}' NOT FOUND")
            if check["reason"] == "partial_match":
                lines.append(f"  → Did you mean: {', '.join(check['suggestions'])}?")
            elif check["reason"] == "not_found":
                lines.append(f"  → Available: {', '.join(check['available'])}")
                lines.append(f"  → Run: ollama pull {Config.OLLAMA_MODEL}")

        return "\n".join(lines)


class LLMClient:
    def __init__(self):
        self.backend = Config.LLM_BACKEND
        self.llm = None

        if self.backend == "llama_cpp":
            if not HAS_LLAMA_CPP:
                raise ImportError("llama-cpp-python not installed. Run: pip install llama-cpp-python")
            self.llm = Llama(
                model_path=Config.GGUF_MODEL_PATH,
                n_ctx=Config.N_CTX,
                n_gpu_layers=Config.N_GPU_LAYERS,
                verbose=False,
            )
        elif self.backend == "ollama":
            if not HAS_REQUESTS:
                raise ImportError("requests not installed. Run: pip install requests")

    def generate(self, system: str, prompt: str) -> str:
        if self.backend == "ollama":
            return self._ollama_generate(system, prompt)
        elif self.backend == "llama_cpp":
            return self._llama_cpp_generate(system, prompt)
        else:
            raise ValueError(f"Unknown backend: {self.backend}")

    def _ollama_generate(self, system: str, prompt: str) -> str:
        payload = {
            "model": Config.OLLAMA_MODEL,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": Config.LLM_TEMPERATURE,
                "top_p": Config.LLM_TOP_P,
                "num_predict": Config.LLM_MAX_TOKENS,
            },
        }
        try:
            resp = requests.post(Config.OLLAMA_URL, json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except requests.ConnectionError:
            return "The silence stretches on. Your radio crackles but finds nothing.\n\n[A] Try again\n[B] Check connection\n[C] Quit"
        except requests.HTTPError as e:
            if resp.status_code == 404:
                return "Model 'dolphin-phi' not found. Run: ollama pull dolphin-phi\n\n[A] Try again\n[B] Retry\n[C] Quit"
            return f"Ollama error ({resp.status_code}). Check 'ollama list' in terminal.\n\n[A] Try again\n[B] Retry\n[C] Quit"
        except Exception as e:
            return f"LLM error: {e}\n\n[A] Try again\n[B] Retry\n[C] Quit"

    def _llama_cpp_generate(self, system: str, prompt: str) -> str:
        full_prompt = f"<|system|>\n{system}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>\n"
        output = self.llm(
            full_prompt,
            max_tokens=Config.LLM_MAX_TOKENS,
            temperature=Config.LLM_TEMPERATURE,
            top_p=Config.LLM_TOP_P,
            stop=["<|end|>", "<|user|>"],
        )
        return output["choices"][0]["text"].strip()


def parse_llm_output(raw: str, state: GameState = None) -> dict:
    """
    Extract narrative and choices from LLM output.
    Handles many format variations that local models produce:
      [A] text, A) text, A. text, A: text, **A** text,
      1. text, 1) text, - text, * text, numbered lists, etc.
    """
    if not raw or not raw.strip():
        return {
            "narrative": "The world holds its breath. Nothing moves.",
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
    if state is None:
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
        options["A"] = f"Head toward {target}"
    else:
        options["A"] = "Search the surrounding area"

    # Choice B: Context-sensitive
    if p.health < 40 and any(ITEMS.get(i, {}).get("type") == "medical" for i in p.inventory):
        med = next(i for i in p.inventory if ITEMS.get(i, {}).get("type") == "medical")
        options["B"] = f"Use your {med} to patch up"
    elif p.hunger < 30 and any(ITEMS.get(i, {}).get("type") == "food" for i in p.inventory):
        food = next(i for i in p.inventory if ITEMS.get(i, {}).get("type") == "food")
        options["B"] = f"Eat the {food}"
    elif p.thirst < 30 and any(ITEMS.get(i, {}).get("type") == "water" for i in p.inventory):
        water = next(i for i in p.inventory if ITEMS.get(i, {}).get("type") == "water")
        options["B"] = f"Drink the {water}"
    elif state.world.threat_level >= 6:
        options["B"] = "Find a hiding spot and stay quiet"
    else:
        options["B"] = "Scavenge for supplies nearby"

    # Choice C: Always a cautious/rest option
    if p.stamina < 30:
        options["C"] = "Find shelter and rest"
    elif state.world.time_of_day == TimeOfDay.NIGHT:
        options["C"] = "Barricade the entrance and sleep"
    else:
        options["C"] = "Stay put and observe your surroundings"

    return options


REPAIR_PROMPT = """Your previous response did not include action choices in the correct format.
Based on the scene you just described, provide EXACTLY 3 choices in this format:

[A] first action
[B] second action
[C] third action

Only output the three choices. Nothing else."""


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
            self.console.print("              A Zombie Apocalypse Text Adventure", style="dim white")
            self.console.print("              Powered by Local LLM\n", style="dim")
            self.console.print("    [1] New Game    [2] Load Game    [3] Settings    [Q] Quit\n", style="bold")
        else:
            print(title)
            print("              A Zombie Apocalypse Text Adventure")
            print("              Powered by Local LLM\n")
            print("    [1] New Game    [2] Load Game    [3] Settings    [Q] Quit\n")

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

        if HAS_RICH:
            # Top bar
            header = Text()
            header.append(f" DAY {w.day} ", style="bold white on red")
            header.append(f" {w.time_of_day.value} ", style="bold white on dark_red")
            header.append(f" {w.weather.value} ", style="dim")
            header.append(f" ☠ Threat: {w.threat_level}/10 ", style="bold red" if w.threat_level >= 7 else "yellow" if w.threat_level >= 4 else "green")
            self.console.print(header)

            # Location
            self.console.print(f" 📍 {w.location}", style="bold cyan")

            # Stats
            stats = Table(box=None, padding=(0, 1), show_header=False, expand=True)
            stats.add_column(width=25)
            stats.add_column(width=25)
            stats.add_column(width=25)

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
            inv_line = f"🔪 {p.equipped_weapon or 'bare hands'}  |  🎒 {len(p.inventory)}/{p.max_inventory}: {', '.join(p.inventory[:5])}"
            if len(p.inventory) > 5:
                inv_line += f" (+{len(p.inventory) - 5} more)"
            self.console.print(f" {inv_line}", style="dim")
            self.console.print("─" * 75, style="dim")
        else:
            print(f"\n═══ DAY {w.day} | {w.time_of_day.value} | {w.weather.value} | Threat: {w.threat_level}/10 ═══")
            print(f"Location: {w.location}")
            print(f"HP: {p.health} | Hunger: {p.hunger} | Thirst: {p.thirst} | Stamina: {p.stamina} | Morale: {p.morale} | Infection: {p.infection}")
            print(f"Weapon: {p.equipped_weapon or 'bare hands'} | Inventory: {', '.join(p.inventory) or 'empty'}")
            print("─" * 60)

    def print_narrative(self, text: str):
        if HAS_RICH:
            self.console.print(f"\n{text}\n", style="white")
        else:
            print(f"\n{text}\n")

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
        if HAS_RICH:
            self.console.print("\n\n")
            self.console.print("    ╔═══════════════════════════════════╗", style="bold red")
            self.console.print("    ║          Y O U   D I E D         ║", style="bold red")
            self.console.print("    ╚═══════════════════════════════════╝", style="bold red")
            self.console.print(f"\n    Survived {state.world.day} days.", style="dim")
            self.console.print(f"    Zombies killed: {state.player.kills}", style="dim")
            self.console.print(f"    People saved: {state.player.people_saved}", style="dim")
            self.console.print(f"    People left behind: {state.player.people_abandoned}\n", style="dim")
        else:
            print("\n\n    ═══ YOU DIED ═══")
            print(f"    Survived {state.world.day} days. Kills: {state.player.kills}")

    def print_infected_screen(self, state: GameState):
        self.clear()
        if HAS_RICH:
            self.console.print("\n\n")
            self.console.print("    ╔═══════════════════════════════════════════╗", style="bold green")
            self.console.print("    ║       Y O U   T U R N E D               ║", style="bold green")
            self.console.print("    ║   The infection claimed another soul.    ║", style="bold green")
            self.console.print("    ╚═══════════════════════════════════════════╝", style="bold green")
            self.console.print(f"\n    You lasted {state.world.day} days before losing yourself.", style="dim")
        else:
            print("\n\n    ═══ YOU TURNED ═══")
            print(f"    The infection won on day {state.world.day}.")

    def print_victory_screen(self, state: GameState):
        self.clear()
        if HAS_RICH:
            self.console.print("\n\n")
            self.console.print("    ╔═══════════════════════════════════════════╗", style="bold green")
            self.console.print("    ║       Y O U   E S C A P E D              ║", style="bold green")
            self.console.print("    ║   The helicopter lifts off at dawn.      ║", style="bold green")
            self.console.print("    ╚═══════════════════════════════════════════╝", style="bold green")
            self.console.print(f"\n    {state.world.day} days. {state.player.kills} kills. You made it.", style="bold white")
        else:
            print("\n\n    ═══ YOU ESCAPED ═══")
            print(f"    You survived {state.world.day} days and made it out.")

    def get_input(self, prompt_text: str = "> ") -> str:
        if HAS_RICH:
            return self.console.input(f"\n [bold white]{prompt_text}[/] ").strip()
        else:
            return input(f"\n{prompt_text}").strip()

    def print_loading(self):
        if HAS_RICH:
            self.console.print("\n  [dim]The dead city speaks...[/]", end="")
        else:
            print("\n  Thinking...", end="", flush=True)

    def print_help(self):
        help_text = """
COMMANDS (type during your turn):
  [A/B/C]    — Choose an action
  inventory  — View detailed inventory
  use <item> — Use an item (e.g., 'use canned beans')
  equip <item> — Equip a weapon
  map        — View known locations
  status     — Detailed player status
  save       — Save the game
  help       — Show this help
  quit       — Quit the game
        """
        if HAS_RICH:
            self.console.print(Panel(help_text.strip(), title="Help", border_style="cyan"))
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

    def initialize_llm(self):
        if Config.LLM_BACKEND == "ollama":
            return self._initialize_ollama()
        else:
            try:
                self.llm = LLMClient()
                return True
            except Exception as e:
                self.display.print_system_message(f"LLM init failed: {e}")
                return False

    def _initialize_ollama(self):
        """Initialize Ollama with auto-start and model validation."""
        self.display.print_system_message("Connecting to Ollama...")

        # Step 1: Check if Ollama is running, try to start if not
        if not OllamaHelper.is_running():
            self.display.print_system_message("Ollama not running. Attempting to start...")
            if OllamaHelper.try_start_server():
                self.display.print_system_message("Ollama started successfully.")
            else:
                self.display.print_system_message(
                    "Could not start Ollama automatically.\n"
                    "  → Please open a terminal and run: ollama serve\n"
                    "  → Then restart the game."
                )
                input("\n  Press Enter to exit...")
                return False

        # Step 2: Verify dolphin-phi is installed
        models = OllamaHelper.list_models()
        model_names = [m.split(":")[0] for m in models]

        if "dolphin-phi" not in model_names and Config.OLLAMA_MODEL not in models:
            self.display.print_system_message(
                f"Model '{Config.OLLAMA_MODEL}' is not installed.\n"
                f"  → Open a terminal and run: ollama pull dolphin-phi\n"
                f"  → Then restart the game."
            )
            input("\n  Press Enter to exit...")
            return False

        self.display.print_system_message(f"Using model: {Config.OLLAMA_MODEL}")

        # Step 3: Initialize the LLM client
        try:
            self.llm = LLMClient()
            return True
        except Exception as e:
            self.display.print_system_message(f"LLM init failed: {e}")
            return False

    def title_screen(self):
        self.display.clear()
        self.display.print_title_screen()

        while True:
            choice = self.display.get_input("Choose: ").strip()
            if choice == '1':
                self.new_game()
                return True
            elif choice == '2':
                if os.path.exists(Config.SAVE_FILE):
                    self.state, self.events = load_game()
                    self.display.print_system_message("Game loaded.")
                    return True
                else:
                    self.display.print_system_message("No save file found.")
            elif choice == '3':
                self.settings_menu()
            elif choice.upper() == 'Q':
                return False

    def new_game(self):
        self.state = GameState()
        self.events = EventSystem()

        self.display.clear()
        name = self.display.get_input("What is your name, survivor? ") or "Survivor"
        self.state.player.name = name

        self.display.print_system_message(f"Good luck, {name}. You'll need it.")
        time.sleep(1)

        # Opening flavor
        opening = (
            f"\nYou wake to the sound of distant screaming.\n"
            f"Day one. Or maybe two. Hard to tell anymore.\n"
            f"The apartment around you has been ransacked. Broken glass, overturned furniture,\n"
            f"and a barricaded door that won't hold forever.\n"
            f"Outside, the city of the dead stretches in every direction.\n"
            f"You need to survive. You need to find a way out.\n"
        )
        self.display.print_narrative(opening)

        # Starting items (random)
        starter_items = random.sample(["kitchen knife", "canned beans", "bottled water", "matchbox", "dirty bandage"], k=3)
        self.state.player.inventory = starter_items
        self.display.print_system_message(f"You find nearby: {', '.join(starter_items)}")

        input("\n  Press Enter to begin...")

    def settings_menu(self):
        self.display.clear()
        print(f"\n  LLM Backend: {Config.LLM_BACKEND}")
        print(f"  Model: {Config.OLLAMA_MODEL}")

        if Config.LLM_BACKEND == "ollama":
            if OllamaHelper.is_running():
                models = OllamaHelper.list_models()
                status = "✓ dolphin-phi installed" if any("dolphin-phi" in m for m in models) else "✗ dolphin-phi NOT installed — run: ollama pull dolphin-phi"
                print(f"  Status: {status}")
            else:
                print(f"  Status: ✗ Ollama not running — run: ollama serve")

        print(f"\n  [1] Run diagnostics")
        print(f"  [B] Back")

        choice = self.display.get_input("Choose: ").strip()
        if choice == '1':
            print(f"\n{OllamaHelper.full_diagnostics()}")
            input("\n  Press Enter to continue...")
            self.settings_menu()

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
            self.display.print_system_message("Game saved.")
            return True
        elif cmd.startswith("use "):
            item_name = cmd[4:].strip()
            result = self.rules.use_item(self.state.player, item_name)
            self.display.print_system_message(result["message"])
            return True
        elif cmd.startswith("equip "):
            item_name = cmd[6:].strip()
            if item_name in self.state.player.inventory:
                item = ITEMS.get(item_name, {})
                if item.get("type") == "weapon":
                    self.state.player.equipped_weapon = item_name
                    self.display.print_system_message(f"Equipped {item_name}.")
                else:
                    self.display.print_system_message(f"Can't equip {item_name} as a weapon.")
            else:
                self.display.print_system_message("You don't have that.")
            return True
        elif cmd == "quit" or cmd == "exit":
            save_q = self.display.get_input("Save before quitting? (y/n) ")
            if save_q.lower() == 'y':
                save_game(self.state, self.events)
            sys.exit(0)

        return False

    def _show_inventory(self):
        p = self.state.player
        if HAS_RICH:
            table = Table(title=f"Inventory ({len(p.inventory)}/{p.max_inventory})", box=box.SIMPLE)
            table.add_column("Item", style="cyan")
            table.add_column("Type", style="dim")
            table.add_column("Description", style="white")
            for item_name in p.inventory:
                item = ITEMS.get(item_name, {})
                equipped = " ⚔" if item_name == p.equipped_weapon else ""
                table.add_row(item_name + equipped, item.get("type", "?"), item.get("desc", ""))
            self.display.console.print(table)
        else:
            print(f"\nInventory ({len(p.inventory)}/{p.max_inventory}):")
            for item_name in p.inventory:
                item = ITEMS.get(item_name, {})
                eq = " [EQUIPPED]" if item_name == p.equipped_weapon else ""
                print(f"  - {item_name}{eq}: {item.get('desc', '')}")

    def _show_status(self):
        p = self.state.player
        if HAS_RICH:
            txt = f"""Name: {p.name}
Skills: Combat {p.skills['combat']:.0f} | Stealth {p.skills['stealth']:.0f} | Medical {p.skills['medical']:.0f} | Survival {p.skills['survival']:.0f} | Persuasion {p.skills['persuasion']:.0f}
Kills: {p.kills} | Saved: {p.people_saved} | Abandoned: {p.people_abandoned}
Days survived: {self.state.world.day}"""
            self.display.console.print(Panel(txt, title="Status", border_style="cyan"))
        else:
            print(f"\nName: {p.name}")
            print(f"Skills: {p.skills}")
            print(f"Kills: {p.kills} | Days: {self.state.world.day}")

    def _show_map(self):
        w = self.state.world
        current = w.location
        loc = LOCATIONS.get(current, {})
        connections = loc.get("connections", [])
        discovered = w.discovered_locations

        if HAS_RICH:
            lines = [f"[bold cyan]Current: {current}[/]", f"Connected:"]
            for c in connections:
                threat = LOCATIONS.get(c, {}).get("base_threat", "?")
                known = "✓" if c in discovered else "?"
                lines.append(f"  [{known}] {c} (base threat: {threat})")
            lines.append(f"\nDiscovered locations: {', '.join(discovered)}")
            self.display.console.print(Panel('\n'.join(lines), title="Map", border_style="cyan"))
        else:
            print(f"\nCurrent: {current}")
            print(f"Connections: {', '.join(connections)}")
            print(f"Discovered: {', '.join(discovered)}")

    def game_turn(self):
        """One full game turn."""
        # 1. Tick survival resources
        self.rules.tick_survival(self.state.player)

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

        # 5. Build prompt and call LLM
        prompt = build_prompt(self.state, event)
        self.display.print_loading()
        raw_output = self.llm.generate(SYSTEM_PROMPT, prompt)
        parsed = parse_llm_output(raw_output, self.state)

        # 5b. If parsing failed, try a repair prompt to get just the choices
        if parsed.get("parse_failed"):
            repair_input = raw_output + "\n\n" + REPAIR_PROMPT
            repair_raw = self.llm.generate(SYSTEM_PROMPT, repair_input)
            repair_parsed = parse_llm_output(repair_raw, self.state)
            if not repair_parsed.get("parse_failed"):
                # Keep original narrative, use repaired choices
                parsed["options"] = repair_parsed["options"]
                parsed["parse_failed"] = False
            else:
                # Still failed — context-aware fallbacks are already in place
                self.display.print_system_message("(Auto-generated choices for this turn)")

        # 6. Display narrative and choices
        self.display.print_narrative(parsed["narrative"])
        self.current_options = parsed["options"]
        self.display.print_choices(self.current_options)

        # 7. Player input loop
        while True:
            user_input = self.display.get_input("Your choice: ").strip()

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
                self.display.print_system_message("Invalid. Choose A, B, or C (or type 'help').")
                continue
            break

        chosen_action = self.current_options.get(choice_key, user_input)

        # 8. Resolve action mechanically
        action_context = chosen_action
        extra_context = []

        # Movement detection
        loc = LOCATIONS.get(self.state.world.location, {})
        for conn in loc.get("connections", []):
            if conn.lower() in chosen_action.lower():
                self.state.world.location = conn
                if conn not in self.state.world.discovered_locations:
                    self.state.world.discovered_locations.append(conn)
                extra_context.append(f"[Moved to {conn}]")
                break

        # Combat detection
        combat_keywords = ["fight", "attack", "kill", "shoot", "swing", "stab", "confront", "charge"]
        if any(kw in chosen_action.lower() for kw in combat_keywords):
            result = self.rules.resolve_combat(self.state.player, self.state.world.threat_level)
            extra_context.append(f"[Combat: {result['outcome']}. {result['narrative_hint']}]")
            self.state.world.noise_level += result.get("noise_generated", 0)

        # Stealth detection
        stealth_keywords = ["sneak", "hide", "stealth", "quiet", "avoid", "creep", "slip past"]
        if any(kw in chosen_action.lower() for kw in stealth_keywords):
            result = self.rules.resolve_stealth(self.state.player, self.state.world.threat_level)
            extra_context.append(f"[Stealth: {result['outcome']}. {result['narrative_hint']}]")

        # Scavenging / loot
        search_keywords = ["search", "loot", "scavenge", "look for", "check", "rummage", "open", "grab"]
        if any(kw in chosen_action.lower() for kw in search_keywords) and event["id"] in ("scavenge", "quiet_moment", "free_roam", "locked_door"):
            loc_data = LOCATIONS.get(self.state.world.location, {})
            if random.random() < loc_data.get("loot_chance", 0.2) and loc_data.get("loot_table"):
                found = random.choice(loc_data["loot_table"])
                if len(self.state.player.inventory) < self.state.player.max_inventory:
                    self.state.player.inventory.append(found)
                    extra_context.append(f"[Found: {found}]")
                else:
                    extra_context.append(f"[Spotted {found} but inventory is full]")

        # Rest detection
        rest_keywords = ["rest", "sleep", "camp", "wait", "recover"]
        if any(kw in chosen_action.lower() for kw in rest_keywords):
            stamina_restore = random.randint(15, 30)
            self.state.player.stamina = min(100, self.state.player.stamina + stamina_restore)
            morale_change = random.randint(-5, 10)
            self.state.player.morale = max(0, min(100, self.state.player.morale + morale_change))
            extra_context.append(f"[Rested. +{stamina_restore} stamina]")

        # 9. Update history
        summary = f"Day {self.state.world.day} {self.state.world.time_of_day.value}: {chosen_action}"
        if extra_context:
            summary += " " + " ".join(extra_context)
        self.state.history.append(summary)

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
            self.display.print_system_message("Could not initialize LLM. Check settings.")
            return

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

        input("\n  Press Enter to exit...")


# ══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    game = DeadStaticGame()
    game.run()
