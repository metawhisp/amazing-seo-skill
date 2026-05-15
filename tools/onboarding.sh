#!/usr/bin/env bash
# Amazing SEO Skill — onboarding wizard.
#
# Run this once after install. It tells you:
#   - which prereqs are installed (Python, Node, git, Playwright, engines)
#   - which API keys are present in macOS Keychain (and what they unlock)
#   - whether the deterministic checkers actually work on your machine
#   - which capability layers (L0-L4) are active right now
#   - what to do next to unlock the rest
#
# Re-run safely any time — it never writes anything; the only side-effects
# are smoke-test HTTP requests to example.com / llmstxt.org.
#
# Usage:  tools/onboarding.sh

set -u

# ── ANSI colours (NO_COLOR-respecting) ────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_BOLD=$'\033[1m'
  C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[36m'
else
  C_RESET=""; C_DIM=""; C_BOLD=""; C_GREEN=""; C_RED=""; C_YELLOW=""; C_BLUE=""
fi

ok()    { printf "  ${C_GREEN}✓${C_RESET} %s\n" "$1"; }
miss()  { printf "  ${C_RED}✗${C_RESET} %s\n" "$1"; }
warn()  { printf "  ${C_YELLOW}!${C_RESET} %s\n" "$1"; }
info()  { printf "  ${C_DIM}·${C_RESET} %s\n" "$1"; }
header(){ printf "\n${C_BOLD}%s${C_RESET}\n" "$1"; }

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SKILL_DIR"

printf "${C_BOLD}${C_BLUE}┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓${C_RESET}\n"
printf "${C_BOLD}${C_BLUE}┃${C_RESET}  ${C_BOLD}amazing-seo-skill${C_RESET} — onboarding & status check        ${C_BOLD}${C_BLUE}┃${C_RESET}\n"
printf "${C_BOLD}${C_BLUE}┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛${C_RESET}\n"

# ── Layer state we'll fill in as we go ────────────────────────────────────
L0_ACTIVE=1     # Claude reasoning always works
L1_ACTIVE=0
L2_ACTIVE=0
L3_HINT="MCP-mediated; install via Claude Code MCP, no local probe possible"
L4_PROVIDERS=()

# ── Prereqs ───────────────────────────────────────────────────────────────
header "1. Prerequisites"
PY_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')
  ok "python3 ${PY_VER}"
  PY_BIN="python3"
else
  miss "python3 — install Python 3.10+ from python.org"
fi
if command -v node >/dev/null 2>&1; then ok "node $(node --version)"; else warn "node — optional (only needed for deep-audit engine)"; fi
if command -v git  >/dev/null 2>&1; then ok "git  $(git --version | awk '{print $3}')"; else miss "git"; fi
if command -v security >/dev/null 2>&1; then ok "macOS Keychain (security CLI)"; else warn "security CLI — not on this OS; you'll set keys via env vars instead"; fi

# ── Python deps (.venv) ──────────────────────────────────────────────────
header "2. Python environment (.venv)"
VENV_PY="$SKILL_DIR/.venv/bin/python"
if [ -x "$VENV_PY" ]; then
  ok ".venv exists ($($VENV_PY --version 2>&1))"
  # Probe required packages
  for pkg in requests bs4 lxml playwright; do
    if "$VENV_PY" -c "import $pkg" 2>/dev/null; then
      ok "  $pkg installed"
    else
      miss "  $pkg missing — run: .venv/bin/pip install -r requirements.txt"
    fi
  done
  L1_ACTIVE=1
else
  miss ".venv not built — run ./install.sh first"
  info "or: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

# ── Engines (L2) ─────────────────────────────────────────────────────────
header "3. Local engines (L2 — deep audit + AEO citation)"
if [ -f .bin/.engines.env ]; then
  # shellcheck disable=SC1091
  source .bin/.engines.env
  if [ -n "${AMAZING_SEO_DEEP_AUDIT_ENGINE:-}" ] && [ -x "${AMAZING_SEO_DEEP_AUDIT_ENGINE:-/x}" ]; then
    ok "deep-audit engine: $AMAZING_SEO_DEEP_AUDIT_ENGINE"
    L2_ACTIVE=1
  else
    miss "deep-audit engine binary missing — run ./install.sh"
  fi
  if [ -n "${AMAZING_SEO_AEO_CITATIONS_ENGINE:-}" ] && [ -x "${AMAZING_SEO_AEO_CITATIONS_ENGINE:-/x}" ]; then
    ok "AEO-citations engine: $AMAZING_SEO_AEO_CITATIONS_ENGINE"
  else
    miss "AEO-citations engine missing — run ./install.sh"
    L2_ACTIVE=0
  fi
else
  warn "no .bin/.engines.env — L2 (deep audit + live AEO citations) disabled"
  info "run ./install.sh with DEEP_AUDIT_ENGINE_PKG / AEO_CITATIONS_ENGINE_PKG_SPEC set"
fi

# ── L4 — multi-LLM ensemble keys ─────────────────────────────────────────
header "4. AI provider keys (L4 — citation ensemble)"
probe_key() {
  local name=$1 label=$2 unlocks=$3
  # First env var (with several common spellings)
  local env_val=""
  case "$name" in
    anthropic-api-key)      env_val="${ANTHROPIC_API_KEY:-}";;
    openai-api-key)         env_val="${OPENAI_API_KEY:-}";;
    perplexity-api-key)     env_val="${PERPLEXITY_API_KEY:-}";;
    x.ai-api-key)           env_val="${XAI_API_KEY:-}";;
    google-gemini-api-key)  env_val="${GOOGLE_GEMINI_API_KEY:-${GOOGLE_AI_STUDIO_API_KEY:-}}";;
    google-psi-api-key)     env_val="${GOOGLE_PSI_API_KEY:-}";;
  esac
  if [ -n "$env_val" ]; then
    ok "$label — found in env"
    L4_PROVIDERS+=("$label")
    return 0
  fi
  # Then Keychain
  if command -v security >/dev/null 2>&1 && \
     security find-generic-password -s "$name" -w >/dev/null 2>&1; then
    ok "$label — found in Keychain (\`$name\`)"
    L4_PROVIDERS+=("$label")
    return 0
  fi
  miss "$label — missing. Unlocks: $unlocks"
  info "    add: security add-generic-password -s $name -a \$USER -w"
  return 1
}

probe_key anthropic-api-key      "Anthropic (Claude)"        "Claude AEO citation probe"
probe_key openai-api-key         "OpenAI (ChatGPT)"          "ChatGPT AEO citation probe"
probe_key perplexity-api-key     "Perplexity"                "Perplexity AEO citation probe"
probe_key x.ai-api-key           "xAI (Grok)"                "Grok AEO citation probe"
probe_key google-gemini-api-key  "Google Gemini"             "Gemini + Google Search grounding — proxies AI Overviews / AI Mode"
probe_key google-psi-api-key     "Google PageSpeed Insights" "Real CrUX/Lighthouse CWV at scale (rate limit: 25k/day vs 25/day keyless)"

# ── Smoke tests of L1 deterministic checkers ─────────────────────────────
header "5. L1 deterministic-checker smoke tests (live HTTP)"
if [ -x "$VENV_PY" ]; then
  echo "  Probing checkers against example.com / llmstxt.org…"
  {
    "$VENV_PY" scripts/_fetch.py 2>/dev/null  # may not be a CLI; tolerate
  } >/dev/null 2>&1 || true

  if "$VENV_PY" -c "
import sys; sys.path.insert(0, 'scripts')
from _fetch import fetch
r = fetch('https://example.com', timeout=10)
print('OK', r.status_code)
" 2>&1 | grep -q "^OK 200"; then
    ok "_fetch.py reaches example.com (realistic UA, SSRF guard active)"
  else
    miss "_fetch.py couldn't reach example.com — network issue?"
  fi

  if "$VENV_PY" scripts/llms_txt_checker.py https://llmstxt.org --skip-links >/dev/null 2>&1; then
    ok "llms_txt_checker — JSON output, exit 0/2 (clean run)"
  else
    warn "llms_txt_checker — non-zero exit; check $VENV_PY scripts/llms_txt_checker.py https://llmstxt.org"
  fi

  if "$VENV_PY" scripts/robots_checker.py https://www.anthropic.com >/dev/null 2>&1; then
    ok "robots_checker — runs cleanly"
  else
    warn "robots_checker — non-zero exit"
  fi

  # New L1 checkers
  if "$VENV_PY" scripts/security_headers_checker.py https://github.com >/dev/null 2>&1; then
    ok "security_headers_checker — runs cleanly"
  fi
  if "$VENV_PY" scripts/images_audit.py https://example.com --no-size-probe >/dev/null 2>&1; then
    ok "images_audit — runs cleanly"
  fi
else
  warn "skipped smoke tests — .venv not ready"
fi

# ── Capability summary ──────────────────────────────────────────────────
header "6. Active capability layers"
[ "$L0_ACTIVE" = 1 ] && ok "L0 (Claude reasoning)  — always on" || true
[ "$L1_ACTIVE" = 1 ] && ok "L1 (deterministic Python checkers)" || miss "L1 — install .venv to enable"
[ "$L2_ACTIVE" = 1 ] && ok "L2 (engines: deep-audit + AEO citations)" || warn "L2 — engines not configured"
ok "L3 (Ahrefs MCP / GSC) — $L3_HINT"
if [ "${#L4_PROVIDERS[@]}" -gt 0 ]; then
  ok "L4 (LLM ensemble) — ${#L4_PROVIDERS[@]}/6 providers: ${L4_PROVIDERS[*]}"
else
  warn "L4 (LLM ensemble) — no provider keys yet"
fi

# ── Next-steps ──────────────────────────────────────────────────────────
header "7. Suggested next steps"
if [ "$L1_ACTIVE" = 0 ]; then
  echo "  • Install Python deps:  ${C_DIM}./install.sh${C_RESET}  (sets up .venv + Playwright + engines)"
fi
if [ "$L2_ACTIVE" = 0 ]; then
  echo "  • Configure engines:    set DEEP_AUDIT_ENGINE_PKG, AEO_CITATIONS_ENGINE_PKG_SPEC and re-run install.sh"
fi
if [ "${#L4_PROVIDERS[@]}" -lt 5 ]; then
  echo "  • Add provider keys above to unlock more AEO/AI-Overview coverage"
fi
echo "  • Try it:               ${C_DIM}in Claude Code, say \"audit https://example.com\"${C_RESET}"
echo "  • Reference:            ${C_DIM}ONBOARDING.md${C_RESET} (this file's reference doc)"
echo "  • Re-run this check:    ${C_DIM}./tools/onboarding.sh${C_RESET}"

printf "\n${C_DIM}Tip: pipe to NO_COLOR=1 for plain output, or to \`tee onboarding.log\` to save.${C_RESET}\n"
