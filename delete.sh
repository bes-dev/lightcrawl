#!/bin/bash
# Delete all services, volumes, and images (including optional profiles)
docker compose --profile mcp --profile playwright down -v --rmi all
echo "LightCrawl deleted (containers, volumes, images)"
