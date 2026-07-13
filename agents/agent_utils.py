import json
import re
from typing import List, Dict, Any, Tuple


def normalize_is_safe(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ["true", "1", "yes", "True"]
    return False


def parse_json_with_retry(
    response_text: str,
    max_retries: int = 3,
    retry_prompt: str = None,
    model_call_func=None,
    extract_json_func=None,
    logger=None,
) -> Dict[str, Any]:
    for attempt in range(max_retries):
        try:
            if extract_json_func:
                cleaned_text = extract_json_func(response_text)
            else:
                text = re.sub(r"```json\s*", "", response_text)
                text = re.sub(r"```\s*$", "", text)
                text = text.strip()
                first_brace = text.find("{")
                last_brace = text.rfind("}")
                if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                    cleaned_text = text[first_brace : last_brace + 1]
                else:
                    cleaned_text = text

            result = json.loads(cleaned_text)
            return result

        except json.JSONDecodeError as e:
            if logger:
                logger.warning(
                    f"JSON parsing failed (Attempt {attempt + 1}/{max_retries}): {str(e)}"
                )

            if attempt < max_retries - 1 and model_call_func and retry_prompt:
                try:
                    retry_message = f"The previous response was incorrect. Please ensure that a complete and valid JSON format is returned.\nPrevious response: {response_text}...\n\nPlease regenerate the complete JSON response, returning only JSON."
                    response_text = model_call_func(retry_message)

                    continue

                except Exception as retry_error:
                    if logger:
                        logger.error(f"Model retry failed: {str(retry_error)}")

            if attempt == max_retries - 1:
                if logger:
                    logger.error(
                        f"JSON parsing failed after reaching max retries {max_retries}"
                    )
                raise
    raise json.JSONDecodeError(
        "Failed to parse JSON after all retries", response_text, 0
    )
