#!/bin/bash
# SPE Remote Control - Setup Script for Raspberry Pi
set -e

echo "=== SPE Remote Control Setup ==="

# Ensure python3-venv is available
if ! dpkg -s python3-venv &>/dev/null; then
    echo "Installing python3-venv..."
    sudo apt-get update && sudo apt-get install -y python3-full python3-venv
fi

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Install dependencies
echo "Installing dependencies..."
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

echo ""
echo "=== Setup complete ==="
echo "To run:  ./run.sh"
echo "Or:      venv/bin/python server.py"
