#!/bin/bash
set -e

echo "=== FlashLink deploy ==="
git pull

source venv/bin/activate
pip install -r requirements.txt -q

sudo systemctl restart flashlink-bot
sudo systemctl restart flashlink-webhook

echo "=== Done ==="
sudo systemctl status flashlink-bot --no-pager
