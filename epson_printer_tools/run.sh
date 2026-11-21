#!/usr/bin/env sh
set -e
mkdir -p /run/cups /var/log/cups /var/spool/cups
exec python3 -u /app/server.py
