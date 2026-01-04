#!/usr/bin/env bash
# GPTIntermediary VPS diagnostic script
# Collects system info, versions, open ports, service status, and recent logs

set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
OUTDIR="/tmp/gpt_diagnostics_${TS}"
mkdir -p "$OUTDIR"

echo "Collecting diagnostics to $OUTDIR"

echo "== Basic info ==" > "$OUTDIR/01_basic.txt"
uname -a >> "$OUTDIR/01_basic.txt" 2>&1 || true
lsb_release -a >> "$OUTDIR/01_basic.txt" 2>&1 || true
cat /etc/os-release >> "$OUTDIR/01_basic.txt" 2>&1 || true
echo "Date: $(date -u)" >> "$OUTDIR/01_basic.txt"

echo "== Python & pip ==" > "$OUTDIR/02_python.txt"
python3 --version 2>&1 >> "$OUTDIR/02_python.txt" || true
pip3 --version 2>&1 >> "$OUTDIR/02_python.txt" || true
if command -v pip3 >/dev/null 2>&1; then
  pip3 freeze 2>/dev/null > "$OUTDIR/02_pip_freeze.txt" || true
fi

echo "== Node & npm ==" > "$OUTDIR/03_node.txt"
node --version 2>&1 >> "$OUTDIR/03_node.txt" || true
npm --version 2>&1 >> "$OUTDIR/03_node.txt" || true
if [ -f package.json ]; then
  npm ls --depth=0 2>/dev/null > "$OUTDIR/03_npm_ls.txt" || true
fi

echo "== Network / Listening ports ==" > "$OUTDIR/04_ports.txt"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp 2>&1 >> "$OUTDIR/04_ports.txt" || true
else
  netstat -tulpn 2>&1 >> "$OUTDIR/04_ports.txt" || true
fi

echo "== Processes (python/node) ==" > "$OUTDIR/05_procs.txt"
ps aux | egrep 'python|node' | egrep -v 'egrep' >> "$OUTDIR/05_procs.txt" || true

echo "== GPTIntermediary directory listing ==" > "$OUTDIR/06_listing.txt"
PROJECT_DIR="/var/www/GPTIntermediary"
if [ -d "$PROJECT_DIR" ]; then
  ls -la "$PROJECT_DIR" >> "$OUTDIR/06_listing.txt" 2>&1 || true
  echo "\nChecking critical files:" >> "$OUTDIR/06_listing.txt"
  [ -f "$PROJECT_DIR/.env" ] && echo ".env exists" >> "$OUTDIR/06_listing.txt" || echo ".env missing" >> "$OUTDIR/06_listing.txt"
  stat "$PROJECT_DIR" >> "$OUTDIR/06_listing.txt" 2>&1 || true
else
  echo "$PROJECT_DIR not found" >> "$OUTDIR/06_listing.txt"
fi

echo "== .env summary (first 100 lines, filtered) ==" > "$OUTDIR/07_env.txt"
if [ -f "$PROJECT_DIR/.env" ]; then
  sed -n '1,200p' "$PROJECT_DIR/.env" | sed -e 's/\(OPENAI_API_KEY\|GOOGLE_CLIENT_\|USER_ACCESS_TOKEN\|USER_REFRESH_TOKEN\|JWT_SECRET\)=.*/\1=REDACTED/' > "$OUTDIR/07_env.txt" || true
else
  echo ".env not found" >> "$OUTDIR/07_env.txt"
fi

echo "== Logs (if present) ==" > "$OUTDIR/08_logs_index.txt"
LOGDIR="$PROJECT_DIR/logs"
if [ -d "$LOGDIR" ]; then
  ls -la "$LOGDIR" >> "$OUTDIR/08_logs_index.txt" 2>&1 || true
  for f in backend_server.log chat_server.log whatsapp_server.log telegram_server.log django_server.log; do
    if [ -f "$LOGDIR/$f" ]; then
      echo "-- tail of $f --" >> "$OUTDIR/08_logs_index.txt"
      tail -n 200 "$LOGDIR/$f" >> "$OUTDIR/08_logs_index.txt" 2>&1 || true
      echo "" >> "$OUTDIR/08_logs_index.txt"
    fi
  done
else
  echo "Log dir not found: $LOGDIR" >> "$OUTDIR/08_logs_index.txt"
fi

echo "== systemctl service status (gptintermediary) ==" > "$OUTDIR/09_service.txt"
systemctl status gptintermediary 2>&1 >> "$OUTDIR/09_service.txt" || true
journalctl -u gptintermediary -n 200 --no-pager 2>&1 >> "$OUTDIR/09_service.txt" || true

echo "== firewall / UFW ==" > "$OUTDIR/10_firewall.txt"
if command -v ufw >/dev/null 2>&1; then
  ufw status verbose 2>&1 >> "$OUTDIR/10_firewall.txt" || true
fi
if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --list-all 2>&1 >> "$OUTDIR/10_firewall.txt" || true
fi

echo "== docker (if present) ==" > "$OUTDIR/11_docker.txt"
if command -v docker >/dev/null 2>&1; then
  docker ps -a 2>&1 >> "$OUTDIR/11_docker.txt" || true
fi

echo "Creating archive..."
ARCHIVE="/tmp/gpt_diagnostics_${TS}.tar.gz"
tar -czf "$ARCHIVE" -C "/tmp" "$(basename "$OUTDIR")" || true

echo "Diagnostics collected: $ARCHIVE"
echo "You can download this file and paste relevant sections here for analysis."

exit 0
