"""
app8.py - Agent mode wrapper for Sales Order Assistant.

This file reuses the existing app7 backend and adds a tool-using
agent endpoint for multi-step execution with trace visibility.
"""

import datetime
import re
import time
from typing import Any, Dict, List

from flask import jsonify, request, send_from_directory

import app7 as core

app = core.app


def _respond(payload: Dict[str, Any], started_at: float, stage: str = "completed"):
    data = dict(payload or {})
    data["ui_state"] = {
        "stage": stage,
        "elapsed_ms": int((time.time() - started_at) * 1000),
        "thinking": "Agent planned next steps.",
        "fetching": "Agent executed tools and prepared result.",
    }
    return jsonify(data)


def _trace_step(trace: List[Dict[str, Any]], step: str, detail: str):
    trace.append({
        "step": step,
        "detail": detail,
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
    })


def _safe_int(value, default=None):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


@app.route("/agent")
def agent_index():
    return send_from_directory("static", "index8.html")


@app.route("/api/agent-tools", methods=["GET"])
def api_agent_tools():
    return jsonify(
        {
            "mode": "agent",
            "tools": [
                "get_order",
                "get_customer_orders",
                "get_orders_advanced",
                "dynamic_sql_query",
                "general_chat",
                "create_order_form",
                "send_email_form",
            ],
            "guardrails": [
                "sql_select_only",
                "max_rows_ui_200",
                "create_requires_confirmation_form",
                "email_requires_confirmation_form",
            ],
        }
    )


@app.route("/api/agent-chat", methods=["POST"])
@app.route("/api/chat-agent", methods=["POST"])
def api_agent_chat():
    started_at = time.time()
    trace: List[Dict[str, Any]] = []

    try:
        body = request.get_json(force=True) or {}
        user_msg = str(body.get("message", "")).strip()
        history = body.get("history", [])

        if not user_msg:
            return _respond({"reply": "Please enter a message.", "type": "text", "agent_trace": trace}, started_at, "validation")

        lower = user_msg.lower().strip()
        if lower in ("hi", "hello", "hey"):
            return _respond(
                {
                    "reply": "Hello! Agent mode is active. I can plan and run tools for orders, tracking, SQL reports, and summaries.",
                    "type": "text",
                    "agent_trace": trace,
                    "agent_mode": True,
                },
                started_at,
            )

        if lower in ("help", "?", "commands"):
            return _respond(
                {
                    "reply": "Try: Get order 67965, Orders this month, Show booked orders for Vision, Track order 67965 with shipping details, Show highly ordered items.",
                    "type": "text",
                    "agent_trace": trace,
                    "agent_mode": True,
                },
                started_at,
            )

        _trace_step(trace, "analyze", "Extracting intent from user request")
        intent = core.ai_extract_intent(history, user_msg)

        force_create = bool(re.search(r"\b(create|new|place|book)\b", lower) and re.search(r"\border\b", lower))
        if force_create:
            intent["action"] = "create"

        action = intent.get("action", "dynamic_query")
        _trace_step(trace, "plan", f"Selected action: {action}")

        if action == "create":
            _trace_step(trace, "tool", "create_order_form")
            return _respond(
                {
                    "reply": "create_form",
                    "type": "create_form",
                    "prefilled": {
                        "cust_po_number": intent.get("cust_po_number"),
                        "ordered_item_input": intent.get("ordered_item"),
                        "ordered_quantity": intent.get("ordered_quantity"),
                        "customer_name": intent.get("customer_name"),
                    },
                    "agent_trace": trace,
                    "agent_mode": True,
                },
                started_at,
            )

        if action == "email":
            _trace_step(trace, "tool", "send_email_form")
            return _respond(
                {
                    "reply": {
                        "to_email": intent.get("email_address", ""),
                        "has_data": core._last_operation["type"] is not None,
                    },
                    "type": "email_form",
                    "agent_trace": trace,
                    "agent_mode": True,
                },
                started_at,
            )

        if action == "get":
            order_number = _safe_int(intent.get("order_number"))
            customer_name = str(intent.get("customer_name") or "").strip()

            if order_number:
                _trace_step(trace, "tool", f"get_order(order_number={order_number})")
                raw = core.get_order(order_number)
                parsed = core.parse_order_response(raw)
                core._last_operation["type"] = "order"
                core._last_operation["data"] = parsed
                core._last_operation["raw"] = raw
                core._last_operation["email_html"] = core._generate_order_email_html(parsed)
                summary = core.generate_ai_summary("order", parsed)
                core._last_operation["ai_summary"] = summary
                return _respond({"reply": parsed, "type": "order", "ai_summary": summary, "agent_trace": trace, "agent_mode": True}, started_at)

            if customer_name:
                _trace_step(trace, f"tool", f"get_customer_orders(customer_name={customer_name})")
                raw = core.get_customer_orders(customer_name)
                parsed = core.parse_customer_orders(raw)
                parsed["customer_name"] = customer_name
                core._last_operation["type"] = "customer_orders"
                core._last_operation["data"] = parsed
                core._last_operation["raw"] = raw
                core._last_operation["email_html"] = core._generate_customer_orders_email_html(parsed)
                summary = core.generate_ai_summary("customer_orders", parsed)
                core._last_operation["ai_summary"] = summary
                return _respond({"reply": parsed, "type": "customer_orders", "ai_summary": summary, "agent_trace": trace, "agent_mode": True}, started_at)

        if action == "get_range":
            range_type = intent.get("date_range")
            year = _safe_int(intent.get("year"))
            status = intent.get("status")
            _trace_step(trace, "tool", f"get_orders_advanced(range={range_type}, year={year}, status={status})")
            data = core.get_orders_advanced(range_type=range_type, year=year, status=status)
            core._last_operation["type"] = "orders_advanced"
            core._last_operation["data"] = data
            core._last_operation["raw"] = data
            core._last_operation["email_html"] = core._generate_orders_advanced_email_html(data, range_type, year, status)
            summary = core.generate_ai_summary("orders_advanced", data)
            core._last_operation["ai_summary"] = summary
            return _respond({"reply": data, "type": "orders_advanced", "ai_summary": summary, "agent_trace": trace, "agent_mode": True}, started_at)

        if action == "general" or (action == "dynamic_query" and not core.is_erp_or_data_query(user_msg)):
            _trace_step(trace, "tool", "general_chat")
            answer = intent.get("general_answer") or core.generate_general_chat_response(history, user_msg)
            return _respond({"reply": answer, "type": "text", "agent_trace": trace, "agent_mode": True}, started_at)

        _trace_step(trace, "tool", "dynamic_sql_query")
        ai_result = core.generate_dynamic_sql(history, user_msg)
        sql_query = re.sub(r"[;\s/]+$", "", str(ai_result.get("sql", "")).strip())
        explanation = ai_result.get("explanation", "Query executed successfully.")

        if not sql_query:
            return _respond({"reply": explanation, "type": "error", "agent_trace": trace, "agent_mode": True}, started_at, "failed")

        if not core.is_safe_select_query(sql_query):
            return _respond({"reply": "Security Error: Only safe SELECT queries are allowed.", "type": "error", "agent_trace": trace, "agent_mode": True}, started_at, "failed")

        results = core.execute_query(sql_query)
        if not results:
            return _respond({"reply": "No records found.", "type": "text", "agent_trace": trace, "agent_mode": True}, started_at)

        columns = list(results[0].keys())
        rows = [[str(row.get(col, "")) for col in columns] for row in results[:200]]

        core._last_operation["type"] = "dynamic_table"
        core._last_operation["data"] = {"columns": columns, "rows": rows, "sql": sql_query}
        core._last_operation["raw"] = results
        core._last_operation["email_html"] = core._generate_dynamic_table_email_html(columns, rows, explanation)

        return _respond(
            {
                "type": "dynamic_table",
                "sql": sql_query,
                "explanation": explanation,
                "columns": columns,
                "rows": rows,
                "agent_trace": trace,
                "agent_mode": True,
            },
            started_at,
        )

    except Exception as e:
        _trace_step(trace, "error", str(e))
        return _respond({"reply": f"Agent execution error: {e}", "type": "error", "agent_trace": trace, "agent_mode": True}, started_at, "failed")


if __name__ == "__main__":
    host = str(core.config_manager.get_config_value("app_host", "0.0.0.0"))
    port = int(core.config_manager.get_config_value("app_port", 5000))
    debug = bool(core.config_manager.get_config_value("app_debug", False))
    use_reloader = bool(core.config_manager.get_config_value("app_use_reloader", False))
    print(f"AI Agent app running on http://{host}:{port}/agent")
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
