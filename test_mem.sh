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
    
    # Monitor for 60 seconds
    for i in {1..60}; do
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
    echo "Completed $mode mode test."
}

# 2 songs playlist for testing
PLAYLIST="https://www.youtube.com/playlist?list=PL4fGSI1pDJn5kI81J1fYWK5eZRl1zJ5kM"

# Make sure ytstr is executable
chmod +x ./ytstr

# Test 1: Default Mix
measure_mem "python3 ./ytstr $PLAYLIST --no-shuffle" "Default Mix"

# Test 2: Light Mix
measure_mem "python3 ./ytstr $PLAYLIST --light-mix --no-shuffle" "Light Mix"

# Test 3: No Mix
measure_mem "python3 ./ytstr $PLAYLIST --no-mix --no-shuffle" "No Mix"

echo "Done."
