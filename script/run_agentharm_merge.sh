#!/usr/bin/env bash
set -euo pipefail

# Run AgentHarm merged (benign + harmful) per-category, similar to run_rjudge_merge.sh
# Notes:
# - pipeline.py now supports: --agentharm_merge_splits + --agentharm_category
# - We merge simulated data by default (no --need_simulate):
#   data is read from data/agentharm/<Category>/{benign,harmful}_simulate.jsonl

export CUDA_VISIBLE_DEVICES=1
cd ..

SIMULATE_MODEL="gemini-3-pro-preview"
ANALYSIS_MODEL="gemini-3-pro-preview"
FUSION_MODEL="gemini-3-pro-preview"
AUDITOR_MODEL="gemini-3-pro-preview"
EXECUTOR_MODEL="gemini-3-pro-preview"
SEED=44

# Categories in AgentHarm (adjust as needed)
# CATEGORIES=("Cybercrime" "Fraud" "Disinformation" "Copyright" "Hate" "Drugs" "Sexual" "Harassment")
CATEGORIES=("Copyright" "Hate" "Drugs" "Sexual" "Harassment")

echo "========================================"
echo "DEFEND Pipeline AgentHarm MERGED Batch Evaluation"
echo "========================================"
echo "Categories: ${CATEGORIES[@]}"
echo "Mode: merged (benign + harmful)"
echo "========================================"
echo ""

PIDS=()

for category in "${CATEGORIES[@]}"; do
    echo "========================================="
    echo " Starting AgentHarm / $category / merged"
    echo "========================================="

    dataset="agentharm_${category}_merged"

    risk_memory="lifelong_library/agentharm/risks_${dataset}.json"
    tool_memory="lifelong_library/agentharm/safety_tools_${dataset}.json"

    fail_tool_debug="debugs/agentharm/fail_tool_${dataset}.json"
    debug_doubt_tool="debugs/agentharm/debug_doubt_tool_${dataset}.log"
    debug_decision="debugs/agentharm/debug_decision_${dataset}.log"

    LOG_DIR="logs/agentharm_new"
    mkdir -p "$LOG_DIR"
    LOG_FILE="$(pwd)/${LOG_DIR}/${category}_merged.log"

    mkdir -p "lifelong_library/agentharm" "debugs/agentharm"

    nohup python -u pipeline.py \
        --dataset "agentharm" \
        --agentharm_merge_splits \
        --agentharm_category "$category" \
        --risk_memory "$risk_memory" \
        --tool_memory "$tool_memory" \
        --simulate_model "$SIMULATE_MODEL" \
        --analysis_model "$ANALYSIS_MODEL" \
        --fusion_model "$FUSION_MODEL" \
        --auditor_model "$AUDITOR_MODEL" \
        --executor_model "$EXECUTOR_MODEL" \
        --seed "$SEED" \
        --restart \
        --fail_tool_debug "$fail_tool_debug" \
        --debug_doubt_tool_path "$debug_doubt_tool" \
        --debug_decision_path "$debug_decision" > "$LOG_FILE" 2>&1 &

    PID=$!
    PIDS+=("$PID")

    echo "✓ Task started with PID: $PID"
    echo "  Log: $LOG_FILE"
    echo "  Category: $category"
    echo "  Dataset (merged): $dataset"
    echo ""
done

if [ ${#PIDS[@]} -gt 0 ]; then
    echo "All tasks started. PIDs: ${PIDS[@]}"
fi
