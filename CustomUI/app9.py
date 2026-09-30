from flask import Flask, request, jsonify
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, Dict, Any
import sys
import os

sys.path.append(os.path.dirname(__file__))

from app7 import (
    app, CreateOrderDraft, resolve_create_order_draft, 
    validate_create_order_data, execute_query, get_org_id,
    _fetch_quick_customer_suggestions
)

# Add this new endpoint after the existing routes

@app.route("/api/create-order/validate-item", methods=["POST"])
def api_validate_item():
    """Validate item and return LOV if multiple matches found"""
    body = request.get_json(force=True) or {}
    item_name = str(body.get("ordered_item", "")).strip()
    
    if not item_name:
        return jsonify({
            "ok": False,
            "error": "Item name is required",
            "suggestions": []
        })
    
    try:
        org_id = int(get_org_id())
        item_upper = item_name.upper()
        
        # First try exact match
        exact_sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
            FROM MTL_SYSTEM_ITEMS_B
            WHERE ORGANIZATION_ID = :org_id
            AND UPPER(SEGMENT1) = :item_name
            FETCH FIRST 1 ROWS ONLY
        """
        exact_rows = execute_query(exact_sql, {"org_id": org_id, "item_name": item_upper})
        
        if exact_rows:
            row = exact_rows[0]
            return jsonify({
                "ok": True,
                "exact_match": True,
                "item": {
                    "inventory_item_id": int(row["INVENTORY_ITEM_ID"]),
                    "segment1": row.get("SEGMENT1", ""),
                    "description": row.get("DESCRIPTION", "")
                },
                "suggestions": []
            })
        
        # If no exact match, search with LIKE
        like_sql = """
            SELECT INVENTORY_ITEM_ID, SEGMENT1, DESCRIPTION
            FROM MTL_SYSTEM_ITEMS_B
            WHERE ORGANIZATION_ID = :org_id
            AND UPPER(SEGMENT1) LIKE :item_like
            ORDER BY SEGMENT1
            FETCH FIRST 25 ROWS ONLY
        """
        like_rows = execute_query(
            like_sql,
            {"org_id": org_id, "item_like": f"%{item_upper}%"}
        )
        
        if like_rows:
            suggestions = [
                {
                    "inventory_item_id": int(r["INVENTORY_ITEM_ID"]),
                    "segment1": r.get("SEGMENT1", ""),
                    "description": r.get("DESCRIPTION", "")
                }
                for r in like_rows
            ]
            return jsonify({
                "ok": True,
                "exact_match": False,
                "item": None,
                "suggestions": suggestions,
                "message": f"Multiple items match '{item_name}'. Please select one from the list."
            })
        
        return jsonify({
            "ok": False,
            "exact_match": False,
            "item": None,
            "suggestions": [],
            "error": f"No items found matching '{item_name}'."
        })
        
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "suggestions": []
        })

@app.route("/api/create-order/validate-all", methods=["POST"])
def api_validate_all():
    """Validate all create order parameters and return suggestions"""
    body = request.get_json(force=True) or {}
    
    try:
        draft = CreateOrderDraft.model_validate(body)
        result = resolve_create_order_draft(draft, strict_mode=True)
        validation = validate_create_order_data(draft, result)
        
        # Enhance suggestions with additional lookup data if needed
        suggestions = validation.get("suggestions", {})
        
        # If no customer suggestions but we have a customer name, try to find more
        if not suggestions.get("customers") and draft.customer_name:
            try:
                customers = _fetch_quick_customer_suggestions(draft.customer_name)
                if customers:
                    suggestions["customers"] = customers
            except Exception:
                pass
        
        # If no price suggestions but we have an item, try to find prices
        if not suggestions.get("prices") and draft.inventory_item_id:
            try:
                item_id = draft.inventory_item_id
                price_sql = """
                    SELECT DISTINCT qlh.LIST_HEADER_ID AS price_list_id,
                                    qlt.NAME AS price_list_name,
                                    qll.OPERAND AS unit_list_price
                    FROM QP_LIST_HEADERS_B qlh, QP_LIST_HEADERS_TL qlt, 
                         QP_LIST_LINES qll, QP_PRICING_ATTRIBUTES qpa
                    WHERE qlt.LIST_HEADER_ID = qlh.LIST_HEADER_ID 
                    AND qlt.LANGUAGE = USERENV('LANG')
                    AND qll.LIST_HEADER_ID = qlh.LIST_HEADER_ID
                    AND qpa.LIST_LINE_ID = qll.LIST_LINE_ID 
                    AND qpa.PRODUCT_ATTRIBUTE = 'PRICING_ATTRIBUTE1'
                    AND qpa.PRODUCT_ATTR_VALUE = :item_id_str
                    AND qlh.ACTIVE_FLAG = 'Y' 
                    AND qlh.LIST_TYPE_CODE = 'PRL' 
                    AND qlh.CURRENCY_CODE = 'USD'
                    ORDER BY qlh.START_DATE_ACTIVE DESC NULLS LAST
                    FETCH FIRST 10 ROWS ONLY
                """
                price_rows = execute_query(price_sql, {"item_id_str": str(item_id)})
                if price_rows:
                    suggestions["prices"] = [
                        {
                            "price_list_id": int(r["PRICE_LIST_ID"]),
                            "price_list_name": r.get("PRICE_LIST_NAME", ""),
                            "unit_list_price": float(r.get("UNIT_LIST_PRICE", 0))
                        }
                        for r in price_rows
                    ]
            except Exception:
                pass
        
        # If no term suggestions, get default terms
        if not suggestions.get("terms"):
            try:
                terms = execute_query("""
                    SELECT TERM_ID, NAME
                    FROM RA_TERMS_VL
                    WHERE (START_DATE_ACTIVE IS NULL OR START_DATE_ACTIVE <= SYSDATE)
                    AND (END_DATE_ACTIVE IS NULL OR END_DATE_ACTIVE >= SYSDATE)
                    ORDER BY TERM_ID
                    FETCH FIRST 10 ROWS ONLY
                """)
                if terms:
                    suggestions["terms"] = [
                        {"term_id": int(t["TERM_ID"]), "term_name": t.get("NAME", "")}
                        for t in terms
                    ]
            except Exception:
                pass
        
        # If no rep suggestions, get default reps
        if not suggestions.get("reps"):
            try:
                reps = execute_query("""
                    SELECT SALESREP_ID, NAME AS SALESREP_NAME
                    FROM JTF_RS_SALESREPS
                    WHERE ORG_ID = :org_id AND STATUS = 'A' AND END_DATE_ACTIVE IS NULL
                    ORDER BY SALESREP_ID
                    FETCH FIRST 10 ROWS ONLY
                """, {"org_id": int(get_org_id())})
                if reps:
                    suggestions["reps"] = [
                        {"salesrep_id": int(r["SALESREP_ID"]), "salesrep_name": r.get("SALESREP_NAME", "")}
                        for r in reps
                    ]
            except Exception:
                pass
        
        return jsonify({
            "ok": True,
            "resolved": result.get("resolved", {}),
            "missing": result.get("missing", []),
            "suggestions": suggestions,
            "errors": validation.get("errors", []),
            "warnings": result.get("warnings", [])
        })
        
    except ValidationError as ve:
        return jsonify({
            "ok": False,
            "error": str(ve),
            "suggestions": {}
        })
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "suggestions": {}
        })


if __name__ == "__main__":
    app.run(debug=True, port=5000)