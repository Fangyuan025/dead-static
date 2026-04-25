"""
package.py — Bundle DeadStatic.exe + llama-server runtime + GGUF model
               into a fully self-contained distributable package.

Run AFTER build.py:
    python package.py

This creates:
    release/DeadStatic/
        DeadStatic.exe          — The game (from PyInstaller)
        _internal/              — Python dependencies (from PyInstaller)
        runtime/                — llama-server.exe + CUDA libs
        models/                 — GGUF Q4 quantized model
        Play DeadStatic.bat     — Double-click to play
        README.txt              — Player instructions

Prerequisites:
    1. Run build.py first
    2. Run game.py once (to auto-download runtime + model)
       OR manually place files in runtime/ and models/
"""

import os
import sys
import shutil


# ── Configuration ──

GAME_NAME = "DeadStatic"
DIST_DIR = os.path.join("dist", GAME_NAME)       # PyInstaller output
RELEASE_DIR = os.path.join("release", GAME_NAME)  # Final package
RUNTIME_DIR = "runtime"
MODEL_DIR = "models"
GGUF_FILENAME = "Huihui-Qwen3.5-2B-abliterated.Q4_K_M.gguf"


def get_dir_size(path: str) -> str:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.isfile(fp):
                total += os.path.getsize(fp)
    if total > 1_000_000_000:
        return f"{total / 1_000_000_000:.1f} GB"
    return f"{total / 1_000_000:.0f} MB"


def package():
    print("\n══════════════════════════════════════")
    print("  DEAD STATIC — Packaging Tool")
    print("══════════════════════════════════════\n")

    # ── Step 1: Check PyInstaller output ──
    print("[1/5] Checking build output...")
    if not os.path.isdir(DIST_DIR):
        print(f"  ✗ Build output not found at {DIST_DIR}")
        print(f"    → Run 'python build.py' first")
        sys.exit(1)
    print(f"  ✓ Build output found")

    # ── Step 2: Check runtime ──
    print("\n[2/5] Checking llama-server runtime...")
    server_exe = os.path.join(RUNTIME_DIR, "llama-server.exe")
    if not os.path.isfile(server_exe):
        print(f"  ✗ llama-server.exe not found in {RUNTIME_DIR}/")
        print(f"    → Run the game once (python game.py) to auto-download")
        sys.exit(1)
    print(f"  ✓ llama-server found ({get_dir_size(RUNTIME_DIR)})")

    # ── Step 3: Check model ──
    print("\n[3/5] Checking GGUF model...")
    model_file = os.path.join(MODEL_DIR, GGUF_FILENAME)
    if not os.path.isfile(model_file):
        print(f"  ✗ Model not found: {model_file}")
        print(f"    → Run the game once (python game.py) to auto-download")
        sys.exit(1)
    model_size = os.path.getsize(model_file)
    print(f"  ✓ Model found ({model_size / 1_000_000_000:.2f} GB)")

    # ── Step 4: Assemble release ──
    print("\n[4/5] Assembling release package...")
    if os.path.exists(RELEASE_DIR):
        shutil.rmtree(RELEASE_DIR)
    os.makedirs(RELEASE_DIR)

    # 4a: Copy game exe + Python deps
    print("  Copying game files...")
    shutil.copytree(DIST_DIR, RELEASE_DIR, dirs_exist_ok=True)

    # 4b: Copy runtime (llama-server + DLLs)
    print("  Copying llama-server runtime...")
    runtime_dest = os.path.join(RELEASE_DIR, "runtime")
    shutil.copytree(RUNTIME_DIR, runtime_dest)

    # 4c: Copy model
    print(f"  Copying model ({GGUF_FILENAME})...")
    model_dest = os.path.join(RELEASE_DIR, "models")
    os.makedirs(model_dest, exist_ok=True)
    shutil.copy2(model_file, os.path.join(model_dest, GGUF_FILENAME))

    # 4d: Create launcher
    print("  Creating launcher...")
    with open(os.path.join(RELEASE_DIR, "Play DeadStatic.bat"), "w", encoding="ascii") as f:
        f.write(LAUNCHER_BAT)

    # 4e: Create README
    with open(os.path.join(RELEASE_DIR, "README.txt"), "w", encoding="ascii") as f:
        f.write(PLAYER_README)

    # ── Step 5: Summary ──
    pkg_size = get_dir_size(RELEASE_DIR)
    print(f"\n══════════════════════════════════════")
    print(f"  ✓ PACKAGING COMPLETE")
    print(f"══════════════════════════════════════")
    print(f"  Output: {os.path.abspath(RELEASE_DIR)}")
    print(f"  Size:   {pkg_size}")
    print(f"  Contents:")
    for item in sorted(os.listdir(RELEASE_DIR)):
        item_path = os.path.join(RELEASE_DIR, item)
        if os.path.isdir(item_path):
            print(f"    [DIR]  {item}/  ({get_dir_size(item_path)})")
        else:
            size_kb = os.path.getsize(item_path) / 1024
            print(f"    [FILE] {item}  ({size_kb:.0f} KB)")
    print(f"\n  ▸ Players double-click 'Play DeadStatic.bat' to start")
    print(f"  ▸ Everything is self-contained — no install needed")
    print(f"  ▸ Compress to .zip for distribution\n")


LAUNCHER_BAT = r"""@echo off
chcp 65001 >nul 2>&1
title DEAD STATIC
cd /d "%~dp0"

echo.
echo  ====================================================================
echo   DEAD STATIC - A Zombie Apocalypse Text Adventure
echo  ====================================================================
echo.

:: -- Check files --
if not exist "DeadStatic.exe" (
    echo  [ERROR] DeadStatic.exe not found. Make sure all files are extracted.
    pause & exit /b 1
)

echo  Launching game...
echo.
DeadStatic.exe

echo.
echo  Thanks for playing. Stay alive out there.
echo.
pause
"""


PLAYER_README = """
DEAD STATIC -- A Zombie Apocalypse Text Adventure
===================================================

HOW TO PLAY:
    Double-click "Play DeadStatic.bat"
    That's it. Everything is bundled. No install needed.

CONTROLS:
    A / B / C    -- Choose an action
    inventory    -- View your items
    use <item>   -- Use an item (e.g., "use canned beans")
    equip <item> -- Equip a weapon (e.g., "equip machete")
    map          -- View known locations
    status       -- Detailed stats
    save         -- Save your progress
    help         -- Show all commands
    quit         -- Save and exit

TIPS:
    - Hunger and thirst drain every turn. Eat and drink regularly.
    - Infection is a death sentence without medicine. Avoid bites.
    - Firearms are powerful but the noise attracts more zombies.
    - Day 15 is the last helicopter. Reach the Evacuation Zone by dawn.
    - Save often. The dead don't give second chances.

SYSTEM REQUIREMENTS:
    - Windows 10 or later
    - 4 GB RAM minimum (8 GB recommended)
    - ~1.5 GB disk space
    - NVIDIA GPU optional (auto-detected, CPU works fine)
    - No internet required (everything is bundled)

Made with local AI. No data leaves your computer. Ever.
"""


if __name__ == "__main__":
    package()
