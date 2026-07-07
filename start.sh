#!/usr/bin/env bash
# Llama.cpp Build Assistant - macOS / Linux launcher
# Uses python_manager.py to pick a compatible interpreter automatically.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " Llama.cpp Build Assistant (v0.2.2)"
echo "========================================"
echo ""

# Find ANY python3 to bootstrap interpreter selection (pure-stdlib module).
PYEXE=""
for c in python3 python python3.13 python3.12 python3.11; do
    if command -v "$c" >/dev/null 2>&1; then PYEXE="$c"; break; fi
done

if [[ -z "$PYEXE" ]]; then
    echo "ERROR: No Python found. Install Python 3.9+:"
    echo "  Debian/Ubuntu: sudo apt install python3 python3-pip"
    echo "  Fedora:        sudo dnf install python3 python3-pip"
    echo "  Arch:          sudo pacman -S python python-pip"
    echo "  macOS:         brew install python@3.13   (or https://www.python.org/downloads/)"
    exit 1
fi

echo "Bootstrap: selecting a compatible Python interpreter..."
"$PYEXE" "$SCRIPT_DIR/python_manager.py" bootstrap

# Read the chosen interpreter written by python_manager.
CHOSEN_PY=""
if [[ -f "$SCRIPT_DIR/.python-interpreter" ]]; then
    CHOSEN_PY="$(tr -d '\r\n' < "$SCRIPT_DIR/.python-interpreter")"
fi
[[ -z "$CHOSEN_PY" ]] && CHOSEN_PY="$PYEXE"

echo "Using interpreter: $CHOSEN_PY"
echo ""
echo "Starting Build Assistant..."
"$CHOSEN_PY" "$SCRIPT_DIR/app.py"

echo ""
echo "Application closed."
