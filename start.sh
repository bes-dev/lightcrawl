#!/bin/bash
set -e

# Generate SearXNG secret key if settings.yml doesn't exist
SETTINGS_FILE="config/searxng/settings.yml"
TEMPLATE_FILE="config/searxng/settings.yml.template"

if [ ! -f "$SETTINGS_FILE" ]; then
    echo "Generating SearXNG config with random secret key..."
    SECRET_KEY=$(openssl rand -hex 32)
    sed "s/\${SEARXNG_SECRET_KEY}/$SECRET_KEY/" "$TEMPLATE_FILE" > "$SETTINGS_FILE"
fi

PROFILES="--profile mcp --profile playwright"

case "${1:-}" in
    --minimal)
        PROFILES=""
        echo "Starting LightCrawl (minimal - API only)..."
        ;;
    *)
        echo "Starting LightCrawl (full)..."
        ;;
esac

docker compose $PROFILES up -d

echo ""
echo "LightCrawl ready:"
echo "  API: http://localhost:3002"
if [ -n "$PROFILES" ]; then
    echo "  MCP: http://localhost:8000/sse"
    echo "  Playwright: http://localhost:3000 (internal)"
fi
echo ""
echo "Usage:"
echo "  ./start.sh           # Full (API + MCP + Playwright)"
echo "  ./start.sh --minimal # API only"
