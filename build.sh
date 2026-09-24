#!/usr/bin/env bash
# Exit immediately if a command exits with a non-zero status
set -o errexit

echo "=============================================="
echo " Starting Voyager ERP Build on Render"
echo "=============================================="

# 1. Upgrade pip and install dependencies
echo "[1/4] Installing backend dependencies..."
pip install --upgrade pip
pip install -r backend/requirements.txt

# 2. Collect static files for WhiteNoise
echo "[2/4] Collecting static files (WhiteNoise)..."
python backend/manage.py collectstatic --noinput

# 3. Apply Django migrations
echo "[3/4] Checking and applying database migrations..."
python backend/manage.py migrate --noinput

# 4. Populate initial data (Ledgers, Customers, Suppliers, Tickets, Vouchers)
echo "[4/4] Checking and seeding database records..."
python backend/load_initial_data.py

echo "=============================================="
echo " Build Completed Successfully!"
echo "=============================================="
