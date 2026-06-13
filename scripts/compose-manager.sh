#!/bin/bash

#
# Docker Compose Manager
# Unified script to start, stop, restart, or check status of all compose stacks
#

set -euo pipefail

# Configuration
COMPOSE_DIR="/docker/homelab-config/nemesis/composed-apps"
EXCLUDE_DIRS=("nvidia-test")  # Add directories to skip here

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Function to show usage
usage() {
    echo "Usage: $0 {start|stop|restart|status} [app-name]"
    echo ""
    echo "Commands:"
    echo "  start     - Start all compose stacks (or specific app)"
    echo "  stop      - Stop all compose stacks (or specific app)"
    echo "  restart   - Restart all compose stacks (or specific app)"
    echo "  status    - Show status of all compose stacks"
    echo ""
    echo "Examples:"
    echo "  $0 start              # Start all stacks"
    echo "  $0 start zomboid      # Start only zomboid stack"
    echo "  $0 stop               # Stop all stacks"
    echo "  $0 status             # Show status of all stacks"
    exit 1
}

# Function to check if directory should be excluded
is_excluded() {
    local app_name="$1"
    for exclude in "${EXCLUDE_DIRS[@]}"; do
        if [ "$app_name" = "$exclude" ]; then
            return 0  # true, is excluded
        fi
    done
    return 1  # false, not excluded
}

# Function to start a single compose stack
start_compose() {
    local dir="$1"
    local app_name=$(basename "$dir")

    if is_excluded "$app_name"; then
        echo -e "${YELLOW}⊘ Skipping:${NC} $app_name (excluded)"
        return 2
    fi

    echo -n -e "${BLUE}▶ Starting:${NC} $app_name ... "

    if (cd "$dir" && docker compose up -d 2>&1 | grep -v "is up-to-date" > /tmp/compose-out-$$.log); then
        if grep -q "Started\|Created\|Running" /tmp/compose-out-$$.log 2>/dev/null; then
            echo -e "${GREEN}✓ Started${NC}"
        else
            echo -e "${GREEN}✓ Already running${NC}"
        fi
        rm -f /tmp/compose-out-$$.log
        return 0
    else
        echo -e "${RED}✗ Failed${NC}"
        if [ -f /tmp/compose-out-$$.log ]; then
            sed 's/^/  /' /tmp/compose-out-$$.log
        fi
        rm -f /tmp/compose-out-$$.log
        return 1
    fi
}

# Function to stop a single compose stack
stop_compose() {
    local dir="$1"
    local app_name=$(basename "$dir")

    if is_excluded "$app_name"; then
        echo -e "${YELLOW}⊘ Skipping:${NC} $app_name (excluded)"
        return 2
    fi

    echo -n -e "${BLUE}■ Stopping:${NC} $app_name ... "

    if (cd "$dir" && docker compose down 2>&1 > /tmp/compose-out-$$.log); then
        echo -e "${GREEN}✓ Stopped${NC}"
        rm -f /tmp/compose-out-$$.log
        return 0
    else
        echo -e "${RED}✗ Failed${NC}"
        if [ -f /tmp/compose-out-$$.log ]; then
            sed 's/^/  /' /tmp/compose-out-$$.log
        fi
        rm -f /tmp/compose-out-$$.log
        return 1
    fi
}

# Function to show status of a single compose stack
status_compose() {
    local dir="$1"
    local app_name=$(basename "$dir")

    # Get list of services (run in subshell to preserve current directory)
    local services=$(cd "$dir" && docker compose config --services 2>/dev/null | wc -l)

    # Get running containers
    local running_containers=$(cd "$dir" && docker compose ps -q 2>/dev/null | wc -l)

    # Determine status
    if [ "$running_containers" -eq 0 ]; then
        echo -e "${GRAY}○ Stopped:${NC} $app_name"
        return 2
    elif [ "$running_containers" -eq "$services" ]; then
        echo -e "${GREEN}● Running:${NC} $app_name ($running_containers/$services containers)"
        return 0
    else
        echo -e "${YELLOW}◐ Partial:${NC} $app_name ($running_containers/$services containers)"
        return 1
    fi
}

# Function to process all compose stacks
process_all() {
    local action="$1"
    local target_app="${2:-}"

    local total=0
    local success=0
    local failed=0
    local skipped=0

    # Print header
    case "$action" in
        start)
            echo -e "${BLUE}========================================${NC}"
            echo -e "${BLUE}Starting Docker Compose Stacks${NC}"
            echo -e "${BLUE}========================================${NC}"
            echo ""
            ;;
        stop)
            echo -e "${BLUE}========================================${NC}"
            echo -e "${BLUE}Stopping Docker Compose Stacks${NC}"
            echo -e "${BLUE}========================================${NC}"
            echo ""
            ;;
        status)
            echo -e "${BLUE}========================================${NC}"
            echo -e "${BLUE}Docker Compose Stack Status${NC}"
            echo -e "${BLUE}========================================${NC}"
            echo ""
            ;;
    esac

    # Find all docker-compose files and store in array
    mapfile -t compose_files < <(find "$COMPOSE_DIR" -maxdepth 2 -name "docker-compose.y*ml" -type f | sort)

    # Process each compose file
    for compose_file in "${compose_files[@]}"; do
        dir=$(dirname "$compose_file")
        app_name=$(basename "$dir")

        # If target app specified, only process that one
        if [ -n "$target_app" ] && [ "$app_name" != "$target_app" ]; then
            continue
        fi

        total=$((total + 1))

        case "$action" in
            start)
                set +e
                start_compose "$dir"
                ret=$?
                set -e
                ;;
            stop)
                set +e
                stop_compose "$dir"
                ret=$?
                set -e
                ;;
            status)
                set +e
                status_compose "$dir"
                ret=$?
                set -e
                ;;
        esac

        # Update counters based on return code
        if [ $ret -eq 0 ]; then
            success=$((success + 1))
        elif [ $ret -eq 2 ]; then
            skipped=$((skipped + 1))
        else
            failed=$((failed + 1))
        fi

    done

    # Print summary (not for status command)
    if [ "$action" != "status" ]; then
        echo ""
        echo -e "${BLUE}========================================${NC}"
        echo -e "${BLUE}Summary${NC}"
        echo -e "${BLUE}========================================${NC}"
        echo -e "Total stacks:    $total"
        echo -e "${GREEN}Successful:      $success${NC}"
        echo -e "${RED}Failed:          $failed${NC}"
        echo -e "${YELLOW}Skipped:         $skipped${NC}"
        echo ""

        if [ $failed -gt 0 ]; then
            echo -e "${RED}Some stacks failed. Check the output above for details.${NC}"
            return 1
        else
            echo -e "${GREEN}All stacks processed successfully!${NC}"
        fi
    else
        # Status summary
        local partial=$failed  # For status, failed means partial
        local stopped=$skipped
        local running=$success

        echo ""
        echo -e "${BLUE}========================================${NC}"
        echo -e "${BLUE}Summary${NC}"
        echo -e "${BLUE}========================================${NC}"
        echo -e "${GREEN}Running:  $running${NC}"
        echo -e "${YELLOW}Partial:  $partial${NC}"
        echo -e "${GRAY}Stopped:  $stopped${NC}"
        echo ""
    fi
}

# Main script logic
if [ $# -lt 1 ]; then
    usage
fi

command="$1"
target_app="${2:-}"

case "$command" in
    start)
        process_all "start" "$target_app"
        ;;
    stop)
        process_all "stop" "$target_app"
        ;;
    restart)
        process_all "stop" "$target_app"
        echo ""
        sleep 2
        process_all "start" "$target_app"
        ;;
    status)
        process_all "status"
        ;;
    *)
        echo -e "${RED}Error: Unknown command '$command'${NC}"
        echo ""
        usage
        ;;
esac
