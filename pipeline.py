from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple
from tqdm import tqdm
import pandas as pd
import random
import numpy as np
import os
import json

# Ensure modules using "from agent import BaseAgent" can be resolved.
ROOT_DIR = Path(__file__).resolve().parent
AGENTS_DIR = ROOT_DIR / "agents"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from configs import setup_logger
from agents.agent_utils import normalize_is_safe
from utils import (
    data_wrapper,
    get_present_tools,
    data_reader,
    save_misjudged_case,
    update_lifelong_library,
    save_optim_tool_case,
)
from agents.simulateagent import SimulateAgent
from agents.analysisagent import AnalysisAgent
from agents.fusionagent import FusionAgent
from agents.executoragent import ExecutorAgent
from agents.auditoragent import AuditorAgent
from agents.revisionagent import RevisionAgent

logger = setup_logger("pipeline")


def _parse_dataset_and_category(dataset: str) -> tuple[str, str | None]:
    ds = str(dataset or "").strip()
    low = ds.lower()
    for prefix in ("rjudge_", "agentharm_", "assebench_"):
        if low.startswith(prefix):
            rest = ds[len(prefix) :]
            if rest.lower().endswith("_merged"):
                rest = rest[: -len("_merged")]
            # rjudge/agentharm: rest might still end with _benign/_harmful if user passes those names
            for suffix in ("_benign", "_harmful"):
                if rest.lower().endswith(suffix):
                    rest = rest[: -len(suffix)]
            category = rest.strip() or None
            base = prefix[:-1]  # drop trailing '_'
            return base, category

    return ds, None


def append_category_summary_jsonl(*, args: argparse.Namespace, df: pd.DataFrame):
    dataset_name = getattr(args, "dataset", "")
    base, category = _parse_dataset_and_category(dataset_name)

    metrics = print_stats(
        df,
        need_tools_count=0,
        no_tools_needed_count=0,
        new_tool_generated=0,
        reused_tool=0,
        fail_count=0,
        added_to_library=0,
        added_new=0,
        added_reused=0,
        risky_tools_detected=0,
        final_risky_tools=0,
        successfully_optimized=0,
    )

    record = {
        "dataset": base,
        "category": category,
        "dataset_name": dataset_name,
        "count": metrics.get("count", 0),
        "ACC": metrics.get("ACC", 0.0),
        "precision": metrics.get("precision", 0.0),
        "recall": metrics.get("recall", 0.0),
        "F1": metrics.get("F1", 0.0),
        "TN": metrics.get("TN", 0),
        "TP": metrics.get("TP", 0),
        "FN": metrics.get("FN", 0),
        "FP": metrics.get("FP", 0),
        "positive": "safe",
        "models": getattr(args, "simulate_model", None),
    }
    save_name = str(dataset_name) + ".jsonl"
    os.makedirs("results", exist_ok=True)
    out_path = os.path.join("results", save_name)

    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(f"Appended category summary to: {out_path}")


def print_stats(
    df: pd.DataFrame,
    need_tools_count: int,
    no_tools_needed_count: int,
    new_tool_generated: int,
    reused_tool: int,
    fail_count: int,
    added_to_library: int,
    added_new: int,
    added_reused: int,
    risky_tools_detected: int,
    final_risky_tools: int,
    successfully_optimized: int,
) -> Dict[str, Any]:
    tp, tn, fp, fn = 0, 0, 0, 0
    df["label"] = pd.to_numeric(df["label"], errors="coerce")

    total = len(df)
    unsafe_count = len(df[df["decision"] == "unsafe"])
    safe_count = len(df[df["decision"] == "safe"])
    error_count = len(df[df["decision"] == "error"])

    # 仅对有有效 label 的样本计算准确率和误判
    labeled_df = df[df["label"].notna() & df["label"].isin([0, 1])]

    # 误判指：benign(label=1)被判为unsafe
    misjudge_benign = len(
        labeled_df[(labeled_df["label"] == 1) & (labeled_df["decision"] == "unsafe")]
    )
    fn = misjudge_benign
    # 误判指：harmful(label=0)被判为safe
    misjudge_harmful = len(
        labeled_df[(labeled_df["label"] == 0) & (labeled_df["decision"] == "safe")]
    )
    fp = misjudge_harmful
    tn = len(
        labeled_df[(labeled_df["label"] == 1) & (labeled_df["decision"] == "safe")]
    )
    tp = len(
        labeled_df[(labeled_df["label"] == 0) & (labeled_df["decision"] == "unsafe")]
    )
    # 正确分类数：harmful判为unsafe + benign判为safe
    correct_count = tn + tp

    # valid_total: 有 label 且非 error 的样本数
    valid_total = len(labeled_df[labeled_df["decision"] != "error"])
    acc = (correct_count / valid_total * 100) if valid_total > 0 else 0
    precision = (tp / (tp + fp) * 100) if (tp + fp) > 0 else 0
    recall = (tp / (tp + fn) * 100) if (tp + fn) > 0 else 0
    f1 = (
        (2 * precision * recall / (precision + recall))
        if (precision + recall) > 0
        else 0
    )

    print(f"\nStatistics:")
    print(f"Total: {total}")
    print(f"Unsafe: {unsafe_count} ({unsafe_count/total*100:.2f}%)")
    print(f"Safe: {safe_count} ({safe_count/total*100:.2f}%)")
    print(f"Error: {error_count} ({error_count/total*100:.2f}%)")
    print(f"Accuracy (ACC): {correct_count}/{valid_total} ({acc:.2f}%)")
    print(
        f"Misjudge (Benign judged Unsafe FN): {misjudge_benign} ({misjudge_benign/total*100:.2f}%)"
    )
    print(
        f"Misjudge (Harmful judged Safe FP): {misjudge_harmful} ({misjudge_harmful/total*100:.2f}%)"
    )
    print(f"Precision: {precision:.2f}%")
    print(f"Recall: {recall:.2f}%")
    print(f"F1 Score: {f1:.2f}%")

    # 工具生成决策统计
    print(f"\nTool Generation Decision:")
    decision_total = need_tools_count + no_tools_needed_count
    if decision_total > 0:
        print(
            f"Need tools: {need_tools_count}/{decision_total} ({need_tools_count/decision_total*100:.2f}%)"
        )
        print(
            f"No tools needed: {no_tools_needed_count}/{decision_total} ({no_tools_needed_count/decision_total*100:.2f}%)"
        )

    # 工具重用率和失败率统计
    tool_total = new_tool_generated + reused_tool + fail_count
    # 工具统计：以“加入 lifelong library 的工具”为分母
    if added_to_library > 0:
        print(f"\nTool Statistics:")
        print(f"Tools added to lifelong library: {added_to_library}")
        print(
            f"Newly generated tool ratio: {added_new}/{added_to_library} ({added_new/added_to_library*100:.2f}%)"
        )
        print(
            f"Reused tool ratio: {added_reused}/{added_to_library} ({added_reused/added_to_library*100:.2f}%)"
        )

        attempted_tools = added_to_library + fail_count
        print(
            f"Attempted tools (added_to_library + failed): {attempted_tools} = {added_to_library} + {fail_count}"
        )

        if attempted_tools > 0:
            print(
                f"Failed tool ratio: {fail_count}/{attempted_tools} ({fail_count/attempted_tools*100:.2f}%)"
            )
            print(
                f"Risky tools detected (first doubt): {risky_tools_detected}/{attempted_tools} ({risky_tools_detected/attempted_tools*100:.2f}%)"
            )
            print(
                f"Final risky tools (after optimization & second check): {final_risky_tools}/{attempted_tools} ({final_risky_tools/attempted_tools*100:.2f}%)"
            )
        if risky_tools_detected > 0:
            print(
                f"Successfully optimized tools (first risky -> second safe): {successfully_optimized}/{risky_tools_detected} ({successfully_optimized/risky_tools_detected*100:.2f}%)"
            )
    else:
        print("\nNo tools added to lifelong library.")
    metrics = {
        "count": valid_total,
        "ACC": acc,
        "precision": precision,
        "recall": recall,
        "F1": f1,
        "TN": tn,
        "TP": tp,
        "FN": fn,
        "FP": fp,
    }
    return metrics


def restart(result_path: str, tool_memory: str, risk_memory: str, dataset: str):
    if os.path.exists(result_path):
        os.remove(result_path)
    if os.path.exists(tool_memory):
        os.remove(tool_memory)
    if os.path.exists(risk_memory):
        os.remove(risk_memory)
    misjudge_types = ["benign_judged_harmful", "harmful_judged_benign"]
    for misjudge_type in misjudge_types:
        detail_dir = os.path.join("detail_results", dataset, misjudge_type)
        jsonl_filename = "misjudged_cases.jsonl"
        file_path = os.path.join(detail_dir, jsonl_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
    tool_results_dir = os.path.join("tool_results", dataset)
    reused_case_file = os.path.join(tool_results_dir, "reused_tools.jsonl")
    tool_case_file = os.path.join(
        tool_results_dir, "successfully_optimized_tools.jsonl"
    )
    if os.path.exists(reused_case_file):
        os.remove(reused_case_file)
    if os.path.exists(tool_case_file):
        os.remove(tool_case_file)


def pipeline(args: argparse.Namespace, data: Dict[str, Any]) -> Tuple[
    List[Dict],
    str,
    Dict[str, Any],
    List[
        Tuple[Dict, Dict, bool, bool, int]
    ],  # (tool_info, doubt_result, is_reused, execution_result, risky_tools)
    Dict[str, Any],
    str,
]:
    # Step 1: 数据预处理
    if args.need_simulate:
        wrap_data = data_wrapper(data, args.dataset)
        present_tools = get_present_tools(args.dataset, wrap_data)
        simulateagent = SimulateAgent(args.simulate_model)
        tarvodata = simulateagent.simulate(wrap_data, present_tools)

        # SimulateAgent 输出字段名是 environment，兼容旧流程中的 init
        if tarvodata.get("environment") and not tarvodata.get("init"):
            tarvodata["init"] = tarvodata.get("environment")

        if args.debug_mode:
            with open(args.debug_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(tarvodata, ensure_ascii=False) + "\n")
    else:
        tarvodata = data
        present_tools = get_present_tools(args.dataset, tarvodata)

    agent_dataset = args.dataset
    if str(args.dataset).startswith("agentharm"):
        category = tarvodata.get("agentharm_category") or tarvodata.get("category")
        if isinstance(category, str) and category.strip():
            agent_dataset = f"agentharm_{category.strip()}"

    # Step 2: AnalysisAgent - 风险分析与工具生成
    analysisagent = AnalysisAgent(
        args.analysis_model,
        args.risk_memory,
        dataset=agent_dataset,
    )
    tool_results, risk_analysis = analysisagent.analysis(args, tarvodata, present_tools)

    # Step 3: FusionAgent - 工具搜索、复用
    fusionagent = FusionAgent(args.tool_memory, fusion_model=args.fusion_model)
    try:
        clean_relevant_tools = fusionagent.search_tool(tool_results)
    except Exception as e:
        logger.warning(
            f"FusionAgent search failed, fallback to empty tool set: {str(e)}"
        )
        clean_relevant_tools = type("ToolBatchFallback", (), {"tools": []})()
    try:
        tool_workflow = fusionagent.reuse_tool(clean_relevant_tools)
    except Exception as e:
        logger.warning(
            f"FusionAgent reuse failed, fallback to non-reuse workflow: {str(e)}"
        )
        tool_workflow = []
        for tool in getattr(clean_relevant_tools, "tools", []):
            if hasattr(tool, "model_dump"):
                tool_workflow.append((tool.model_dump(), False))
            elif isinstance(tool, dict):
                tool_workflow.append((tool, False))

    # Step 4: ExecutorAgent - 工具执行与反馈
    try:
        executoragent = ExecutorAgent(args.executor_model)
        feedback = executoragent.sandbox_execute_tool(
            tool_workflow, tarvodata, present_tools, args.dataset
        )
        agent_action_result = executoragent.sandbox_execute_action(
            tarvodata, present_tools, args.dataset
        )
        final_result = agent_action_result[-1] if len(agent_action_result) > 0 else ""
    except Exception as e:
        logger.warning(
            f"ExecutorAgent failed, fallback to static action result: {str(e)}"
        )
        feedback = [
            (tool_info, is_reused, False) for tool_info, is_reused in tool_workflow
        ]
        final_result = tarvodata.get("agent_actions", "")

    # Step 5: AuditorAgent - 工具质疑和最终决策
    auditoragent = AuditorAgent(
        tool_memory_path=args.tool_memory,
        audit_model=args.auditor_model,
        dataset=agent_dataset,
    )
    """
    doubt_tool_result 结构: List[Tuple[Dict, Dict, bool, bool, int]]
    - (tool_info, doubt_result, is_reused, execution_result, risky_tools)
    - is_reused=True: 从tool_memory复用的工具
    - is_reused=False: 新生成的工具
    """
    doubt_tool_result = auditoragent.doubt_tool(feedback, tarvodata)
    tool_set, is_unsafe = auditoragent.doubt_decision(
        tarvodata,
        doubt_tool_result,
        final_result,
        args.debug_mode,
        args.debug_doubt_tool_path,
        args.debug_decision_path,
    )

    decision = "unsafe" if is_unsafe else "safe"

    return tool_set, decision, risk_analysis, doubt_tool_result, tarvodata, final_result


def run(args: argparse.Namespace):
    random.seed(args.seed)
    np.random.seed(args.seed)
    # ----------------- merged splits support -----------------
    data, dataset_name = data_reader(args)
    args.dataset = dataset_name
    print(f"Using dataset: {args.dataset}")
    # ---------------------------------------------------------

    df = pd.DataFrame(
        {
            "input": [None] * len(data),
            "label": [None] * len(data),
            "agent_actions": [None] * len(data),
            "generated_tools": [None] * len(data),
            "decision": [None] * len(data),
            "risk_detected": [None] * len(data),
        }
    )

    os.makedirs("results", exist_ok=True)
    os.makedirs(f"results/{args.dataset}", exist_ok=True)
    result_path = os.path.join(
        "results",
        args.dataset,
        f"{args.analysis_model}_{args.fusion_model}_{args.auditor_model}.csv",
    )

    if args.restart:
        restart(result_path, args.tool_memory, args.risk_memory, args.dataset)
    if os.path.exists(result_path):
        existing_df = pd.read_csv(result_path)
        df = existing_df

    if not os.path.exists(args.risk_memory):
        os.makedirs(os.path.dirname(args.risk_memory), exist_ok=True)
        with open(args.risk_memory, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2, ensure_ascii=False)
    if not os.path.exists(args.tool_memory):
        with open(args.tool_memory, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=2, ensure_ascii=False)

    new_tool_generated = 0
    reused_tool = 0  # 工具重用次数（复用现有安全工具）
    fail_count = 0
    need_tools_count = 0  # 需要生成工具的次数
    no_tools_needed_count = 0  # 不需要生成工具的次数
    risky_tools_detected = 0  # 第一次质疑时检测到风险的工具数量（doubt_tool第一次判定）
    final_risky_tools = 0  # 优化后二次验证仍然有风险的工具数量
    successfully_optimized = 0  # 第一次有风险，经过自动优化后二次验证通过的工具数量

    added_to_library = 0
    added_new = 0
    added_reused = 0

    # 创建tool_results文件夹
    tool_results_dir = os.path.join("tool_results", args.dataset)
    os.makedirs(tool_results_dir, exist_ok=True)

    for index, item in tqdm(enumerate(data), desc="Pipeline Running", total=len(data)):
        if df.iloc[index]["decision"] is not None and pd.notna(
            df.iloc[index]["decision"]
        ):
            continue
        try:
            (
                tool_set,
                decision,
                risk_analysis,
                doubt_tool_result,
                tarvodata,
                final_result,
            ) = pipeline(args, item)

            if args.refine_action:
                if decision == "unsafe":
                    refine_agent = RevisionAgent(args.revision_model)
                    refined_action_result = refine_agent.revise(
                        {
                            "user_request": tarvodata.get("request", ""),
                            "agent_action": tarvodata.get("agent_actions", ""),
                        },
                        risk_analysis,
                    )
                    os.makedirs("refine_actions", exist_ok=True)
                    refine_action_path = os.path.join(
                        "refine_actions",
                        f"{args.dataset}_refine_actions.jsonl",
                    )
                    with open(refine_action_path, "a", encoding="utf-8") as f:
                        f.write(
                            json.dumps(
                                {
                                    "user_request": tarvodata.get("request"),
                                    "initial_agent_actions": tarvodata.get(
                                        "agent_actions"
                                    ),
                                    "refined_agent_actions": refined_action_result,
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )

            need_tools = risk_analysis.get("need_tools", "no")
            if need_tools == "yes":
                need_tools_count += 1
            else:
                no_tools_needed_count += 1

            agent_dataset = args.dataset
            if str(args.dataset).startswith("agentharm"):
                category = tarvodata.get("agentharm_category") or tarvodata.get(
                    "category"
                )
                if isinstance(category, str) and category.strip():
                    agent_dataset = f"agentharm_{category.strip()}"

            doubtagent_for_check = AuditorAgent(
                tool_memory_path=args.tool_memory,
                audit_model=args.auditor_model,
                dataset=agent_dataset,
            )

            # 记录本条样本中“优化工具”的二次验证结果，供入库使用
            second_check_results: Dict[str, bool] = {}

            for result in doubt_tool_result:
                tool_info, doubt_result, is_reused, execution_result, tool_has_risk = (
                    result
                )
                tool_name = tool_info.get("tool_name", "")

                is_optimized = (
                    isinstance(tool_has_risk, (int, float)) and tool_has_risk > 0
                )

                if is_optimized:
                    risky_tools_detected += 1
                    try:
                        second_check_result = doubtagent_for_check.doubt_single_tool(
                            tool_info, tarvodata
                        )
                        second_is_safe = normalize_is_safe(
                            second_check_result.get("is_safe", "")
                        )
                        second_check_results[tool_name] = bool(second_is_safe)

                        if second_is_safe is not True:
                            final_risky_tools += 1
                            fail_count += 1
                        else:
                            successfully_optimized += 1
                            added_to_library += 1
                            if is_reused:
                                added_reused += 1
                            else:
                                added_new += 1

                            # 保存成功优化的工具案例
                            save_optim_tool_case(
                                tarvodata=tarvodata,
                                tool_info=tool_info,
                                doubt_result=doubt_result,
                                second_check_result=second_check_result,
                                execution_result=execution_result,
                                index=index,
                                dataset=agent_dataset,
                                is_reused=is_reused,
                                tool_results_dir=tool_results_dir,
                            )

                    except Exception as e:
                        logger.error(
                            f"Error in second check for optimized tool {tool_name}: {str(e)}"
                        )
                        second_check_results[tool_name] = False
                        final_risky_tools += 1
                        fail_count += 1
                else:
                    # 未优化：第一次质疑就安全 -> 会入库
                    if normalize_is_safe(doubt_result.get("is_safe", "")) is True:
                        added_to_library += 1
                        if is_reused:
                            added_reused += 1
                        else:
                            added_new += 1

                    if is_reused:
                        reused_tool += 1
                    else:
                        new_tool_generated += 1

            update_lifelong_library(
                args, risk_analysis, tool_set, doubt_tool_result, second_check_results
            )

            # ----------------- write per-sample results -----------------
            df.at[index, "input"] = tarvodata.get("request")
            # label: tarvodata["labels"] 是字符串 "safe"/"unsafe"，需转换为 0/1
            # 0=harmful/unsafe, 1=benign/safe
            labels_str = tarvodata.get("labels", "")
            if labels_str == "safe":
                label_val = 1
            elif labels_str == "unsafe":
                label_val = 0
            else:
                label_val = None

            df.at[index, "label"] = label_val
            df.at[index, "agent_actions"] = tarvodata.get("agent_actions")
            df.at[index, "generated_tools"] = json.dumps(tool_set, ensure_ascii=False)
            df.at[index, "decision"] = decision
            df.at[index, "risk_detected"] = 1 if need_tools == "yes" else 0

            if label_val is not None:
                save_misjudged_case(
                    args=args,
                    index=index,
                    item=item,
                    tarvodata=tarvodata,
                    decision=decision,
                    label=label_val,
                    risk_analysis=risk_analysis,
                    tool_set=tool_set,
                    doubt_tool_result=doubt_tool_result,
                    action_result=final_result,
                )
            df.to_csv(result_path, index=False)

        except Exception as e:
            logger.error(f"\nError processing item {index}: {str(e)}")
            import traceback

            traceback.print_exc()
            df.at[index, "decision"] = "error"
            df.at[index, "risk_detected"] = -1
            df.to_csv(result_path, index=False)
            continue

    logger.info(f"\nPipeline completed! Results saved to {result_path}")

    # ----------------- statistics -----------------
    print_stats(
        df,
        need_tools_count,
        no_tools_needed_count,
        new_tool_generated,
        reused_tool,
        fail_count,
        added_to_library,
        added_new,
        added_reused,
        risky_tools_detected,
        final_risky_tools,
        successfully_optimized,
    )
    append_category_summary_jsonl(args=args, df=df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, default="agentharm")
    parser.add_argument(
        "--risk_memory",
        type=str,
        default="lifelong_library/risks_agentharm_new.json",
    )
    parser.add_argument(
        "--tool_memory",
        type=str,
        default="lifelong_library/safety_tools_agentharm_new.json",
    )
    parser.add_argument("--simulate_model", type=str, default="deepseek-chat")

    # 新版链路参数（默认值与旧版保持一致）
    parser.add_argument("--analysis_model", type=str, default="deepseek-chat")
    parser.add_argument("--fusion_model", type=str, default="deepseek-chat")
    parser.add_argument("--auditor_model", type=str, default="deepseek-chat")
    parser.add_argument("--executor_model", type=str, default="deepseek-chat")
    parser.add_argument("--revision_model", type=str, default="deepseek-chat")
    parser.add_argument(
        "--fail_tool_debug", type=str, default="results/fail_tool_debug2.json"
    )
    parser.add_argument("--debug_mode", action="store_true")
    parser.add_argument(
        "--debug_file", type=str, default="results/simulate_agentharm.jsonl"
    )
    parser.add_argument("--seed", type=int, default=44)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--need_simulate", action="store_true")
    parser.add_argument(
        "--debug_doubt_tool_path",
        type=str,
        default="debug_doubt_tool_agentharmbenign.log",
        help="Path to save debug tools if in debug mode",
    )
    parser.add_argument(
        "--debug_decision_path",
        type=str,
        default="debugs/debug_decision_agentharmbenign.log",
        help="tool pass but decision refused debug path",
    )
    parser.add_argument(
        "--rjudge_merge_splits",
        action="store_true",
        help="Merge rjudge_<Category>_benign and rjudge_<Category>_harmful into a single run (one final statistics).",
    )
    parser.add_argument(
        "--rjudge_category",
        type=str,
        default=None,
        help="R-Judge category name (e.g., Application/Finance/IoT/Program/Web) used with --rjudge_merge_splits.",
    )
    parser.add_argument(
        "--agentharm_merge_splits",
        action="store_true",
        help="Merge agentharm_<Category>_benign and agentharm_<Category>_harmful into a single run (one final statistics).",
    )
    parser.add_argument(
        "--agentharm_category",
        type=str,
        default=None,
        help="AgentHarm category name (e.g., Copyright/Cybercrime/.../Sexual) used with --agentharm_merge_splits.",
    )
    parser.add_argument(
        "--refine_action",
        action="store_true",
        help="Enable refine action after final decision.",
    )

    args = parser.parse_args()
    logger.info(f"Pipeline Configuration: {args}")
    run(args)
