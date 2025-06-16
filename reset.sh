#!/usr/bin/env bash

set -e

echo "⚠️  WARNING: This will remove ALL data including SSL certificates!"
echo "   Use this only for debugging or complete reset."
echo ""
echo "   For normal restarts, use: ./start.sh"
echo ""
read -p "Are you sure you want to reset everything? [y/N] " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🗑️  Removing all containers, volumes, and data..."
    
    # Stop and remove everything including volumes
    sudo docker-compose down --volumes --remove-orphans
    
    # Build and start fresh
    sudo docker-compose up -d --build
    
    echo "✅ Complete reset finished!"
else
    echo "❌ Reset cancelled."
fi 