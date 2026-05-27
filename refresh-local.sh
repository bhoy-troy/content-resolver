#!/bin/bash

# Local version of refresh.sh for development
# Runs content_resolver.py without S3 sync operations
# Designed to be used in docker-compose with Docker-in-Docker support

set -e  # Exit on error

echo ""
echo "========================================"
echo "Content Resolver - Local Development Run"
echo "========================================"
echo ""

# Ensure output directory exists
mkdir -p out/history || exit 1

# Build timestamp for logging
build_started=$(date +"%Y-%m-%d-%H%M")
echo "Build started: $build_started"
echo ""

# Check if Docker is available (for DinD scenarios)
if command -v docker &> /dev/null; then
    echo "✅ Docker available (Docker-in-Docker enabled)"
    docker --version
    echo ""
fi

# Run the content resolver
# Note: This assumes it's running inside a container with:
#   - /workspace mounted to the project root
#   - /dnf_cachedir available (tmpfs or volume)
#   - /var/run/docker.sock mounted (for Docker-in-Docker)
echo "Running content resolver..."
echo "Labels: eln (reduced scope to avoid OOM)"
echo "Input: content-resolver-input/configs"
echo "Output: out/"
echo ""

./content_resolver.py \
  --labels eln \
  --dnf-cache-dir /dnf_cachedir \
  content-resolver-input/configs \
  out

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "========================================"
    echo "✅ Content resolver completed successfully"
    echo "========================================"
    echo ""
    echo "Output available in: out/"
    echo "Open out/index.html to view results"
    echo ""
else
    echo ""
    echo "========================================"
    echo "❌ Content resolver failed with exit code: $exit_code"
    echo "========================================"
    echo ""
    exit $exit_code
fi
