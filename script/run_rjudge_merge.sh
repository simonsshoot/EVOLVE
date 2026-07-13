export CUDA_VISIBLE_DEVICES=1
cd ..

SIMULATE_MODEL="deepseek-chat"
ANALYSIS_MODEL="deepseek-chat"
FUSION_MODEL="deepseek-chat"
AUDITOR_MODEL="deepseek-chat"
EXECUTOR_MODEL="deepseek-chat"
SEED=44

# SUBFOLDERS=("Application" "Finance" "IoT" "Program" "Web")
SUBFOLDERS=("Web")

echo "========================================"
echo "DEFEND Pipeline R-Judge MERGED Batch Evaluation"
echo "========================================"
echo "Subfolders: ${SUBFOLDERS[@]}"
echo "Mode: merged (benign + harmful)"
echo "========================================"
echo ""

# 存储所有后台进程的PID
PIDS=()

for subfolder in "${SUBFOLDERS[@]}"; do
    echo "========================================="
    echo " Starting R-Judge / $subfolder / merged"
    echo "========================================="


    risk_memory="lifelong_library/rjudge_new/risks_rjudge_${subfolder}.json"
    tool_memory="lifelong_library/rjudge_new/safety_tools_rjudge_${subfolder}.json"

    fail_tool_debug="debugs/rjudge/fail_tool_rjudge_${subfolder}_merged.json"
    debug_doubt_tool="debugs/rjudge/debug_doubt_tool_rjudge_${subfolder}_merged.log"
    debug_decision="debugs/rjudge/debug_decision_rjudge_${subfolder}_merged.log"

    LOG_DIR="logs/rjudge_new"
    mkdir -p "$LOG_DIR"
    LOG_FILE="$(pwd)/${LOG_DIR}/${subfolder}_merged.log"

    nohup python -u pipeline.py \
        --dataset "rjudge" \
        --rjudge_merge_splits \
        --rjudge_category "$subfolder" \
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
    echo "  Category: $subfolder"
    echo ""
done

if [ ${#PIDS[@]} -gt 0 ]; then
    echo "All tasks started. PIDs: ${PIDS[@]}"
fi
