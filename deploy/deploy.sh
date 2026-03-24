#!/bin/bash
set -e

echo "=== FlashLink deploy ==="
git pull

source venv/bin/activate
pip install -r requirements.txt -q

sudo systemctl restart flashlink-bot
sudo systemctl restart flashlink-webhook
sudo systemctl restart flashlink-api

echo "=== Done ==="
sudo systemctl status flashlink-bot flashlink-webhook flashlink-api --no-pager