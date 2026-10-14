#!/bin/bash
# Master desktop application launcher script for macOS environments.
# Resolves application root directories, activates the Python virtual environment, and executes desktop_app.py.
# Handles zero-configuration startup for native Cocoa desktop window presentation.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/Back End"

echo "============================================================"
echo " Launching A.R.C. Vision Offline Photo Sorting Application"
echo "============================================================"

if [ -f .venv/bin/python ]; then
    exec ./.venv/bin/python desktop_app.py
else
    exec python3 desktop_app.py
fi
