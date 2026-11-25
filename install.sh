#!/usr/bin/env bash
# Vortex — Setup & Requirements Installer for Linux / macOS

set -e

echo "======================================================="
echo "       Vortex — Setup & Requirements Installer         "
echo "======================================================="
echo ""

# 1. Check Python
if ! command -v python3 &> /dev/null; then
    echo "[!] Python 3 is not installed."
    echo "    On Ubuntu/Debian: sudo apt update && sudo apt install -y python3 python3-pip"
    echo "    On macOS: brew install python"
    exit 1
fi
echo "[OK] Found $(python3 --version)"

# 2. Install Python packages
echo "[*] Installing Python dependencies..."
python3 -m pip install --upgrade pip --quiet
python3 -m pip install -r requirements.txt
echo "[OK] Python dependencies installed successfully."

# 3. Check FFmpeg
echo "[*] Checking for FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "[OK] FFmpeg is already installed and ready."
else
    echo "[!] FFmpeg not found."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "[*] Installing FFmpeg via Homebrew..."
        brew install ffmpeg || echo "[!] Please install ffmpeg with: brew install ffmpeg"
    elif [[ -f /etc/debian_version ]]; then
        echo "[*] Installing FFmpeg via apt..."
        sudo apt update && sudo apt install -y ffmpeg || echo "[!] Please install ffmpeg with: sudo apt install ffmpeg"
    elif [[ -f /etc/arch-release ]]; then
        echo "[*] Installing FFmpeg via pacman..."
        sudo pacman -S --noconfirm ffmpeg || echo "[!] Please install ffmpeg with: sudo pacman -S ffmpeg"
    else
        echo "[!] Please install ffmpeg using your system package manager."
    fi
fi

echo ""
echo "======================================================="
echo "[OK] Setup complete! Start Vortex with: python3 app.py"
echo "======================================================="
