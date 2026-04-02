#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# dev.sh — Single command to start the full Handoff POC stack
#
# Starts: PostgreSQL (Docker) → ngrok → updates .env & Plivo
#         webhooks → backend (uvicorn) → frontend (pnpm dev)
#
# Usage:
#   bash scripts/dev.sh              # normal start
#   bash scripts/dev.sh --seed       # also seed the database
#   bash scripts/dev.sh --no-ngrok   # skip ngrok (mock/local only)
# ──────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

# ── Flags ────────────────────────────────────────────────────
SEED=false
SKIP_NGROK=false
for arg in "$@"; do
  case $arg in
    --seed)     SEED=true ;;
    --no-ngrok) SKIP_NGROK=true ;;
  esac
done

# ── Colors ───────────────────────────────────────────────────
G='\033[0;32m' Y='\033[1;33m' R='\033[0;31m' C='\033[0;36m' NC='\033[0m'
info()  { echo -e "${G}[✓]${NC} $1"; }
warn()  { echo -e "${Y}[!]${NC} $1"; }
err()   { echo -e "${R}[✗]${NC} $1"; }

# ── Process tracking & cleanup ───────────────────────────────
PIDS=()
cleanup() {
  echo ""
  warn "Shutting down..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null || true
  done
  info "All processes stopped. PostgreSQL container still running (docker compose stop postgres to stop)."
}
trap cleanup EXIT INT TERM

# ── 1. PostgreSQL ────────────────────────────────────────────
info "Starting PostgreSQL..."
docker compose up -d postgres

# Wait for it to accept connections (max 30s)
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
    break
  fi
  if [ "$i" -eq 30 ]; then
    err "PostgreSQL failed to start within 30s"
    exit 1
  fi
  sleep 1
done
info "PostgreSQL is ready."

# ── 2. Seed (optional) ──────────────────────────────────────
if [ "$SEED" = true ]; then
  info "Seeding database..."
  python -m scripts.seed
fi

# ── 3. ngrok ─────────────────────────────────────────────────
NGROK_URL=""
if [ "$SKIP_NGROK" = false ]; then
  # Kill any existing ngrok to avoid port conflicts
  pkill -f "ngrok http" 2>/dev/null || true
  sleep 1

  # Read static domain from .env if present (ngrok free-tier static domain)
  CURRENT_URL=$(grep -E "^BASE_WEBHOOK_URL=" .env | head -1 | sed 's/^BASE_WEBHOOK_URL=//' | tr -d '"' | tr -d "'")
  STATIC_DOMAIN=""
  if echo "$CURRENT_URL" | grep -q "ngrok"; then
    STATIC_DOMAIN=$(echo "$CURRENT_URL" | sed 's|https://||' | sed 's|/.*||')
  fi

  info "Starting ngrok..."
  if [ -n "$STATIC_DOMAIN" ]; then
    ngrok http 8000 --domain "$STATIC_DOMAIN" --log=stdout > /dev/null 2>&1 &
  else
    ngrok http 8000 --log=stdout > /dev/null 2>&1 &
  fi
  PIDS+=($!)

  # Wait for ngrok API to be available (max 10s)
  for i in $(seq 1 10); do
    NGROK_URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null \
      | python -c "import sys,json; tunnels=json.load(sys.stdin).get('tunnels',[]); print(tunnels[0]['public_url'] if tunnels else '')" 2>/dev/null) || true
    if [ -n "$NGROK_URL" ]; then
      break
    fi
    sleep 1
  done

  if [ -z "$NGROK_URL" ]; then
    err "Could not get ngrok URL. Is ngrok installed and authenticated?"
    err "Install: https://ngrok.com/download  |  Auth: ngrok config add-authtoken <token>"
    exit 1
  fi
  info "ngrok tunnel: ${C}${NGROK_URL}${NC}"

  # ── 4. Update .env ───────────────────────────────────────
  # Replace BASE_WEBHOOK_URL line (handles quoted and unquoted values)
  sed -i "s|^BASE_WEBHOOK_URL=.*|BASE_WEBHOOK_URL=${NGROK_URL}|" .env
  info "Updated BASE_WEBHOOK_URL in .env"

  # ── 5. Update Plivo webhooks ─────────────────────────────
  if grep -qE "^PLIVO_AUTH_ID=.+" .env; then
    warn "Updating Plivo application webhooks..."
    python -m scripts.update_webhooks --url "$NGROK_URL" 2>&1 | sed 's/^/     /'
  fi
fi

# ── 6. Backend ───────────────────────────────────────────────
info "Starting backend (uvicorn :8000)..."
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
PIDS+=($!)

# Wait for backend to respond (max 15s)
for i in $(seq 1 15); do
  if curl -sf http://localhost:8000/docs > /dev/null 2>&1; then
    break
  fi
  sleep 1
done
info "Backend is ready."

# ── 7. Frontend ──────────────────────────────────────────────
info "Starting frontend (pnpm dev :5173)..."
(cd frontend && pnpm dev) &
PIDS+=($!)

# ── Summary ──────────────────────────────────────────────────
sleep 2
echo ""
echo -e "${G}══════════════════════════════════════════${NC}"
echo -e "${G}  Handoff POC — All services running${NC}"
echo -e "${G}══════════════════════════════════════════${NC}"
echo -e "  Frontend:  ${C}http://localhost:5173${NC}"
echo -e "  Backend:   ${C}http://localhost:8000${NC}"
echo -e "  Swagger:   ${C}http://localhost:8000/docs${NC}"
if [ -n "$NGROK_URL" ]; then
echo -e "  ngrok:     ${C}${NGROK_URL}${NC}"
fi
echo -e "${G}══════════════════════════════════════════${NC}"
echo -e "  Press ${Y}Ctrl+C${NC} to stop all services"
echo -e "${G}══════════════════════════════════════════${NC}"

# Keep script alive until interrupted
wait
