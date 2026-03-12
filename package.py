"""
package.py — Bundle DeadStatic.exe + Ollama + dolphin-phi model into a distributable package.

Run AFTER build.py:
    python package.py

This creates:
    release/DeadStatic/
        DeadStatic.exe          — The game (from PyInstaller)
        _internal/              — Python dependencies (from PyInstaller)
        ollama/
            ollama.exe          — Ollama binary
        models/                 — Pre-downloaded dolphin-phi model
        launcher.bat            — Double-click to play (starts Ollama → game → cleanup)
        README.txt              — Player instructions

Prerequisites:
    1. Run build.py first
    2. Ollama must be installed (ollama.exe accessible)
    3. dolphin-phi must be pulled (ollama pull dolphin-phi)
"""

import os
import sys
import shutil
import subprocess
import glob


# ── Configuration ──

GAME_NAME = "DeadStatic"
DIST_DIR = os.path.join("dist", GAME_NAME)       # PyInstaller output
RELEASE_DIR = os.path.join("release", GAME_NAME)  # Final package


def find_ollama_exe() -> str:
    """Find ollama.exe on this system."""
    # Check common locations
    candidates = []

    # PATH
    ollama_path = shutil.which("ollama")
    if ollama_path:
        candidates.append(ollama_path)

    # Windows default install locations
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            candidates.append(os.path.join(local_app, "Programs", "Ollama", "ollama.exe"))

        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates.append(os.path.join(program_files, "Ollama", "ollama.exe"))

        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "ollama.exe"))

    for c in candidates:
        if c and os.path.isfile(c):
            print(f"  ✓ Found ollama at: {c}")
            return c

    return ""


def find_model_dir() -> str:
    """Find the Ollama models directory containing dolphin-phi."""
    # Check OLLAMA_MODELS env var first
    env_models = os.environ.get("OLLAMA_MODELS", "")
    if env_models and os.path.isdir(env_models):
        return env_models

    # Default locations
    candidates = []
    if os.name == "nt":
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile:
            candidates.append(os.path.join(user_profile, ".ollama", "models"))
    else:
        home = os.path.expanduser("~")
        candidates.append(os.path.join(home, ".ollama", "models"))

    for c in candidates:
        if os.path.isdir(c):
            # Verify dolphin-phi exists in manifests
            manifest_path = os.path.join(c, "manifests", "registry.ollama.ai", "library", "dolphin-phi")
            if os.path.exists(manifest_path):
                print(f"  Found dolphin-phi model at: {c}")
                return c
            else:
                print(f"  Models dir found at {c} but dolphin-phi not installed")
                print(f"    -> Run: ollama pull dolphin-phi")
                return ""

    return ""


def copy_single_model(model_dir: str, dest_dir: str, model_name: str = "dolphin-phi"):
    """
    Copy only the specified model from Ollama's model storage.

    Ollama stores models as:
        models/
          manifests/registry.ollama.ai/library/<model>/<tag>   (JSON manifest)
          blobs/sha256-<hex>                                    (content-addressed layers)

    This reads the manifest to find which blobs belong to the model,
    then copies only those blobs instead of the entire blobs/ directory.
    """
    import json as _json

    manifest_base = os.path.join(model_dir, "manifests", "registry.ollama.ai", "library", model_name)
    blobs_dir = os.path.join(model_dir, "blobs")

    if not os.path.isdir(manifest_base):
        print(f"  ERROR: Manifest not found for '{model_name}' at {manifest_base}")
        return False

    # ── Step 1: Copy manifest directory ──
    dest_manifest = os.path.join(dest_dir, "manifests", "registry.ollama.ai", "library", model_name)
    os.makedirs(dest_manifest, exist_ok=True)

    # Find all tags (usually just "latest")
    required_blobs = set()
    tag_count = 0

    for tag_file in os.listdir(manifest_base):
        tag_path = os.path.join(manifest_base, tag_file)
        if not os.path.isfile(tag_path):
            continue

        # Copy the tag manifest file
        shutil.copy2(tag_path, os.path.join(dest_manifest, tag_file))
        tag_count += 1

        # Parse manifest to find blob digests
        try:
            with open(tag_path, "r", encoding="utf-8") as f:
                manifest = _json.load(f)

            # Collect all referenced digests
            # Config layer
            config = manifest.get("config", {})
            if config.get("digest"):
                required_blobs.add(config["digest"])

            # Model layers (weights, template, license, params, etc.)
            for layer in manifest.get("layers", []):
                if layer.get("digest"):
                    required_blobs.add(layer["digest"])

        except (ValueError, KeyError) as e:
            print(f"  WARNING: Could not parse manifest '{tag_file}': {e}")
            # Fallback: copy all blobs if we can't parse
            print(f"  Falling back to copying all blobs...")
            dest_blobs = os.path.join(dest_dir, "blobs")
            shutil.copytree(blobs_dir, dest_blobs)
            return True

    print(f"  Found {tag_count} tag(s), {len(required_blobs)} blob(s) to copy")

    # ── Step 2: Copy only the required blobs ──
    dest_blobs = os.path.join(dest_dir, "blobs")
    os.makedirs(dest_blobs, exist_ok=True)

    copied_size = 0
    for digest in sorted(required_blobs):
        # Blob filenames use "sha256-<hex>" with colon replaced by dash
        blob_filename = digest.replace(":", "-")
        src_path = os.path.join(blobs_dir, blob_filename)

        if os.path.isfile(src_path):
            size = os.path.getsize(src_path)
            size_str = f"{size / 1_000_000_000:.1f} GB" if size > 1_000_000_000 else f"{size / 1_000_000:.0f} MB" if size > 1_000_000 else f"{size / 1_000:.0f} KB"
            print(f"    Copying {blob_filename[:20]}... ({size_str})")
            shutil.copy2(src_path, os.path.join(dest_blobs, blob_filename))
            copied_size += size
        else:
            print(f"    WARNING: Blob not found: {blob_filename}")

    total_str = f"{copied_size / 1_000_000_000:.1f} GB" if copied_size > 1_000_000_000 else f"{copied_size / 1_000_000:.0f} MB"
    print(f"  Model total: {total_str}")
    return True


def get_dir_size(path: str) -> str:
    """Get total size of a directory in human-readable format."""
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

    # ── Step 1: Check PyInstaller output exists ──
    print("[1/5] Checking build output...")
    if not os.path.isdir(DIST_DIR):
        print(f"  ✗ Build output not found at {DIST_DIR}")
        print(f"    → Run 'python build.py' first")
        sys.exit(1)
    print(f"  ✓ Build output found")

    # ── Step 2: Find Ollama binary ──
    print("\n[2/5] Locating Ollama...")
    ollama_exe = find_ollama_exe()
    if not ollama_exe:
        print("  ✗ Cannot find ollama.exe")
        print("    → Install Ollama from https://ollama.com")
        print("    → Or set its location in PATH")
        sys.exit(1)

    # On Windows, Ollama also needs some DLLs from its install dir
    ollama_dir = os.path.dirname(ollama_exe)

    # ── Step 3: Find model files ──
    print("\n[3/5] Locating dolphin-phi model...")
    model_dir = find_model_dir()
    if not model_dir:
        print("  ✗ Cannot find dolphin-phi model")
        print("    → Run: ollama pull dolphin-phi")
        sys.exit(1)

    # ── Step 4: Assemble release folder ──
    print("\n[4/5] Assembling release package...")
    if os.path.exists(RELEASE_DIR):
        shutil.rmtree(RELEASE_DIR)
    os.makedirs(RELEASE_DIR)

    # 4a: Copy game (PyInstaller output)
    print("  Copying game files...")
    shutil.copytree(DIST_DIR, RELEASE_DIR, dirs_exist_ok=True)

    # 4b: Copy Ollama binary
    print("  Copying Ollama...")
    ollama_dest = os.path.join(RELEASE_DIR, "ollama")
    os.makedirs(ollama_dest, exist_ok=True)
    shutil.copy2(ollama_exe, ollama_dest)

    # Also copy any DLLs / runners from Ollama's install directory
    # Ollama on Windows stores GPU runners in lib/ollama/runners/
    for subdir in ["lib", "runners"]:
        src = os.path.join(ollama_dir, subdir)
        if os.path.isdir(src):
            dst = os.path.join(ollama_dest, subdir)
            print(f"  Copying {subdir}/...")
            shutil.copytree(src, dst)

    # Check for ollama runner libs in AppData (Windows)
    if os.name == "nt":
        user_profile = os.environ.get("USERPROFILE", "")
        app_runners = os.path.join(user_profile, "AppData", "Local", "Programs", "Ollama", "lib", "ollama")
        if os.path.isdir(app_runners):
            dst = os.path.join(ollama_dest, "lib", "ollama")
            if not os.path.exists(dst):
                print(f"  Copying Ollama runtime libraries...")
                shutil.copytree(app_runners, dst)

    # 4c: Copy ONLY dolphin-phi model (not all models)
    print("  Copying dolphin-phi model (this may take a while)...")
    model_dest = os.path.join(RELEASE_DIR, "models")
    os.makedirs(model_dest, exist_ok=True)
    if not copy_single_model(model_dir, model_dest, "dolphin-phi"):
        print("  ERROR: Failed to copy model files")
        sys.exit(1)

    # 4d: Create launcher.bat
    print("  Creating launcher...")
    launcher_path = os.path.join(RELEASE_DIR, "Play DeadStatic.bat")
    with open(launcher_path, "w", encoding="ascii") as f:
        f.write(LAUNCHER_BAT)

    # 4e: Create README.txt
    readme_path = os.path.join(RELEASE_DIR, "README.txt")
    with open(readme_path, "w", encoding="ascii") as f:
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
            print(f"    📁 {item}/  ({get_dir_size(item_path)})")
        else:
            size_kb = os.path.getsize(item_path) / 1024
            print(f"    📄 {item}  ({size_kb:.0f} KB)")
    print(f"\n  ▸ Players double-click 'Play DeadStatic.bat' to start")
    print(f"  ▸ Compress this folder to .zip for distribution")
    print(f"  ▸ Or use Inno Setup for a proper installer (see README)\n")


# ── Launcher batch file ──

LAUNCHER_BAT = """@echo off
chcp 65001 >nul 2>&1
title DEAD STATIC
cd /d "%~dp0"

echo.
echo  ====================================================================
echo   DEAD STATIC - A Zombie Apocalypse Text Adventure
echo  ====================================================================
echo.

:: -- Check that game exe exists --
if not exist "DeadStatic.exe" (
    echo  [ERROR] DeadStatic.exe not found in this folder.
    echo  Make sure all files are extracted properly.
    echo.
    pause
    exit /b 1
)

:: -- Check that ollama exists --
if not exist "ollama\\ollama.exe" (
    echo  [ERROR] ollama\\ollama.exe not found.
    echo  Make sure the ollama folder is next to this bat file.
    echo.
    pause
    exit /b 1
)

:: -- Check that model exists --
if not exist "models\\manifests" (
    echo  [ERROR] Model files not found in models\\ folder.
    echo  Make sure the models folder is next to this bat file.
    echo.
    pause
    exit /b 1
)

:: -- Set environment --
set OLLAMA_MODELS=%~dp0models
set OLLAMA_HOST=127.0.0.1:11434

:: -- Check if Ollama is already running --
echo  Checking Ollama server...
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 3; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 (
    echo  [OK] Ollama is already running.
    goto :start_game
)

:: -- Start Ollama server --
echo  Starting Ollama server...
start "" /B "%~dp0ollama\\ollama.exe" serve
if %errorlevel% neq 0 (
    echo  [ERROR] Failed to start Ollama.
    echo.
    pause
    exit /b 1
)

:: -- Wait for Ollama to be ready (up to 30 seconds) --
set /a attempts=0
:wait_loop
echo  Waiting for Ollama to be ready... (%attempts%/30)
timeout /t 1 /nobreak >nul
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% equ 0 goto :ollama_ready
set /a attempts+=1
if %attempts% geq 30 (
    echo.
    echo  [ERROR] Ollama failed to start after 30 seconds.
    echo  Try running ollama\\ollama.exe serve manually in a separate window.
    echo.
    pause
    exit /b 1
)
goto :wait_loop

:ollama_ready
echo  [OK] Ollama server ready.
echo.

:start_game
echo  Launching game...
echo.

:: -- Run the game --
DeadStatic.exe

:: -- Cleanup --
echo.
echo  Shutting down Ollama server...
taskkill /f /im ollama.exe >nul 2>&1

echo.
echo  Thanks for playing. Stay alive out there.
echo.
pause
"""


# ── Player-facing README ──

PLAYER_README = """
DEAD STATIC -- A Zombie Apocalypse Text Adventure
===================================================

HOW TO PLAY:
    Double-click "Play DeadStatic.bat"
    That's it. Everything is bundled.

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

TROUBLESHOOTING:
    - If the game says "Cannot connect to Ollama":
      -> Close the game, wait 5 seconds, try again.
      -> Or run ollama\\ollama.exe manually first.
    - If you get an error about missing model:
      -> Open Command Prompt in this folder
      -> Run: ollama\\ollama.exe pull dolphin-phi
    - Game saves are stored as "dead_static_save.json" next to the exe.

SYSTEM REQUIREMENTS:
    - Windows 10 or later
    - 4 GB RAM minimum (8 GB recommended)
    - ~2 GB disk space (mostly the AI model)
    - No internet required -- everything runs locally

Made with local AI. No data leaves your computer. Ever.
"""


if __name__ == "__main__":
    package()