#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "=============================================="
echo " Starting Voyager ERP Build on Render"
echo "=============================================="

# 1. Upgrade pip and install dependencies
echo "[1/3] Installing backend dependencies..."
pip install --upgrade pip
pip install -r backend/requirements.txt

# 2. Collect static files for WhiteNoise
echo "[2/3] Collecting static files (WhiteNoise)..."
python backend/manage.py collectstatic --noinput

# 3. Apply Django migrations
echo "[3/3] Checking and applying database migrations..."
python backend/manage.py migrate --noinput

echo "=============================================="
echo " Build Completed Successfully!"
echo "=============================================="
