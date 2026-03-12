# DEAD STATIC

**A single-player zombie apocalypse text adventure powered by a local LLM. No internet. No cloud. No escape.**

You wake up in a ransacked apartment. The city outside is dead. You have 15 days to reach the last evacuation helicopter — or join the horde.

Every playthrough is different. A local language model narrates your story in real time, responding to your choices with procedurally generated prose. The game logic keeps things grounded: combat is dice-and-skill, resources drain every turn, and infection is a slow clock you can't ignore.

Everything runs on your machine. The AI model ships with the game. No API keys, no accounts, no telemetry.

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **[Ollama](https://ollama.com)** installed and running
- **dolphin-phi** model pulled:

```bash
ollama pull dolphin-phi
```

### Run

```bash
pip install rich requests
python game.py
```

That's it. The game auto-detects Ollama and the model on startup.

---

## How It Works

### Architecture

```
Player Input
     |
     v
+--------------------+
|    Game Loop        |
|  +--------------+   |     +-----------+
|  | Event System |---+--->| Prompt     |-----> Local LLM (Ollama)
|  +--------------+   |    | Builder    |           |
|  | Rules Engine |   |    +-----------+            v
|  +--------------+   |                      +-----------+
|  | State Manager|<--+<--------------------| Output     |
|  +--------------+   |                      | Parser     |
+--------------------+                      +-----------+
     |
     v
  Rich TUI
```

**The LLM narrates. The code decides.** All state changes — damage, loot, movement, infection — are computed deterministically by the rules engine. The LLM receives structured game state and produces narrative text with player choices. An 8-strategy parser extracts choices from the model output, handling format variations that small local models produce. If parsing fails entirely, context-aware fallback choices are generated from game state.

### The 15-Day Structure

| Day | Event | Pressure |
|-----|-------|----------|
| 1-2 | Tutorial zone. Learn mechanics, scavenge nearby. | Low |
| 3 | **Radio signal** — evacuation point revealed. | Clock starts |
| 5 | **First horde** — starting area becomes unsafe. | Must move |
| 8 | **Military broadcast** — napalm strike incoming. Cross the river. | Forced migration |
| 13 | **Final broadcast** — last helicopter, dawn of day 15. | Endgame |
| 15 | Reach Evacuation Zone at dawn to win. | Now or never |

### Game Systems

**Survival** — Hunger, thirst, and stamina drain every turn. Hit zero and your health starts bleeding. Eat, drink, and rest to stay alive.

**Infection** — Zombie bites and scratches inject infection that ticks up each turn. Antibiotics slow it. The experimental antiviral in the Hospital Basement can nearly cure it. Hit 100% and you turn. Game over.

**Combat** — Skill-based with dice rolls. Your combat skill + weapon damage vs. threat level. Firearms hit hard but generate noise that attracts more zombies. Sometimes stealth is the smarter play.

**Morale** — Tracks your psychological state. Affects narrative tone: high morale reads as grim determination, low morale as creeping despair. Moral choices (saving or abandoning survivors) push it in different directions.

**Exploration** — 14 interconnected locations from the starting apartment to the evacuation zone. Each has its own threat level, loot table, and connections. Some locations are locked behind the story progression.

### Content

- **14 locations** — apartments, streets, hospitals, sewers, a military checkpoint, and the final evacuation zone
- **45 items** across 8 types — food, water, weapons, medical supplies, armor, ammo, utilities, and one experimental antiviral
- **15 event types** — 6 exploration, 5 night, 4 story-driven
- **5 skills** — combat, stealth, medical, survival, persuasion (improve through use)
- **3 endings** — death, infection (you turn), or escape

---

## Controls

| Input | Action |
|-------|--------|
| `A` / `B` / `C` | Choose a narrative option |
| `inventory` | View items with descriptions |
| `use <item>` | Consume food, medicine, etc. |
| `equip <item>` | Set active weapon |
| `map` | View discovered locations and connections |
| `status` | Skills, kill count, days survived |
| `save` | Save to `dead_static_save.json` |
| `help` | Full command list |
| `quit` | Save and exit |

---

## Building a Distributable Package

Three scripts handle packaging into a standalone Windows release:

### Step 1 — Compile to exe

```bash
pip install pyinstaller
python build.py
```

Produces `dist/DeadStatic/DeadStatic.exe` with all Python dependencies.

### Step 2 — Bundle Ollama + model

```bash
python package.py
```

Automatically locates your `ollama.exe` and extracts **only the dolphin-phi model blobs** (not your entire model library). Creates:

```
release/DeadStatic/
  DeadStatic.exe
  _internal/
  ollama/
    ollama.exe
  models/
    manifests/...
    blobs/...        (only dolphin-phi layers)
  Play DeadStatic.bat
  README.txt
```

The `Play DeadStatic.bat` launcher handles everything: starts Ollama, waits for it to be ready, launches the game, and shuts Ollama down on exit.

Compress this folder to `.zip` and distribute.

### Step 3 (optional) — Windows installer

Install [Inno Setup](https://jrsoftware.org/isinfo.php), open `installer.iss`, and build. Produces a single `DeadStatic_Setup.exe` with desktop shortcuts and uninstaller.

---

## Configuration

All settings are in the `Config` class at the top of `game.py`:

```python
class Config:
    LLM_BACKEND = "ollama"
    OLLAMA_URL = "http://localhost:11434/api/generate"
    OLLAMA_MODEL = "dolphin-phi"
    GGUF_MODEL_PATH = "./model.gguf"    # for llama.cpp backend
    LLM_TEMPERATURE = 0.8
    LLM_MAX_TOKENS = 400
    MAX_HISTORY = 8                     # turns of context sent to LLM
```

### Using a different model

Change `OLLAMA_MODEL` to any Ollama-compatible model. Recommended:

| Model | Size | Notes |
|-------|------|-------|
| `dolphin-phi` | ~1.6 GB | Default. Fast, decent English. |
| `llama3.2:3b` | ~2 GB | Better coherence, slightly slower. |
| `qwen2.5:3b` | ~2 GB | Strong instruction following. |
| `mistral:7b` | ~4 GB | Best quality, needs more RAM. |

### Using llama.cpp instead of Ollama

```bash
pip install llama-cpp-python
```

Set `LLM_BACKEND = "llama_cpp"` and point `GGUF_MODEL_PATH` to a `.gguf` file. No Ollama needed.

---

## Extending the Game

### Add a location

Add an entry to the `LOCATIONS` dict:

```python
"Gas Station": {
    "type": "building",
    "base_threat": 5,
    "description": "Pumps are dry. The convenience store window is smashed.",
    "connections": ["Main Street"],       # link to existing locations
    "loot_table": ["energy bar", "matchbox", "glass bottle"],
    "loot_chance": 0.4,
},
```

Then add `"Gas Station"` to the `connections` list of `Main Street` (or wherever it should connect).

### Add an item

Add an entry to the `ITEMS` dict:

```python
"molotov cocktail": {
    "type": "weapon",
    "damage": 35,
    "noise": 6,
    "desc": "Glass bottle, gasoline, rag. One throw.",
},
```

Items are automatically available in loot tables that reference them by name.

### Add an event

Add to the relevant pool in `EVENT_POOL`:

```python
{
    "id": "trapped_survivor",
    "weight": 15,
    "min_day": 4,
    "title": "Cries for help",
    "template": "Someone is screaming behind a collapsed wall. You could try to dig them out.",
},
```

### Change the narrator voice

Edit `SYSTEM_PROMPT`. The current style is terse and Cormac McCarthy-inspired. You could change it to pulpy horror, dark comedy, military thriller, or anything else — the game mechanics stay the same regardless.

---

## Project Structure

```
game.py           Main game — all systems in a single file (~1800 lines)
build.py          PyInstaller build script
package.py        Bundles exe + Ollama + dolphin-phi model
installer.iss     Inno Setup script for Windows installer
requirements.txt  Python dependencies
```

### Why a single file?

Portability. The entire game is one `game.py` you can run anywhere with Python + Ollama. The multi-file packaging (`build.py`, `package.py`) is only for distribution.

---

## System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| OS | Windows 10 / Linux / macOS | Same |
| RAM | 4 GB | 8 GB |
| Disk | ~2 GB (model + game) | Same |
| GPU | Not required | NVIDIA GPU for faster inference |
| Internet | Not required | Only for initial `ollama pull` |

---

## License

MIT

---

*No data leaves your machine. The dead don't need your analytics.*
