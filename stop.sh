#!/usr/bin/env bash

set -e

# Stop and remove containers and volumes
sudo docker-compose down --volumes --remove-orphans 