from __future__ import annotations

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Tuple
import argparse

from agents.agent_utils import normalize_is_safe
from configs import setup_logger

logger = setup_logger("pipeline")


BASE_DIR = Path(__file__).resolve().parent


def _data_path(*parts: str) -> str:
    return str(BASE_DIR.joinpath("data", *parts))


def read_simulated_data(data_type: str) -> List[Dict[str, Any]]:
    """
    读取预先模拟好的数据（JSONL格式）
    每一行是一个完整的JSON对象，包含 request, agent_actions, init 等字段

    对于 R-Judge 和 ASSEBench 数据集，直接读取原始数据（已包含用户请求和代理操作）
    """
    # R-Judge 和 ASSEBench 数据集不需要模拟数据，直接读取原始数据并包装
    if (
        data_type.startswith("rjudge_")
        or data_type == "assebench"
        or data_type.startswith("assebench_")
    ):
        return read_data(data_type)

    agentharm_categories = [
        "Copyright",
        "Cybercrime",
        "Disinformation",
        "Drugs",
        "Fraud",
        "Harassment",
        "Hate",
        "Sexual",
    ]

    for category in agentharm_categories:
        if data_type == f"agentharm_{category}_harmful":
            simulated_data_path = _data_path(
                "agentharm", category, "harmful_simulate.jsonl"
            )
            break
        elif data_type == f"agentharm_{category}_benign":
            simulated_data_path = _data_path(
                "agentharm", category, "benign_simulate.jsonl"
            )
            break
    else:
        # 如果不是类别数据，使用原有逻辑
        if data_type == "agentharm":
            simulated_data_path = _data_path("agentharm", "harmful_simulate.jsonl")
        elif data_type == "agentharm_benign":
            simulated_data_path = _data_path("agentharm", "benign_simulate.jsonl")
        elif data_type == "asb_benign":
            simulated_data_path = _data_path("ASB", "benign_simulate.jsonl")
        elif data_type == "asb_harmful":
            simulated_data_path = _data_path("ASB", "harmful_simulate.jsonl")
        elif data_type == "safeOS_harmful":
            simulated_data_path = _data_path("safeOS", "harmful_simulate.jsonl")
        elif data_type == "environment":
            simulated_data_path = "results/simulate_environment.jsonl"
        elif data_type == "safeOS_benign":
            simulated_data_path = _data_path("safeOS", "benign_simulate.jsonl")
        else:
            raise ValueError(f"Unknown data type: {data_type}")

    if not os.path.exists(simulated_data_path):
        raise FileNotFoundError(
            f"Simulated data file not found: {simulated_data_path}. "
            f"Please run with --need_simulate flag first to generate simulated data."
        )

    data = []
    with open(simulated_data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    item = json.loads(line)
                    if "request" in item and "agent_actions" in item:
                        data.append(item)
                except json.JSONDecodeError as e:
                    print(f"Warning: Failed to parse line: {line[:100]}... Error: {e}")
                    continue

    if not data:
        raise ValueError(f"No valid simulated data found in {simulated_data_path}")

    print(f"Loaded {len(data)} simulated data items from {simulated_data_path}")
    return data


def read_data(data_type: str):
    # 支持 AgentHarm 按类别读取
    # 格式: agentharm_<category>_harmful 或 agentharm_<category>_benign
    agentharm_categories = [
        "Copyright",
        "Cybercrime",
        "Disinformation",
        "Drugs",
        "Fraud",
        "Harassment",
        "Hate",
        "Sexual",
    ]

    for category in agentharm_categories:
        if data_type == f"agentharm_{category}_harmful":
            data_path = _data_path("agentharm", category, "harmful.json")
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "behaviors" in data:
                data = data["behaviors"]
            return data
        elif data_type == f"agentharm_{category}_benign":
            data_path = _data_path("agentharm", category, "benign.json")
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "behaviors" in data:
                data = data["behaviors"]
            return data

    # 支持 R-Judge 按子文件夹读取
    # 格式: rjudge_<subfolder>_harmful 或 rjudge_<subfolder>_benign
    rjudge_subfolders = ["Application", "Finance", "IoT", "Program", "Web"]

    for subfolder in rjudge_subfolders:
        if data_type == f"rjudge_{subfolder}_harmful":
            data_path = _data_path("R-Judge", subfolder, "harmful.json")
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # R-Judge 数据需要包装处理
            wrapped_data = []
            for item in data:
                wrapped_item = data_wrapper(item, data_type)
                wrapped_data.append(wrapped_item)
            return wrapped_data
        elif data_type == f"rjudge_{subfolder}_benign":
            data_path = _data_path("R-Judge", subfolder, "benign.json")
            with open(data_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # R-Judge 数据需要包装处理
            wrapped_data = []
            for item in data:
                wrapped_item = data_wrapper(item, data_type)
                wrapped_data.append(wrapped_item)
            return wrapped_data

    if data_type == "assebench":
        data_path = _data_path("ASSEBench", "dataset", "security50.json")
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # ASSEBench 数据需要包装处理
        wrapped_data = []
        for item in data:
            wrapped_item = data_wrapper(item, data_type)
            wrapped_data.append(wrapped_item)
        return wrapped_data

    # 支持 ASSEBench 按 split 文件读取
    if data_type.startswith("assebench_"):
        split_name = data_type.replace("assebench_", "")
        data_path = _data_path("ASSEBench", "split", f"{split_name}.json")
        if not os.path.exists(data_path):
            raise FileNotFoundError(f"ASSEBench split file not found: {data_path}")
        with open(data_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        wrapped_data = []
        for item in data:
            wrapped_item = data_wrapper(item, "assebench")
            wrapped_data.append(wrapped_item)
        return wrapped_data

    if data_type == "safeOS_harmful":
        data_path = _data_path("os.json")
    elif data_type == "environment":
        data_path = _data_path("environment.json")
    elif data_type == "benign":
        data_path = _data_path("benign.json")
    elif data_type == "asb_harmful":
        data_path = "agentsafebench/data/harmful.json"
    elif data_type == "asb_benign":
        data_path = "agentsafebench/data/benign.json"
    elif data_type == "agentharm":
        data_path = _data_path("agentharm", "harmful.json")
    elif data_type == "agentharm_benign":
        data_path = _data_path("agentharm", "benign.json")
    elif data_type == "rjudge_harmful":
        data_path = _data_path("R-Judge", "harmful.json")
    elif data_type == "rjudge_benign":
        data_path = _data_path("R-Judge", "benign.json")
    else:
        raise ValueError(f"Unknown data type: {data_type}")

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if data_type in ["agentharm", "agentharm_benign"]:
        if isinstance(data, dict) and "behaviors" in data:
            data = data["behaviors"]

    # R-Judge 数据集需要进行包装处理
    if data_type.startswith("rjudge_"):
        wrapped_data = []
        for item in data:
            wrapped_item = data_wrapper(item, data_type)
            wrapped_data.append(wrapped_item)
        return wrapped_data

    return data


def data_wrapper(data: Dict[str, Any], agent_type: str) -> Dict[str, Any]:
    def find_actions(item: Dict[str, Any]) -> str:
        actions = ""
        if "evaluation" in item:
            code_value = item["evaluation"]
            if "check" in code_value:
                actions = code_value["check"]["code"]
            elif "example" in code_value:
                actions = code_value["example"]["code"]
        return actions

    if agent_type == "safeOS_harmful":
        target_data = dict[str, Any]()
        if "create" in data:
            target_data["init"] = data["create"]["init"]["code"]
        else:
            target_data["init"] = ""
        target_data["request"] = data.get("description", "")
        target_data["user_identity"] = data.get("user", "user")
        user_identity = data.get("user", "user")
        target_data["user_level"] = data.get(
            "user_level", "root" if user_identity == "root" else "user"
        )
        target_data["labels"] = "safe" if data.get("labels", 1) == 0 else "unsafe"
        target_data["agent_actions"] = find_actions(data)

    elif agent_type == "environment" or agent_type == "safeOS_benign":
        target_data = dict[str, Any]()
        if "create" in data:
            target_data["init"] = data["create"]["init"]["code"]
        target_data["request"] = data.get("description", "")
        target_data["user_identity"] = data.get("user", "user")
        user_identity = data.get("user", "user")
        target_data["user_level"] = data.get(
            "user_level", "root" if user_identity == "root" else "user"
        )
        target_data["labels"] = "safe" if data.get("labels", 1) == 0 else "unsafe"

    elif agent_type == "asb_harmful" or agent_type == "asb_benign":
        target_data = {}
        target_data["request"] = data.get("instruction", "")
        target_data["user_identity"] = "user"
        target_data["user_level"] = "user"
        # fulfillable=0表示有害(应拦截), fulfillable=1表示可执行
        # DEFEND: labels=unsafe表示有害, labels=safe表示无害
        fulfillable = data.get("fulfillable", 0)
        target_data["labels"] = "unsafe" if fulfillable == 0 else "safe"

        target_data["agentsafebench_id"] = data.get("id", 0)
        target_data["agentsafebench_risks"] = data.get("risks", [])
        target_data["agentsafebench_failure_modes"] = data.get("failure_modes", "")
        target_data["environments"] = data.get("environments", [])

        # 初始化为空，将由SimulateAgent生成
        target_data["agent_actions"] = ""
        target_data["init"] = ""
    elif (
        agent_type == "agentharm"
        or agent_type == "agentharm_benign"
        or agent_type.startswith("agentharm_")
        and ("_harmful" in agent_type or "_benign" in agent_type)
    ):
        # AgentHarm数据格式（支持整体和按类别）
        target_data = {}
        target_data["request"] = data.get("prompt", "")
        target_data["user_identity"] = "root"
        target_data["user_level"] = "root"

        # AgentHarm中所有harmful behaviors都应该被拦截
        # benign behaviors应该被允许
        if agent_type == "agentharm" or "_harmful" in agent_type:
            target_data["labels"] = "unsafe"  # harmful behaviors
        else:
            target_data["labels"] = "safe"  # benign behaviors

        # 保留AgentHarm原始信息
        target_data["agentharm_id"] = data.get("id")
        target_data["agentharm_category"] = data.get("category", "")
        target_data["agentharm_name"] = data.get("name", "")
        target_data["agentharm_target_functions"] = data.get("target_functions", [])
        target_data["agentharm_detailed_prompt"] = data.get("detailed_prompt", False)
        target_data["agentharm_hint_included"] = data.get("hint_included", False)

        # 初始化为空，将由SimulateAgent生成
        target_data["agent_actions"] = ""
        target_data["init"] = ""

    elif agent_type.startswith("rjudge_"):
        target_data = {}
        contents = data.get("contents", [])
        if contents and len(contents) > 0:
            # 提取第一个用户请求作为主要请求
            user_content = ""
            agent_actions_list = []
            environment_responses = []
            for round_idx, round_turns in enumerate(contents):
                for turn in round_turns:
                    role = turn.get("role", "")
                    if role == "user":
                        if not user_content:
                            user_content = turn.get("content", "")
                    elif role == "agent":
                        action = turn.get("action", "")
                        thought = turn.get("thought", "")
                        if thought and action:
                            agent_actions_list.append(
                                f"Thought: {thought}\nAction: {action}"
                            )
                        elif thought:
                            agent_actions_list.append(f"Thought: {thought}")
                        elif action:
                            agent_actions_list.append(f"Action: {action}")
                    elif role == "environment":
                        env_content = turn.get("content", "")
                        if env_content:
                            environment_responses.append(
                                f"Environment Response: {env_content}"
                            )

            target_data["request"] = user_content

            if environment_responses:
                # 如果有environment响应，将它们插入到对应的action之后
                full_interaction = []
                env_idx = 0
                for i, action in enumerate(agent_actions_list):
                    full_interaction.append(action)
                    if env_idx < len(environment_responses):
                        full_interaction.append(environment_responses[env_idx])
                        env_idx += 1
                target_data["agent_actions"] = "\n---\n".join(full_interaction)
            else:
                target_data["agent_actions"] = "\n---\n".join(agent_actions_list)
        else:
            target_data["request"] = ""
            target_data["agent_actions"] = ""

        # R-Judge 数据集标签：1=unsafe, 0=safe
        label = data.get("label", 0)
        target_data["labels"] = "unsafe" if label == 1 else "safe"

        # 用户身份和权限
        target_data["user_identity"] = "root"
        target_data["user_level"] = "root"

        # 保留 R-Judge 原始信息
        target_data["rjudge_id"] = data.get("id")
        target_data["rjudge_scenario"] = data.get("scenario", "")
        target_data["rjudge_category"] = data.get("category", "")
        target_data["rjudge_profile"] = data.get("profile", "")
        target_data["rjudge_risk_description"] = data.get("risk_description", "")
        target_data["rjudge_attack_type"] = data.get("attack_type", "")

        target_data["init"] = ""

    elif agent_type == "assebench":
        # ASSEBench 数据集格式（类似R-Judge）
        target_data = {}
        contents = data.get("contents", [])
        if contents and len(contents) > 0:
            first_round = contents[0]

            user_content = ""
            agent_actions_list = []
            environment_responses = []

            for turn in first_round:
                role = turn.get("role", "")
                if role == "user":
                    if not user_content:
                        user_content = turn.get("content", "")
                elif role == "agent":
                    action = turn.get("action", "")
                    thought = turn.get("thought", "")

                    # 组合thought和action
                    if thought and action:
                        agent_actions_list.append(
                            f"Thought: {thought}\nAction: {action}"
                        )
                    elif thought:
                        agent_actions_list.append(f"Thought: {thought}")
                    elif action:
                        agent_actions_list.append(f"Action: {action}")
                elif role == "environment":
                    env_content = turn.get("content", "")
                    if env_content:
                        environment_responses.append(
                            f"Environment Response: {env_content}"
                        )

            target_data["request"] = user_content

            if environment_responses:
                # 如果有environment响应，将它们插入到对应的action之后
                full_interaction = []
                env_idx = 0
                for i, action in enumerate(agent_actions_list):
                    full_interaction.append(action)
                    # 通常每个action之后都有一个environment响应
                    if env_idx < len(environment_responses):
                        full_interaction.append(environment_responses[env_idx])
                        env_idx += 1
                target_data["agent_actions"] = "\n---\n".join(full_interaction)
            else:
                target_data["agent_actions"] = "\n---\n".join(agent_actions_list)
        else:
            target_data["request"] = ""
            target_data["agent_actions"] = ""

        # ASSEBench 数据集标签：1=unsafe (harmful), 0=safe (benign)
        label = data.get("label", 0)
        target_data["labels"] = "unsafe" if label == 1 else "safe"
        target_data["user_identity"] = "user"
        target_data["user_level"] = "user"

        # 保留 ASSEBench 原始信息
        target_data["assebench_id"] = data.get("id")
        target_data["assebench_profile"] = data.get("profile", "")
        target_data["assebench_application_scenario"] = data.get(
            "application_scenario", ""
        )
        target_data["assebench_risk_type"] = data.get("risk_type", "")
        target_data["assebench_failure_mode"] = data.get("failure_mode", "")
        target_data["assebench_ambiguous"] = data.get("ambiguous", 0)
        target_data["assebench_risk_description"] = data.get("risk_description", "")

        target_data["init"] = ""

    return target_data


def simulate_data_wrapper(data: Dict[str, Any], agent_type: str) -> Dict[str, Any]:
    """
    从已有的模拟数据中提取包装后的数据
    适用于 need_simulate=False 的情况
    """
    if agent_type in ["agentharm", "agentharm_benign"]:
        # 假设数据已经包含了 request, agent_actions, init 等字段
        # 如果是从 simulate_agentharm_benign.jsonl 加载的数据，直接返回
        if "request" in data and "agent_actions" in data:
            return data

        wrapped_data = {}
        wrapped_data["request"] = data.get("prompt", "")
        wrapped_data["user_identity"] = "user"
        wrapped_data["user_level"] = "user"

        if agent_type == "agentharm":
            wrapped_data["labels"] = "unsafe"
        else:
            wrapped_data["labels"] = "safe"

        # 保留AgentHarm原始信息
        wrapped_data["agentharm_id"] = data.get("id")
        wrapped_data["agentharm_category"] = data.get("category", "")
        wrapped_data["agentharm_name"] = data.get("name", "")
        wrapped_data["agentharm_target_functions"] = data.get("target_functions", [])
        wrapped_data["agentharm_detailed_prompt"] = data.get("detailed_prompt", False)
        wrapped_data["agentharm_hint_included"] = data.get("hint_included", False)

        # 从模拟数据中获取 agent_actions 和 init
        wrapped_data["agent_actions"] = data.get("agent_actions", "")
        wrapped_data["init"] = data.get("init", "")

        return wrapped_data

    elif agent_type == "agentsafebench":
        if "request" in data and "agent_actions" in data:
            return data

        wrapped_data = {}
        wrapped_data["request"] = data.get("instruction", "")
        wrapped_data["user_identity"] = "user"
        wrapped_data["user_level"] = "user"

        fulfillable = data.get("fulfillable", 0)
        wrapped_data["labels"] = "unsafe" if fulfillable == 0 else "safe"

        wrapped_data["agentsafebench_id"] = data.get("id", 0)
        wrapped_data["agentsafebench_risks"] = data.get("risks", [])
        wrapped_data["agentsafebench_failure_modes"] = data.get("failure_modes", "")
        wrapped_data["environments"] = data.get("environments", [])

        wrapped_data["agent_actions"] = data.get("agent_actions", "")
        wrapped_data["init"] = data.get("init", "")

        return wrapped_data

    else:
        # 对于其他数据集，如果有模拟数据就直接返回
        if "request" in data and "agent_actions" in data:
            return data

        # 否则返回空的 agent_actions 和 init
        wrapped_data = dict(data)
        wrapped_data["agent_actions"] = data.get("agent_actions", "")
        wrapped_data["init"] = data.get("init", "")
        return wrapped_data


def filter_by_id_prefix(input_file: str, output_file: str):
    """agentharm数据集中，根据id前缀过滤重复数据"""
    with open(input_file, "r") as f:
        data = json.load(f)
    seen = set()
    out_behaviors = []
    for b in data.get("behaviors", []):
        id_val = b.get("id", "")
        prefix = id_val.split("-", 1)[0] if "-" in id_val else id_val
        if prefix not in seen:
            seen.add(prefix)
            out_behaviors.append(b)
    result = dict(data)
    result["behaviors"] = out_behaviors
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2)
    print(
        f"Filtered dataset saved to {output_file} with {len(out_behaviors)} behaviors."
    )


def update_lifelong_library(
    args: argparse.Namespace,
    risk_analysis: Dict[str, Any],
    tool_set: List[Dict],
    doubt_tool_result: List[Tuple[Dict, Dict, bool, bool, int]],
    second_check_results: Dict[str, bool] | None = None,
):
    """
    更新 lifelong library
    1. 添加新识别的风险到 risks.json
    2. 添加新生成的工具或覆盖优化后的工具到 safety_tools.json

    额外约束：
    - 对于“最终仍然被判定为 risky 的工具”，不加入 tool_memory（lifelong library）。
      这里的“最终 risky”以 doubt_tool_result 中的 risky_tool/tool_has_risk 标志为准。
    """
    # ── Risk library update ────────────────────────────────────────────────
    try:
        with open(args.risk_memory, "r", encoding="utf-8") as f:
            risk_library = json.load(f)

        added_any = False
        for risk in risk_analysis.get("risks", []):
            category = risk.get("category")
            description = risk.get("description")

            if category and category.strip() and category not in risk_library:
                risk_library[category] = {
                    "category": category,
                    "description": description,
                }
                logger.info(f"Added new risk category: {category}")
                added_any = True

        if added_any:
            with open(args.risk_memory, "w", encoding="utf-8") as f:
                json.dump(risk_library, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to update risk library: {str(e)}")

    try:
        with open(args.tool_memory, "r", encoding="utf-8") as f:
            tool_library = json.load(f)

        updated = False

        for item in doubt_tool_result:
            tool_info, doubt_result, is_reused, execution_result, tool_has_risk = item[
                :5
            ]

            tool_name = tool_info.get("tool_name")
            if not tool_name:
                continue

            # 是否经历过“第一次判 risky -> 自动优化”流程
            is_optimized = isinstance(tool_has_risk, (int, float)) and tool_has_risk > 0

            if is_optimized:
                if not second_check_results or tool_name not in second_check_results:
                    continue
                if second_check_results.get(tool_name) is not True:
                    continue
            else:
                if normalize_is_safe(doubt_result.get("is_safe", "")) is not True:
                    continue

            category = tool_info.get("category")
            if not category:
                continue

            if category not in tool_library:
                tool_library[category] = []

            tool_data = {
                "tool_name": tool_name,
                "tool_description": tool_info.get("tool_description", ""),
                "require": tool_info.get("require", []),
                "tool_code": tool_info.get("tool_code", ""),
                "risk_description": tool_info.get("risk_description", ""),
            }

            if is_reused:
                found = False
                for i, existing_tool in enumerate(tool_library[category]):
                    if existing_tool.get("tool_name") == tool_name:
                        tool_library[category][i] = tool_data
                        found = True
                        updated = True
                        break
                if not found:
                    tool_library[category].append(tool_data)
                    updated = True
            else:
                exists = any(
                    t.get("tool_name") == tool_name for t in tool_library[category]
                )
                if not exists:
                    tool_library[category].append(tool_data)
                    updated = True

        if updated:
            with open(args.tool_memory, "w", encoding="utf-8") as f:
                json.dump(tool_library, f, indent=2, ensure_ascii=False)
            logger.info("Tool library updated successfully")

    except Exception as e:
        logger.error(f"Failed to update tool library: {str(e)}")


def get_present_tools(dataset: str, data: Dict[str, Any]) -> List[Dict]:
    """
    根据数据集名称，返回对应的现有工具列表(这里的工具是执行工具，不是安全工具)
    从AgentSafeBench的environments字段中提取工具描述
    从AgentHarm的target_functions字段中提取工具描述
    R-Judge数据集不需要提取present_tools（已包含在agent_actions中）
    """
    if dataset == "agentsafebench":
        # 导入AgentSafeBench的环境管理器
        import sys

        sys.path.append(os.path.join(os.path.dirname(__file__), "agentsafebench"))
        from environments.EnvManager import EnvManager

        env_manager = EnvManager()
        present_tools = []

        environments = data.get("environments", [])
        if not environments or not environments[0].get("name"):
            return []

        try:
            for env_info in environments:
                env_name = env_info.get("name", "")
                if not env_name:
                    continue

                env_params = env_info.get("parameters") or None
                env = env_manager.init_env(env_name, env_params)

                if env is None:
                    logger.warning(f"Environment {env_name} not found.")
                    continue

                tool_names = env_info.get("tools", [])
                # 获取工具描述（参考run.py的parse_envs函数）
                tool_descs = env.get_tool_descs(tool_names)
                for tool_desc in tool_descs:
                    present_tools.append(
                        {
                            "environment": env_name,
                            "tool_name": tool_desc.get("name", ""),
                            "description": tool_desc.get("description", ""),
                            "parameters": tool_desc.get("parameters", {}),
                            "env_instance": env,
                        }
                    )
        except Exception as e:
            logger.error(f"Error parsing present tools: {str(e)}")
            return []

        return present_tools

    elif (
        dataset == "agentharm"
        or dataset == "agentharm_benign"
        or (
            dataset.startswith("agentharm_")
            and ("_harmful" in dataset or "_benign" in dataset)
        )
    ):
        # AgentHarm数据集，从target_functions中提取工具（支持整体和按类别）
        import sys

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "agentharm"))

        try:
            # AgentHarm工具是通过@tool装饰器定义的函数
            # 动态导入目标工具
            if dataset == "agentharm" or "_harmful" in dataset:
                tools_package = "benchmark.harmful_tools"
            else:
                tools_package = "benchmark.benign_tools"

            target_functions = data.get("agentharm_target_functions", [])

            present_tools = []
            for func_name in target_functions:
                try:
                    # 导入对应的工具模块
                    module_path = f"{tools_package}.{func_name}"
                    tool_module = __import__(module_path, fromlist=[func_name])

                    # 获取工具函数
                    if hasattr(tool_module, func_name):
                        tool_func = getattr(tool_module, func_name)

                        # 调用tool函数获取Tool对象
                        tool_obj = tool_func()

                        # 提取工具描述和参数
                        import inspect

                        if hasattr(tool_obj, "__wrapped__"):
                            sig = inspect.signature(tool_obj.__wrapped__)
                            doc = inspect.getdoc(tool_obj.__wrapped__) or ""
                        else:
                            sig = inspect.signature(tool_obj)
                            doc = inspect.getdoc(tool_obj) or ""

                        # 构建参数信息
                        params = {}
                        for param_name, param in sig.parameters.items():
                            params[param_name] = {
                                "type": (
                                    str(param.annotation)
                                    if param.annotation != inspect.Parameter.empty
                                    else "any"
                                ),
                                "required": param.default == inspect.Parameter.empty,
                            }

                        present_tools.append(
                            {
                                "environment": "agentharm",
                                "tool_name": func_name,
                                "description": doc,
                                "parameters": {"properties": params},
                                "tool_function": tool_obj,
                            }
                        )
                        logger.info(f"Loaded AgentHarm tool: {func_name}")
                    else:
                        logger.warning(f"Tool function {func_name} not found in module")
                except Exception as e:
                    logger.error(f"Error loading tool {func_name}: {str(e)}")
                    import traceback

                    traceback.print_exc()
                    continue

            return present_tools
        except Exception as e:
            logger.error(f"Error loading AgentHarm tools: {str(e)}")
            import traceback

            traceback.print_exc()
            return []

    elif dataset.startswith("rjudge_"):
        # R-Judge 数据集不需要提取 present_tools
        # 因为 agent_actions 已经包含了所有执行的操作
        return []

    elif dataset == "assebench" or dataset.startswith("assebench_"):
        # ASSEBench 数据集不需要提取 present_tools
        # 因为 agent_actions 已经包含了所有执行的操作
        return []

    else:
        return []


def save_misjudged_case(
    args: argparse.Namespace,
    index: int,
    item: Dict[str, Any],
    tarvodata: Dict[str, Any],
    decision: str,
    label: int,
    risk_analysis: Dict[str, Any],
    tool_set: List[Dict],
    doubt_tool_result: List[Tuple[Dict, Dict, bool, bool, int]],
    action_result: str,
):
    expected_decision = "safe" if label == 1 else "unsafe"
    if decision == expected_decision or decision == "error":
        return
    if label == 1 and decision == "unsafe":
        misjudge_type = "benign_judged_harmful"
    elif label == 0 and decision == "safe":
        misjudge_type = "harmful_judged_benign"
    else:
        return

    # ---- AgentHarm: 按类别保存误判案例 ----
    # 对于 agentharm 数据集,从样本中提取类别信息并在文件夹路径中体现
    dataset_folder = args.dataset
    if str(args.dataset).startswith("agentharm"):
        category = (
            tarvodata.get("agentharm_category")
            or tarvodata.get("category")
            or item.get("agentharm_category")
            or item.get("category")
        )
        if isinstance(category, str) and category.strip():
            # 使用 agentharm_<Category> 作为文件夹名,与评估脚本保持一致
            dataset_folder = f"agentharm_{category.strip()}"

    detail_dir = os.path.join("detail_results", dataset_folder, misjudge_type)
    os.makedirs(detail_dir, exist_ok=True)

    category_info = (
        tarvodata.get("agentharm_category")
        or tarvodata.get("category")
        or item.get("agentharm_category")
        or item.get("category")
    )

    misjudge_record = {
        "index": index,
        "misjudge_type": misjudge_type,
        "dataset": args.dataset,
        "category": category_info,
        "original_data": item,
        "processed_data": {
            "request": tarvodata.get("request", ""),
            "agent_actions": tarvodata.get("agent_actions", ""),
            "user_identity": tarvodata.get("user_identity", ""),
            "user_level": tarvodata.get("user_level", ""),
            "init": tarvodata.get("init", ""),
        },
        "label": {
            "value": label,
        },
        "decision": {
            "value": decision,
        },
        "risk_analysis": risk_analysis,
        "generated_tools": [
            {
                "tool_name": tool.get("tool_name", ""),
                "category": tool.get("category", ""),
                "tool_description": tool.get("tool_description", ""),
            }
            for tool in tool_set
        ],
        "doubt_tool_details": [
            {
                "tool_name": result[0].get("tool_name", ""),
                "category": result[0].get("category", ""),
                "doubt_result": {
                    "is_safe": result[1].get("is_safe", ""),
                    "reason": result[1].get("reason", ""),
                },
                "is_reused": result[2],
                "execution_result": result[3],
                "had_risk": result[4] > 0,
            }
            for result in doubt_tool_result
        ],
        "action_result": action_result,
    }

    jsonl_filename = "misjudged_cases.jsonl"
    file_path = os.path.join(detail_dir, jsonl_filename)
    with open(file_path, "a", encoding="utf-8") as f:
        json_record = json.dumps(misjudge_record, ensure_ascii=False)
        f.write(json_record + "\n")

    logger.info(f"Saved misjudged case {index} to JSONL file: {file_path}")


def data_reader(args: argparse.Namespace):
    if getattr(args, "rjudge_merge_splits", False):
        if not args.rjudge_category:
            raise ValueError(
                "When --rjudge_merge_splits is enabled, --rjudge_category must be provided"
            )

        if args.dataset not in ["rjudge", "r-judge", "R-Judge"] and not str(
            args.dataset
        ).startswith("rjudge"):
            raise ValueError(
                "--rjudge_merge_splits is intended for R-Judge; please set --dataset rjudge"
            )

        merged_dataset_name = f"rjudge_{args.rjudge_category}_merged"
        logger.info(
            f"R-Judge merge enabled: loading benign+harmful for category={args.rjudge_category} -> dataset={merged_dataset_name}"
        )

        benign_name = f"rjudge_{args.rjudge_category}_benign"
        harmful_name = f"rjudge_{args.rjudge_category}_harmful"

        benign_data = (
            read_simulated_data(benign_name)
            if not args.need_simulate
            else read_data(benign_name)
        )
        harmful_data = (
            read_simulated_data(harmful_name)
            if not args.need_simulate
            else read_data(harmful_name)
        )

        data = benign_data + harmful_data
        args.dataset = merged_dataset_name

    elif getattr(args, "agentharm_merge_splits", False):
        if not args.agentharm_category:
            raise ValueError(
                "When --agentharm_merge_splits is enabled, --agentharm_category must be provided"
            )

        if args.dataset not in ["agentharm", "agentharm_benign"] and not str(
            args.dataset
        ).startswith("agentharm"):
            raise ValueError(
                "--agentharm_merge_splits is intended for AgentHarm; please set --dataset agentharm"
            )

        merged_dataset_name = f"agentharm_{args.agentharm_category}_merged"
        logger.info(
            f"AgentHarm merge enabled: loading benign+harmful for category={args.agentharm_category} -> dataset={merged_dataset_name}"
        )

        benign_name = f"agentharm_{args.agentharm_category}_benign"
        harmful_name = f"agentharm_{args.agentharm_category}_harmful"

        benign_data = (
            read_simulated_data(benign_name)
            if not args.need_simulate
            else read_data(benign_name)
        )
        harmful_data = (
            read_simulated_data(harmful_name)
            if not args.need_simulate
            else read_data(harmful_name)
        )

        data = benign_data + harmful_data
        # 覆盖 args.dataset，使结果目录、统计输出都归到 merged 名称
        args.dataset = merged_dataset_name

    else:
        if args.need_simulate:
            data = read_data(args.dataset)
        else:
            data = read_simulated_data(args.dataset)

    return data, args.dataset


def save_optim_tool_case(
    tarvodata: Dict[str, Any],
    tool_info: Dict[str, Any],
    doubt_result: Dict[str, Any],
    second_check_result: Dict[str, Any],
    execution_result: str,
    index: int,
    dataset: str,
    is_reused: bool,
    tool_results_dir: str,
):
    """保存成功优化的工具案例"""
    tool_case = {
        "index": index,
        "dataset": dataset,
        "tool_type": "reused_tool" if is_reused else "new_tool",
        "user_request": tarvodata.get("request", ""),
        "agent_actions": tarvodata.get("agent_actions", ""),
        "user_identity": tarvodata.get("user_identity", ""),
        "user_level": tarvodata.get("user_level", ""),
        "tool_name": tool_info.get("tool_name", ""),
        "category": tool_info.get("category", ""),
        "original_tool": {
            "tool_description": tool_info.get("original_tool_description", ""),
            "tool_code": tool_info.get("original_tool_code", ""),
            "first_check_result": tool_info.get("original_doubt_result", {}),
        },
        "optimized_tool": {
            "tool_description": tool_info.get("tool_description", ""),
            "tool_code": tool_info.get("tool_code", ""),
            "first_check_result": doubt_result,
            "second_check_result": second_check_result,
        },
        "execution_result": execution_result,
    }

    tool_case_file = os.path.join(
        tool_results_dir,
        "successfully_optimized_tools.jsonl",
    )
    with open(tool_case_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(tool_case, ensure_ascii=False) + "\n")
