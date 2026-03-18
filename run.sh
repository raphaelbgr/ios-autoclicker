#!/bin/bash
# iOS Auto-Clicker — Setup & Run Script
# Sets up a Python virtual environment, installs dependencies, and launches the app.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

echo "🎯 iOS Auto-Clicker"
echo "==================="

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not found."
    echo "   Install it from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python $PYTHON_VERSION found"

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✅ Virtual environment created"
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# Install/update dependencies
echo "📦 Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "✅ Dependencies installed"

# Launch the app
echo ""
echo "🚀 Launching iOS Auto-Clicker..."
echo "   (Make sure iPhone Mirroring is open)"
echo ""

cd "$SCRIPT_DIR"
python -m src.main
