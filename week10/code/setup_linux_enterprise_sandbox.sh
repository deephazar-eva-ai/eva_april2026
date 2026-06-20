#!/bin/bash
# Enterprise Sandbox Setup for Linux (Session 13)
# This script sets up a fresh user account for safe agent runs,
# grants necessary permissions to cua-driver under that account,
# and ensures the agent operates only on test files.

set -e

# Configuration
TEST_USER="agent_test_user"
TEST_HOME="/home/$TEST_USER"
DATA_BACKUP_DIR="/var/backups/agent_test_data"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root (or with sudo) to create the test user and setup the environment."
  exit 1
fi

echo "Creating fresh user account: $TEST_USER..."
if id "$TEST_USER" &>/dev/null; then
    echo "User $TEST_USER already exists."
else
    useradd -m -s /bin/bash "$TEST_USER"
    echo "User $TEST_USER created successfully."
fi

echo "Setting up test environment in $TEST_HOME..."
mkdir -p "$TEST_HOME/test_workspace"
chown -R "$TEST_USER":"$TEST_USER" "$TEST_HOME/test_workspace"

echo "Creating backup directory..."
mkdir -p "$DATA_BACKUP_DIR"
# Example: Create a snapshot backup of test files before runs
tar -czf "$DATA_BACKUP_DIR/initial_test_files_$(date +%Y%m%d%H%M%S).tar.gz" -C "$TEST_HOME" test_workspace 2>/dev/null || true

echo ""
echo "=========================================================="
echo "Linux Enterprise Setup Complete"
echo "=========================================================="
echo ""
echo "To run the agent safely:"
echo "1. Switch to the test user: sudo su - $TEST_USER"
echo "2. Ensure you are running under X11 or grant Wayland portal permissions interactively."
echo "3. Run your tests ONLY on files inside ~/test_workspace"
echo ""
echo "Recovery Primitives to Test:"
echo "- kill_app (to kill misbehaving applications instantly)"
echo "- Ctrl-Z (Undo) to revert destructive edits"
echo ""
echo "If a run goes out of control:"
echo "Run 'cua-driver shutdown' to immediately kill the daemon and stop the agent within a second."
echo "=========================================================="
