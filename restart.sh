#!/bin/bash
pkill -f kaon-bot.py || true
nohup python -u kaon-bot.py > kaon.log 2>&1 &
echo "▶ Kaon Bot 시작 (PID: $!)"
