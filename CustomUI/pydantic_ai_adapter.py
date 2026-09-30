"""Pydantic-backed AI helpers with optional PydanticAI agent execution.

This module keeps app7.py clean by centralizing:
- typed response models
- optional PydanticAI agent calls
- robust fallback to regular chat-completions + Pydantic validation
"""

import json
from typing import Any, Callable, Dict, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

try:
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIModel

    PYDANTIC_AI_RUNTIME_AVAILABLE = True
except Exception:
    Agent = None
    OpenAIModel = None
    PYDANTIC_AI_RUNTIME_AVAILABLE = False


class IntentResult(BaseModel):
    action: Literal[
        "dynamic_query",
        "create",
        "get",
        "get_range",
        "add_line",
        "email",
        "help",
        "general",
    ] = "dynamic_query"
    date_range: Optional[str] = None
    year: Optional[int] = None
    status: Optional[str] = None
    order_number: Optional[int] = None
    customer_name: Optional[str] = None
    email_address: Optional[str] = None
    cust_po_number: Optional[str] = None
    ordered_item: Optional[str] = None
    ordered_quantity: Optional[float] = None
    general_answer: Optional[str] = None


class SqlResult(BaseModel):
    sql: str = ""
    explanation: str = ""


class SummaryResult(BaseModel):
    summary: str = Field(default="", max_length=3000)


def _clean_json_text(text: str) -> str:
    return str(text or "").replace("```json", "").replace("```", "").strip()


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    cleaned = _clean_json_text(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def _run_pydantic_ai_agent(
    result_type: Any,
    system_prompt: str,
    user_prompt: str,
    model_name: str,
    base_url: str,
    token: str,
) -> Optional[Any]:
    if not PYDANTIC_AI_RUNTIME_AVAILABLE:
        return None

    try:
        model = OpenAIModel(
            model_name=model_name,
            base_url=base_url,
            api_key=token,
        )
        agent = Agent(
            model=model,
            result_type=result_type,
            system_prompt=system_prompt,
        )
        result = agent.run_sync(user_prompt)
        if hasattr(result, "data"):
            return result.data
        return result
    except Exception:
        return None


def _run_chat_completion_json(
    chat_completion: Callable[..., Dict[str, Any]],
    result_type: Any,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: Optional[int],
) -> Any:
    response = chat_completion(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    content = response["choices"][0]["message"]["content"].strip()
    payload = _extract_json_from_text(content)
    return result_type.model_validate(payload)


def extract_intent(
    history_str: str,
    user_input: str,
    system_prompt: str,
    chat_completion: Callable[..., Dict[str, Any]],
    model_name: str,
    base_url: str,
    token: str,
    user_prompt_builder: Callable[[str, str], str],
) -> Dict[str, Any]:
    user_prompt = user_prompt_builder(history_str, user_input)

    result = _run_pydantic_ai_agent(
        IntentResult,
        system_prompt,
        user_prompt,
        model_name,
        base_url,
        token,
    )
    if isinstance(result, IntentResult):
        return result.model_dump(exclude_none=True)

    fallback_result = _run_chat_completion_json(
        chat_completion,
        IntentResult,
        system_prompt,
        user_prompt,
        temperature=0,
        max_tokens=None,
    )
    return fallback_result.model_dump(exclude_none=True)


def generate_dynamic_sql(
    history_str: str,
    user_input: str,
    system_prompt: str,
    schema_context: str,
    chat_completion: Callable[..., Dict[str, Any]],
    model_name: str,
    base_url: str,
    token: str,
    user_prompt_builder: Callable[[str, str], str],
) -> Dict[str, str]:
    full_system_prompt = f"{system_prompt}\n\n{schema_context}".strip()
    user_prompt = user_prompt_builder(history_str, user_input)

    result = _run_pydantic_ai_agent(
        SqlResult,
        full_system_prompt,
        user_prompt,
        model_name,
        base_url,
        token,
    )
    if isinstance(result, SqlResult):
        return result.model_dump()

    fallback_result = _run_chat_completion_json(
        chat_completion,
        SqlResult,
        full_system_prompt,
        user_prompt,
        temperature=0,
        max_tokens=None,
    )
    return fallback_result.model_dump()


def generate_summary(
    operation_type: str,
    data_json: str,
    system_prompt: str,
    chat_completion: Callable[..., Dict[str, Any]],
    model_name: str,
    base_url: str,
    token: str,
    user_prompt_builder: Callable[[str, str], str],
) -> str:
    user_prompt_raw = user_prompt_builder(operation_type, data_json)
    schema_hint = (
        "Return ONLY JSON in this schema: {\"summary\": \"3-5 sentence executive summary\"}."
    )
    full_system_prompt = f"{system_prompt}\n\n{schema_hint}".strip()

    result = _run_pydantic_ai_agent(
        SummaryResult,
        full_system_prompt,
        user_prompt_raw,
        model_name,
        base_url,
        token,
    )
    if isinstance(result, SummaryResult):
        return result.summary.strip()

    try:
        fallback_result = _run_chat_completion_json(
            chat_completion,
            SummaryResult,
            full_system_prompt,
            user_prompt_raw,
            temperature=0.3,
            max_tokens=300,
        )
        return fallback_result.summary.strip()
    except (ValidationError, json.JSONDecodeError, KeyError):
        response = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt_raw},
            ],
            temperature=0.3,
            max_tokens=300,
        )
        return response["choices"][0]["message"]["content"].strip()
