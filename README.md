<div align="center">

**[English](README.md)** | **[中文](README_zh.md)**

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
pip install -r requirements.txt
python game.py
```

On first launch, the game automatically downloads:
1. **llama-server** (~200 MB, CUDA or CPU build auto-detected)
2. **AI model** (~1.4 GB, Q5_K_M quantized GGUF)

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

**Model:** [Josiefied-Qwen3-1.7B-abliterated-v1](https://huggingface.co/mradermacher/Josiefied-Qwen3-1.7B-abliterated-v1-GGUF) (Q5_K_M quantization, 1.4 GB)

### Episodic Memory (RAG)

The 1.7B model has a tight context window — without help, a 14-day playthrough forgets what happened on day 3 by day 10. DEAD STATIC solves this with a lightweight **RAG (Retrieval-Augmented Generation) layer**:

1. **At the end of every turn**, a second, compact LLM call summarizes what just happened in one sentence (≤ 40 chars Chinese / ≤ 20 words English). Adds ~0.2–0.4s per turn.
2. The summary is tokenized (jieba for Chinese, whitespace for English) and stored in a local **BM25 index** under `rag_data/`.
3. **At the start of every turn**, the game queries that index with `(location + weather + time + current action)` and injects the top-3 relevant past memories into the prompt as "Past echoes".
4. **Revisit detection**: if the player returns to a location they've been to before, a strong imperative is added — *"You've been here before. Last time: [summary]. Start with 'again' and echo what happened."* — so the model actually uses the memory instead of ignoring it.

**Result:** on a revisit to a location 10 turns later, the narrative opens with "You return again..." and carries forward specific details from the earlier visit — antibiotics you found, the growl down the hallway, the NPC you helped.

Both toggles live in the settings menu:
- **Story memory (RAG)** — the retrieval layer itself (on by default)
- **LLM summary** — use a 2nd LLM call for sharper summaries (on by default; disable if the extra latency bothers you — the mechanical fallback still works)

Implementation: `rag/episodic.py` (~310 lines, BM25 + jieba, no heavy deps) and `rag/summarizer.py` (~100 lines). Zero additional downloads.

### Static Lore Corpus

Retrieval of past turns only solves half the problem. The other half is **consistency in the world itself** — the apartment should feel like the same apartment across visits, the sewer tunnels should sound like sewer tunnels. A small model left on its own tends to reinvent every scene.

DEAD STATIC ships a hand-authored lore corpus: 28 per-location flavor entries (14 locations × 2) plus 12 weather/time atmosphere fragments. Every entry carries optional `weather` and `time` tags.

On every turn the game:

1. **Hard-filters** by the current scene — an entry is a candidate only if its location matches (or is a `*` atmosphere wildcard), its weather list matches, and its time list matches.
2. **Ranks** survivors by weighted token-overlap against the current `(location + weather + time + event + last action)`. Stopwords and single-character CJK particles are stripped so signal terms (走廊, monitor, banner) dominate.
3. **Injects** top-2 as a `Scene reference` section placed right before the event line, with a directive: *"borrow imagery and vocabulary — do not copy verbatim."*

Concrete effect: on **Hospital / Night**, the model sees lore about "a cardiac monitor beeping, a wheelchair turning of its own accord" and weaves that imagery in; on **Rooftop / Clear / Night**, it sees "the Milky Way along the horizon, a door slamming far away"; on **Sewer Tunnels / Rain**, "water rising to mid-calf, breathing-like rhythms in a distant pipe." The world stops amnesia-resetting on every scene change.

Toggle **Scene lore** in the settings menu (on by default). Implementation: `rag/lore.py` (~180 lines) + `rag/corpus/lore_data.py` (the hand-authored content). Static data — loaded once at startup, no disk I/O during play.

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
    *.Q5_K_M.gguf       (~1.4 GB)
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
    HF_REPO_ID = "mradermacher/Josiefied-Qwen3-1.7B-abliterated-v1-GGUF"
    GGUF_FILENAME = "Josiefied-Qwen3-1.7B-abliterated-v1.Q5_K_M.gguf"
    N_CTX = 4096              # context window size
    N_GPU_LAYERS = 99         # layers to offload to GPU
    SERVER_PORT = 8384        # local server port
    LLM_TEMPERATURE = 0.8
    LLM_MAX_TOKENS = 400
```

### Using a different quantization

| File | Size | Notes |
|------|------|-------|
| `...Q3_K_M.gguf` | 1.0 GB | Smallest practical. |
| `...Q4_K_M.gguf` | 1.2 GB | Faster, smaller. |
| `...Q5_K_M.gguf` | 1.4 GB | Default. Better quality at modest size bump. |
| `...Q6_K.gguf`   | 1.5 GB | Higher quality. |
| `...Q8_0.gguf`   | 1.9 GB | Near-lossless. |

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
game.py                Main game — all systems in a single file (~2600 lines)
rag/
  episodic.py          BM25 + jieba episodic memory store
  summarizer.py        LLM turn-summarizer
  lore.py              Static lore retrieval (tag-filtered token overlap)
  corpus/
    lore_data.py       Hand-authored per-location flavor + atmosphere
build.py               PyInstaller build script
package.py             Bundles exe + llama-server + GGUF model
installer.iss          Inno Setup script for Windows installer
requirements.txt       Python dependencies
test_rag.py            Headless unit tests for episodic RAG (18 cases)
test_lore.py           Headless unit tests for the lore corpus (26 cases)
test_state_prompt.py   Headless unit tests for prompt builder — graded
                       state, inventory grounding, action primacy, outcome
                       physicalization, fabrication guard (76 cases)
test_summarizer.py     Summarizer-quality tests against live llama-server
test_rag_live.py       End-to-end episodic RAG scripted playthrough (9 cases)
test_lore_live.py      End-to-end lore injection playthrough (14 cases)
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
