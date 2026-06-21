#!/bin/bash
pkill -f kaon-bot.py || true
nohup .venv/bin/python -u kaon-bot.py > /dev/null 2>&1 &
echo "▶ Kaon Bot 시작 (PID: $!)"
