#!/bin/bash
# Shell startup script for the A.R.C. Vision FastAPI server on macOS and Linux.
# Initializes the local Python environment, verifies dependencies, and executes the uvicorn web server.
# Handles automatic browser opening and input/output folder preparation.

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

mkdir -p input output

# Wait for server to listen on port 8000 before opening browser
(
    for i in {1..50}; do
        if nc -z 127.0.0.1 8000 2>/dev/null; then
            open "http://127.0.0.1:8000/loading.html"
            break
        fi
        sleep 0.2
    done
) &

# First-time setup only if virtual environment does not exist
if [ ! -d ".venv" ] || [ ! -f ".venv/bin/python" ]; then
    echo "[INFO] First-time setup: Setting up Python environment..."
    PYTHON_CMD="python3"
    if command -v python3.10 &>/dev/null; then
        PYTHON_CMD="python3.10"
    fi
    $PYTHON_CMD -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt --quiet
    ./.venv/bin/python check_env.py
fi

# Instant server execution
exec ./.venv/bin/python server.py
