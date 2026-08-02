#!/bin/bash
# deploy.sh - Script to pull latest changes and restart Docker containers

echo "🚀 Starting Deployment..."

# 1. Pull latest code from main
echo "📥 Pulling latest code from git..."
git pull origin main

# 2. Rebuild and restart containers in the background
echo "🐳 Rebuilding and starting Docker containers..."
docker compose -f docker-compose.prod.yml up --build -d

echo "✅ Deployment complete! Run 'docker compose -f docker-compose.prod.yml logs -f' to view logs."
