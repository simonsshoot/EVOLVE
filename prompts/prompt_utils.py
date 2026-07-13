from prompts.agentharm_prompts import (
    AGENTHARM_GENERAL_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_GENERAL_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_CYBERCRIME_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_CYBERCRIME_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_FRAUD_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_FRAUD_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_DISINFORMATION_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_DISINFORMATION_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_COPYRIGHT_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_COPYRIGHT_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_HATE_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_HATE_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_DRUGS_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_DRUGS_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_HARASSMENT_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_HARASSMENT_DOUBT_DECISION_SUPPLEMENT,
    AGENTHARM_SEXUAL_RISK_ANALYSIS_SUPPLEMENT,
    AGENTHARM_SEXUAL_DOUBT_DECISION_SUPPLEMENT,
)
from prompts.assebench_prompts import (
    ASSEBENCH_DATA_MANAGEMENT_RISK_ANALYSIS,
    ASSEBENCH_DATA_MANAGEMENT_DOUBT_DECISION,
    ASSEBENCH_EVALUATION_DIAGNOSIS_RISK_ANALYSIS,
    ASSEBENCH_EVALUATION_DIAGNOSIS_DOUBT_DECISION,
    ASSEBENCH_CONTENT_CREATION_RISK_ANALYSIS,
    ASSEBENCH_CONTENT_CREATION_DOUBT_DECISION,
    ASSEBENCH_AUTONOMOUS_NAVIGATION_RISK_ANALYSIS,
    ASSEBENCH_AUTONOMOUS_NAVIGATION_DOUBT_DECISION,
    ASSEBENCH_FINANCIAL_OPERATIONS_RISK_ANALYSIS,
    ASSEBENCH_FINANCIAL_OPERATIONS_DOUBT_DECISION,
    ASSEBENCH_HEALTH_WELLNESS_RISK_ANALYSIS,
    ASSEBENCH_HEALTH_WELLNESS_DOUBT_DECISION,
    ASSEBENCH_INFORMATION_RETRIEVAL_RISK_ANALYSIS,
    ASSEBENCH_INFORMATION_RETRIEVAL_DOUBT_DECISION,
    ASSEBENCH_IT_SYSTEM_RISK_ANALYSIS,
    ASSEBENCH_IT_SYSTEM_DOUBT_DECISION,
    ASSEBENCH_LEGAL_COMPLIANCE_RISK_ANALYSIS,
    ASSEBENCH_LEGAL_COMPLIANCE_DOUBT_DECISION,
    ASSEBENCH_PLANNING_SCHEDULING_RISK_ANALYSIS,
    ASSEBENCH_PLANNING_SCHEDULING_DOUBT_DECISION,
    ASSEBENCH_SECURITY_OPERATIONS_RISK_ANALYSIS,
    ASSEBENCH_SECURITY_OPERATIONS_DOUBT_DECISION,
    ASSEBENCH_TASK_AUTOMATION_RISK_ANALYSIS,
    ASSEBENCH_TASK_AUTOMATION_DOUBT_DECISION,
)
from prompts.rjudge_prompts import (
    RJUDGE_APPLICATION_RISK_ANALYSIS_SUPPLEMENT,
    RJUDGE_APPLICATION_DOUBT_DECISION_SUPPLEMENT,
    RJUDGE_APPLICATION_TOOL_PLAN_SUPPLEMENT,
    RJUDGE_PROGRAM_RISK_ANALYSIS_SUPPLEMENT,
    RJUDGE_PROGRAM_DOUBT_DECISION_SUPPLEMENT,
    RJUDGE_PROGRAM_TOOL_PLAN_SUPPLEMENT,
    RJUDGE_IOT_RISK_ANALYSIS_SUPPLEMENT,
    RJUDGE_IOT_DOUBT_DECISION_SUPPLEMENT,
    RJUDGE_IOT_TOOL_PLAN_SUPPLEMENT,
    RJUDGE_FINANCE_RISK_ANALYSIS_SUPPLEMENT,
    RJUDGE_FINANCE_DOUBT_DECISION_SUPPLEMENT,
    RJUDGE_FINANCE_TOOL_PLAN_SUPPLEMENT,
    RJUDGE_WEB_RISK_ANALYSIS_SUPPLEMENT,
    RJUDGE_WEB_DOUBT_DECISION_SUPPLEMENT,
    RJUDGE_WEB_TOOL_PLAN_SUPPLEMENT,
)


def get_specific_prompt_supplement(prompt_name: str, dataset: str) -> str:
    if dataset == "agentharm" or dataset.startswith("agentharm_"):
        if dataset == "agentharm":
            if prompt_name in ("RISK_ANALYSIS", "DOUBT_DECISION"):
                return (
                    AGENTHARM_GENERAL_RISK_ANALYSIS_SUPPLEMENT
                    if prompt_name == "RISK_ANALYSIS"
                    else AGENTHARM_GENERAL_DOUBT_DECISION_SUPPLEMENT
                )
            return ""

        category = dataset.replace("agentharm_", "")

        category_map_risk = {
            "Cybercrime": AGENTHARM_CYBERCRIME_RISK_ANALYSIS_SUPPLEMENT,
            "Fraud": AGENTHARM_FRAUD_RISK_ANALYSIS_SUPPLEMENT,
            "Disinformation": AGENTHARM_DISINFORMATION_RISK_ANALYSIS_SUPPLEMENT,
            "Copyright": AGENTHARM_COPYRIGHT_RISK_ANALYSIS_SUPPLEMENT,
            "Hate": AGENTHARM_HATE_RISK_ANALYSIS_SUPPLEMENT,
            "Drugs": AGENTHARM_DRUGS_RISK_ANALYSIS_SUPPLEMENT,
            "Harassment": AGENTHARM_HARASSMENT_RISK_ANALYSIS_SUPPLEMENT,
            "Sexual": AGENTHARM_SEXUAL_RISK_ANALYSIS_SUPPLEMENT,
        }

        category_map_decision = {
            "Cybercrime": AGENTHARM_CYBERCRIME_DOUBT_DECISION_SUPPLEMENT,
            "Fraud": AGENTHARM_FRAUD_DOUBT_DECISION_SUPPLEMENT,
            "Disinformation": AGENTHARM_DISINFORMATION_DOUBT_DECISION_SUPPLEMENT,
            "Copyright": AGENTHARM_COPYRIGHT_DOUBT_DECISION_SUPPLEMENT,
            "Hate": AGENTHARM_HATE_DOUBT_DECISION_SUPPLEMENT,
            "Drugs": AGENTHARM_DRUGS_DOUBT_DECISION_SUPPLEMENT,
            "Harassment": AGENTHARM_HARASSMENT_DOUBT_DECISION_SUPPLEMENT,
            "Sexual": AGENTHARM_SEXUAL_DOUBT_DECISION_SUPPLEMENT,
        }

        if prompt_name == "RISK_ANALYSIS":
            return category_map_risk.get(
                category, AGENTHARM_GENERAL_RISK_ANALYSIS_SUPPLEMENT
            )
        elif prompt_name == "DOUBT_DECISION":
            return category_map_decision.get(
                category, AGENTHARM_GENERAL_DOUBT_DECISION_SUPPLEMENT
            )
        else:
            return ""

    if dataset == "assebench" or dataset.startswith("assebench_"):
        if dataset == "assebench":
            return ""

        scenario = dataset.replace("assebench_", "")

        scenario_map_risk = {
            "Data_Management": ASSEBENCH_DATA_MANAGEMENT_RISK_ANALYSIS,
            "Evaluation_Diagnosis_Support": ASSEBENCH_EVALUATION_DIAGNOSIS_RISK_ANALYSIS,
            "ContentCreation_Processing_Communication": ASSEBENCH_CONTENT_CREATION_RISK_ANALYSIS,
            "Autonomous_Navigation_Robotics": ASSEBENCH_AUTONOMOUS_NAVIGATION_RISK_ANALYSIS,
            "Financial_Operations": ASSEBENCH_FINANCIAL_OPERATIONS_RISK_ANALYSIS,
            "Health_Wellness_Support": ASSEBENCH_HEALTH_WELLNESS_RISK_ANALYSIS,
            "Information_Retrieval_Analysis": ASSEBENCH_INFORMATION_RETRIEVAL_RISK_ANALYSIS,
            "IT_System_Network_Operations": ASSEBENCH_IT_SYSTEM_RISK_ANALYSIS,
            "Legal_Compliance_Audit": ASSEBENCH_LEGAL_COMPLIANCE_RISK_ANALYSIS,
            "Planning_Scheduling_Optimization": ASSEBENCH_PLANNING_SCHEDULING_RISK_ANALYSIS,
            "Security_Operations_System_Misuse": ASSEBENCH_SECURITY_OPERATIONS_RISK_ANALYSIS,
            "Task_Automation": ASSEBENCH_TASK_AUTOMATION_RISK_ANALYSIS,
        }

        scenario_map_decision = {
            "Data_Management": ASSEBENCH_DATA_MANAGEMENT_DOUBT_DECISION,
            "Evaluation_Diagnosis_Support": ASSEBENCH_EVALUATION_DIAGNOSIS_DOUBT_DECISION,
            "ContentCreation_Processing_Communication": ASSEBENCH_CONTENT_CREATION_DOUBT_DECISION,
            "Autonomous_Navigation_Robotics": ASSEBENCH_AUTONOMOUS_NAVIGATION_DOUBT_DECISION,
            "Financial_Operations": ASSEBENCH_FINANCIAL_OPERATIONS_DOUBT_DECISION,
            "Health_Wellness_Support": ASSEBENCH_HEALTH_WELLNESS_DOUBT_DECISION,
            "Information_Retrieval_Analysis": ASSEBENCH_INFORMATION_RETRIEVAL_DOUBT_DECISION,
            "IT_System_Network_Operations": ASSEBENCH_IT_SYSTEM_DOUBT_DECISION,
            "Legal_Compliance_Audit": ASSEBENCH_LEGAL_COMPLIANCE_DOUBT_DECISION,
            "Planning_Scheduling_Optimization": ASSEBENCH_PLANNING_SCHEDULING_DOUBT_DECISION,
            "Security_Operations_System_Misuse": ASSEBENCH_SECURITY_OPERATIONS_DOUBT_DECISION,
            "Task_Automation": ASSEBENCH_TASK_AUTOMATION_DOUBT_DECISION,
        }

        if prompt_name == "RISK_ANALYSIS":
            return scenario_map_risk.get(scenario, "")
        elif prompt_name == "DOUBT_DECISION":
            return scenario_map_decision.get(scenario, "")
        else:
            return ""

    if dataset.startswith("rjudge_"):
        subfolder = dataset.replace("rjudge_", "").split("_")[0]

        if subfolder == "Application":
            if prompt_name == "RISK_ANALYSIS":
                return RJUDGE_APPLICATION_RISK_ANALYSIS_SUPPLEMENT
            elif prompt_name == "DOUBT_DECISION":
                return RJUDGE_APPLICATION_DOUBT_DECISION_SUPPLEMENT
            elif prompt_name == "TOOL_PLAN":
                return RJUDGE_APPLICATION_TOOL_PLAN_SUPPLEMENT
            else:
                return ""

        elif subfolder == "Program":
            if prompt_name == "RISK_ANALYSIS":
                return RJUDGE_PROGRAM_RISK_ANALYSIS_SUPPLEMENT
            elif prompt_name == "DOUBT_DECISION":
                return RJUDGE_PROGRAM_DOUBT_DECISION_SUPPLEMENT
            elif prompt_name == "TOOL_PLAN":
                return RJUDGE_PROGRAM_TOOL_PLAN_SUPPLEMENT
            else:
                return ""

        elif subfolder == "IoT":
            if prompt_name == "RISK_ANALYSIS":
                return RJUDGE_IOT_RISK_ANALYSIS_SUPPLEMENT
            elif prompt_name == "DOUBT_DECISION":
                return RJUDGE_IOT_DOUBT_DECISION_SUPPLEMENT
            elif prompt_name == "TOOL_PLAN":
                return RJUDGE_IOT_TOOL_PLAN_SUPPLEMENT
            else:
                return ""

        elif subfolder == "Finance":
            if prompt_name == "RISK_ANALYSIS":
                return RJUDGE_FINANCE_RISK_ANALYSIS_SUPPLEMENT
            elif prompt_name == "DOUBT_DECISION":
                return RJUDGE_FINANCE_DOUBT_DECISION_SUPPLEMENT
            elif prompt_name == "TOOL_PLAN":
                return RJUDGE_FINANCE_TOOL_PLAN_SUPPLEMENT
            else:
                return ""

        elif subfolder == "Web":
            if prompt_name == "RISK_ANALYSIS":
                return RJUDGE_WEB_RISK_ANALYSIS_SUPPLEMENT
            elif prompt_name == "DOUBT_DECISION":
                return RJUDGE_WEB_DOUBT_DECISION_SUPPLEMENT
            elif prompt_name == "TOOL_PLAN":
                return RJUDGE_WEB_TOOL_PLAN_SUPPLEMENT
            else:
                return ""
        else:
            return ""

    return ""


def compose_prompt(base_prompt: str, supplement: str) -> str:
    if not supplement:
        return base_prompt

    if "Your return：" in base_prompt:
        parts = base_prompt.rsplit("Your return：", 1)
        return parts[0] + supplement + "\nYour return：" + parts[1]
    else:
        return base_prompt + "\n" + supplement
