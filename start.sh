#!/usr/bin/env bash

set -e

# Stop and remove containers (but keep volumes for certificate persistence)
sudo docker-compose down --remove-orphans

# Build and start services
sudo docker-compose up -d --build