#!/bin/bash
# Stop all services (including optional profiles)
docker compose --profile mcp --profile playwright down
echo "LightCrawl stopped"
