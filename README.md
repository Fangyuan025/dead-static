<div align="center">

```
 ██████╗ ███████╗ █████╗ ██████╗     ███████╗████████╗ █████╗ ████████╗██╗ ██████╗
 ██╔══██╗██╔════╝██╔══██╗██╔══██╗    ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔════╝
 ██║  ██║█████╗  ███████║██║  ██║    ███████╗   ██║   ███████║   ██║   ██║██║     
 ██║  ██║██╔══╝  ██╔══██║██║  ██║    ╚════██║   ██║   ██╔══██║   ██║   ██║██║     
 ██████╔╝███████╗██║  ██║██████╔╝    ███████║   ██║   ██║  ██║   ██║   ██║╚██████╗
 ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝     ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝
```

**A single-player zombie apocalypse text adventure powered by a local LLM.**

**No cloud. No API keys. No install. No escape.**

</div>

You wake up in a ransacked apartment. The city outside is dead. You have 15 days to reach the last evacuation helicopter — or join the horde.

Every playthrough is different. A local language model narrates your story in real time, responding to your choices with procedurally generated prose. The game logic keeps things grounded: combat is dice-and-skill, resources drain every turn, and infection is a slow clock you can't ignore.

Everything runs on your machine. The AI engine ([llama.cpp](https://github.com/ggml-org/llama.cpp)) and model (Q4 quantized GGUF, ~1 GB) are bundled with the game or auto-downloaded on first launch. No Python, no drivers, no configuration.

---

## Quick Start

### For players (packaged release)

Double-click **`Play DeadStatic.bat`**. That's it.

### For developers (from source)

```bash
pip install rich requests huggingface-hub
python game.py
```

On first launch, the game automatically downloads:
1. **llama-server** (~200 MB, CUDA or CPU build auto-detected)
2. **AI model** (~1.05 GB, Q4 quantized GGUF)

After that, no internet is needed.

---

## How It Works

### Architecture

```
Player Input
     |
     v
+--------------------+
|    Game Loop        |
|  +--------------+   |     +-----------+     +------------------+
|  | Event System |---+--->| Prompt     |---->| llama-server.exe |
|  +--------------+   |    | Builder    |     | (subprocess)     |
|  | Rules Engine |   |    +-----------+     | HTTP API         |
|  +--------------+   |          ^            +------------------+
|  | State Manager|<--+---------+--- parsed output
|  +--------------+   |
+--------------------+
     |
     v
  Rich TUI
```

**The LLM narrates. The code decides.** All state changes — damage, loot, movement, infection — are computed deterministically by the rules engine. The LLM receives structured game state and produces narrative text with player choices.

The game starts `llama-server.exe` as a background subprocess and communicates via its OpenAI-compatible HTTP API. The server auto-shuts down when the game exits. NVIDIA GPUs are auto-detected for CUDA acceleration; CPU mode works fine too.

**Model:** [Josiefied-Qwen3-1.7B-abliterated-v1](https://huggingface.co/Goekdeniz-Guelmez/Josiefied-Qwen3-1.7B-abliterated-v1-gguf) (Q4_0 quantization, 1.05 GB)

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

**Survival** — Hunger, thirst, and stamina drain every turn. Hit zero and your health starts bleeding.

**Infection** — Zombie bites inject infection that ticks up each turn. Hit 100% and you turn.

**Combat** — Skill-based with dice rolls. Firearms hit hard but generate noise that attracts more zombies.

**Morale** — Tracks your psychological state. Moral choices push it in different directions.

**Exploration** — 14 interconnected locations with threat levels, loot tables, and connections.

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

### Step 1 — Compile to exe

```bash
pip install pyinstaller
python build.py
```

### Step 2 — Bundle with runtime + model

```bash
python package.py
```

This requires the runtime and model to be downloaded first (run `python game.py` once).

Creates a fully self-contained release folder:

```
release/DeadStatic/
  DeadStatic.exe
  _internal/
  runtime/
    llama-server.exe    + CUDA DLLs
  models/
    *.q4_0.gguf         (~1.05 GB)
  Play DeadStatic.bat
  README.txt
```

Compress to `.zip` and distribute. Players just unzip and double-click.

### Step 3 (optional) — Windows installer

Install [Inno Setup](https://jrsoftware.org/isinfo.php), open `installer.iss`, and build.

---

## Configuration

All settings are in the `Config` class at the top of `game.py`:

```python
class Config:
    HF_REPO_ID = "Goekdeniz-Guelmez/Josiefied-Qwen3-1.7B-abliterated-v1-gguf"
    GGUF_FILENAME = "josiefied-qwen3-1.7b-abliterated-v1.q4_0.gguf"
    N_CTX = 4096              # context window size
    N_GPU_LAYERS = 99         # layers to offload to GPU
    SERVER_PORT = 8384        # local server port
    LLM_TEMPERATURE = 0.8
    LLM_MAX_TOKENS = 400
```

### Using a different quantization

| File | Size | Notes |
|------|------|-------|
| `...q4_0.gguf` | 1.05 GB | Default. Fast, small. |
| `...q5_0.gguf` | 1.23 GB | Better quality. |
| `...q6_k.gguf` | 1.42 GB | Good balance. |
| `...q8_0.gguf` | 1.83 GB | Near-lossless. |

Change `GGUF_FILENAME` in `Config`.

---

## Extending the Game

### Add a location

```python
"Gas Station": {
    "type": "building",
    "base_threat": 5,
    "description": "Pumps are dry. The convenience store window is smashed.",
    "connections": ["Main Street"],
    "loot_table": ["energy bar", "matchbox", "glass bottle"],
    "loot_chance": 0.4,
},
```

### Add an item

```python
"molotov cocktail": {
    "type": "weapon",
    "damage": 35,
    "noise": 6,
    "desc": "Glass bottle, gasoline, rag. One throw.",
},
```

### Change the narrator voice

Edit `SYSTEM_PROMPT`. The game mechanics stay the same regardless of narrative style.

---

## Project Structure

```
game.py           Main game — all systems in a single file (~1800 lines)
build.py          PyInstaller build script
package.py        Bundles exe + llama-server + GGUF model
installer.iss     Inno Setup script for Windows installer
requirements.txt  Python dependencies (rich, requests, huggingface-hub)
```

---

## System Requirements

| | Minimum | Recommended |
|---|---------|-------------|
| OS | Windows 10 x64 | Same |
| RAM | 4 GB | 8 GB |
| Disk | ~1.5 GB | Same |
| GPU | Not required | NVIDIA GPU (auto-detected) |
| Internet | First launch only | Not needed if bundled |

---

## License

MIT

---

*No data leaves your machine. The dead don't need your analytics.*
