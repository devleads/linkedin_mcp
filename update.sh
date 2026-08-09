#!/bin/bash
set -e

echo "=== LinkedIn MCP Server Update ==="

# Stop and remove existing containers
echo "Stopping existing containers..."
if docker compose version &> /dev/null; then
  docker compose down --remove-orphans
else
  docker-compose down --remove-orphans
fi

# Clean up unused Docker objects (keep volumes for browser state)
echo "Cleaning up unused Docker objects..."
docker system prune -f

# Build and start containers
# Migration runs first (service_completed_successfully), then mcp-server starts
echo "Building and starting containers..."
if docker compose version &> /dev/null; then
  docker compose up --detach --build
else
  docker-compose up --detach --build
fi

echo "=== Update complete! ==="
echo ""
echo "Container status:"
docker ps -f "name=linkedin-mcp" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "Migration logs:"
if docker compose version &> /dev/null; then
  docker compose logs migration --tail=10
else
  docker-compose logs migration --tail=10
fi