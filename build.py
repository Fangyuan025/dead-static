"""
build.py — Package DEAD STATIC into a standalone exe
Run: python build.py

Prerequisites:
    pip install pyinstaller

This creates:
    dist/DeadStatic/
        DeadStatic.exe      — The game
        + all dependencies
"""

import subprocess
import sys
import os
import shutil


def check_pyinstaller():
    try:
        import PyInstaller
        print(f"  ✓ PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("  ✗ PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        return True


def build():
    print("\n══════════════════════════════════════")
    print("  DEAD STATIC — Build Tool")
    print("══════════════════════════════════════\n")

    # 1. Check PyInstaller
    print("[1/3] Checking dependencies...")
    check_pyinstaller()

    # 2. Clean previous builds
    print("[2/3] Cleaning previous builds...")
    for d in ["build", "dist", "__pycache__"]:
        if os.path.exists(d):
            shutil.rmtree(d)
    for f in ["DeadStatic.spec"]:
        if os.path.exists(f):
            os.remove(f)

    # 3. Run PyInstaller
    print("[3/3] Building exe...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "DeadStatic",
        "--onedir",                # One folder (not single exe — faster startup)
        "--console",               # Console app (needed for text game)
        "--noconfirm",             # Overwrite without asking
        "--clean",                 # Clean cache
        "--icon", "NONE",          # No icon (add your .ico later if you want)
        "--add-data", f"README.md{os.pathsep}.",  # Bundle README
        "game.py",
    ]

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print("\n══════════════════════════════════════")
        print("  ✓ BUILD SUCCESSFUL")
        print("══════════════════════════════════════")
        print(f"  Output: dist/DeadStatic/DeadStatic.exe")
        print(f"\n  Next step: run package.py to bundle with Ollama + model")
    else:
        print("\n  ✗ Build failed. Check errors above.")
        sys.exit(1)


if __name__ == "__main__":
    build()
