#!/bin/bash
# Run match simulations in parallel.
#
# Usage:
#   ./run_simulations.sh                              # default: arsenal-chelsea + leeds-sunderland
#   ./run_simulations.sh mancity-manutd palace-spurs  # specific matches
#   ./run_simulations.sh arsenal-chelsea mancity-manutd palace-spurs leeds-sunderland  # all four
#
# Available match keys:
#   arsenal-chelsea     Arsenal vs Chelsea (PL title race)
#   leeds-sunderland    Leeds vs Sunderland (Championship promotion)
#   mancity-manutd      Man City vs Man Utd (Manchester Derby, Haaland milestone)
#   palace-spurs        Crystal Palace vs Tottenham (relegation vs Champions League)
#
# NOTE: Before running a new fixture for the first time, upload its stats to GCS:
#   python cloud_run_job/upload_stats.py \
#     --fixture-id man-city-vs-man-utd-2025-03-15 \
#     --stats-file historical_stats.json
#   python cloud_run_job/upload_stats.py \
#     --fixture-id crystal-palace-vs-tottenham-2025-03-15 \
#     --stats-file historical_stats.json

cd "$(dirname "$0")"

MATCHES=("$@")
if [ ${#MATCHES[@]} -eq 0 ]; then
    MATCHES=("arsenal-chelsea" "leeds-sunderland")
fi

BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"

echo "Starting simulations: ${MATCHES[*]}"
for match in "${MATCHES[@]}"; do
    python simulate_match.py --match "$match" --delay 4 --local "$BACKEND_URL" &
done
wait
echo "All simulations complete."
