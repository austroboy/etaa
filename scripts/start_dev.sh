#!/usr/bin/env bash
# ============================================================
# ETAA – Development start script
# Launches all services in background tmux panes (or sequentially)
# Run: bash scripts/start_dev.sh
# ============================================================

set -e

info() { echo "[ETAA] $*"; }

# Activate venv
source venv/bin/activate 2>/dev/null || true

# Check if tmux is available
if command -v tmux &>/dev/null; then
  SESSION="etaa"

  tmux new-session -d -s $SESSION -n "django" \
    "source venv/bin/activate; python manage.py runserver; exec bash" 2>/dev/null || true

  tmux new-window -t $SESSION -n "celery" \
    "source venv/bin/activate; celery -A etaa_core worker --loglevel=info; exec bash"

  tmux new-window -t $SESSION -n "beat" \
    "source venv/bin/activate; celery -A etaa_core beat --loglevel=info; exec bash"

  tmux new-window -t $SESSION -n "bridge" \
    "cd bridge && node server.js; exec bash"

  tmux attach-session -t $SESSION
else
  # Fallback: print instructions
  info "tmux not found. Start each service manually:"
  echo ""
  echo "Terminal 1 (Django):"
  echo "  source venv/bin/activate && python manage.py runserver"
  echo ""
  echo "Terminal 2 (Celery Worker):"
  echo "  source venv/bin/activate && celery -A etaa_core worker --loglevel=info"
  echo ""
  echo "Terminal 3 (Celery Beat):"
  echo "  source venv/bin/activate && celery -A etaa_core beat --loglevel=info"
  echo ""
  echo "Terminal 4 (WhatsApp Bridge):"
  echo "  cd bridge && node server.js"
fi
