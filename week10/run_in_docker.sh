#!/bin/bash
set -e

# Change to the week10 directory
cd "$(dirname "$0")"

# Build the docker image
echo "Building the week10-agent docker image..."
docker build --network host -t week10-agent .

# Clean up any stale LibreOffice lock files to prevent "Document in Use" errors
echo "Cleaning up stale LibreOffice lock files..."
find "$(pwd)/data" -type f -name ".~lock.*#" -delete 2>/dev/null || true

# Auto-backup ODS files before each run (agent may corrupt them)
for f in "$(pwd)"/data/*.ods; do
    [ -f "$f" ] && cp "$f" "${f}.bak"
done

# Run the container
echo "Running the agent in Docker..."
# We use --network host so localhost:8109 resolves to the host's gateway
docker run -it \
    --network host \
    --memory="4g" \
    --cpus="2.0" \
    -v "$(pwd)/trajectories:/app/trajectories" \
    -v "$(pwd)/code:/app/code" \
    -v "$(pwd)/data:$(pwd)/data" \
    week10-agent "$@"
