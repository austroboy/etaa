#!/usr/bin/env bash
# ============================================================
# ETAA – First-time setup script
# Run: bash scripts/setup.sh
# ============================================================

set -e

CYAN='\033[0;36m'
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${CYAN}[ETAA]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ── 1. Check Python ────────────────────────────────────────────
info "Checking Python version…"
python3 --version | grep -E "3\.(10|11|12)" > /dev/null 2>&1 \
  || error "Python 3.10+ required."
success "Python OK"

# ── 2. Check Node.js ───────────────────────────────────────────
info "Checking Node.js version…"
node --version | grep -E "v(18|19|20|21)" > /dev/null 2>&1 \
  || error "Node.js 18+ required."
success "Node.js OK"

# ── 3. Check Redis ─────────────────────────────────────────────
info "Checking Redis…"
redis-cli ping > /dev/null 2>&1 || error "Redis is not running. Start it with: redis-server"
success "Redis OK"

# ── 4. Python virtual environment ─────────────────────────────
if [ ! -d "venv" ]; then
  info "Creating Python virtual environment…"
  python3 -m venv venv
fi

info "Activating virtual environment…"
source venv/bin/activate

# ── 5. Install Python dependencies ────────────────────────────
info "Installing Python dependencies…"
pip install --upgrade pip -q
pip install -r requirements.txt -q
success "Python dependencies installed"

# ── 6. Copy .env if not exists ────────────────────────────────
if [ ! -f ".env" ]; then
  info "Creating .env from example…"
  cp .env.example .env
  echo ""
  echo -e "${RED}⚠️  Please edit .env with your actual credentials before continuing!${NC}"
  echo "   Required: DJANGO_SECRET_KEY, OPENAI_API_KEY, SMTP_USER, SMTP_PASSWORD,"
  echo "             OPERATOR_1_PHONE, WHATSAPP_GROUP_JID"
  echo ""
  read -p "Press Enter once you've filled in .env to continue..."
fi

# ── 7. Create directories ─────────────────────────────────────
info "Creating output directories…"
mkdir -p outputs/cv_rankings outputs/job_posts outputs/code logs temp/cvs media staticfiles
success "Directories created"

# ── 8. Django setup ────────────────────────────────────────────
info "Running Django migrations…"
python manage.py migrate --noinput
success "Migrations complete"

info "Collecting static files…"
python manage.py collectstatic --noinput -v 0
success "Static files collected"

# ── 9. Create superuser ────────────────────────────────────────
info "Creating Django admin superuser (follow prompts)…"
python manage.py createsuperuser || true

# ── 10. Node bridge setup ──────────────────────────────────────
info "Installing Node.js bridge dependencies…"
cd bridge && npm install --omit=dev && cd ..
success "Node.js dependencies installed"

# ── 11. Done ───────────────────────────────────────────────────
echo ""
success "ETAA setup complete!"
echo ""
echo -e "Start the system with:"
echo -e "  ${CYAN}# Terminal 1 – Django${NC}"
echo -e "  source venv/bin/activate && python manage.py runserver"
echo ""
echo -e "  ${CYAN}# Terminal 2 – Celery Worker${NC}"
echo -e "  source venv/bin/activate && celery -A etaa_core worker --loglevel=info"
echo ""
echo -e "  ${CYAN}# Terminal 3 – WhatsApp Bridge${NC}"
echo -e "  cd bridge && node server.js"
echo ""
echo -e "Or use Docker Compose: ${CYAN}docker-compose up -d${NC}"
