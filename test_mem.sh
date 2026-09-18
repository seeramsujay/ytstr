#!/bin/bash
rm -f errors.md test.md

echo "## Memory Test Results" > test.md

measure_mem() {
    local cmd=$1
    local mode=$2
    echo "Running in $mode mode..."
    echo "Command: $cmd"
    
    # Run in background
    $cmd > /dev/null 2>>errors.md &
    local pid=$!
    
    local max_mem=0
    
    # Monitor for 20 seconds per mode
    for i in {1..20}; do
        if ! kill -0 $pid 2>/dev/null; then
            break
        fi
        
        # Get memory in KB (RSS)
        local mem=$(ps -o rss= -p $pid 2>/dev/null)
        if [ ! -z "$mem" ]; then
            if [ "$mem" -gt "$max_mem" ]; then
                max_mem=$mem
            fi
        fi
        sleep 1
    done
    
    # Kill the process and its children if still running
    pkill -P $pid 2>/dev/null
    kill $pid 2>/dev/null
    
    # Convert KB to MB
    local max_mem_mb=$(echo "scale=2; $max_mem / 1024" | bc)
    
    echo "* **$mode Mode**: Peak RAM usage was ${max_mem_mb} MB" >> test.md
    echo "Completed $mode mode test: ${max_mem_mb} MB."
}

PLAYLIST="https://www.youtube.com/playlist?list=PL4fGSI1pDJn5kI81J1fYWK5eZRl1zJ5kM"

chmod +x ./ytstr

# Test 1: Direct No-Mix
measure_mem "uv run ./ytstr $PLAYLIST --no-mix --no-shuffle" "Direct No-Mix"

# Test 2: Direct Stream
measure_mem "uv run ./ytstr $PLAYLIST --stream --no-shuffle" "Direct Stream"

# Test 3: Light Mix
measure_mem "uv run ./ytstr $PLAYLIST --light-mix --no-shuffle" "Light Mix"

# Test 4: Auto-DJ Mix
measure_mem "uv run ./ytstr $PLAYLIST --no-shuffle" "Auto-DJ Mix"

echo "Done."
