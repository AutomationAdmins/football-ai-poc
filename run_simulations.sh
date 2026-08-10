#!/bin/bash
# Run both match simulations in parallel
cd "$(dirname "$0")"

python3 simulate_match.py --fixture-id arsenal-vs-chelsea-2025-08-02 --delay 4 &
python3 simulate_leeds_sunderland.py --fixture-id leeds-vs-sunderland-2025-08-02 --delay 4 &
wait
