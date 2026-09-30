import streamlit as st
import json
import SalesOrderbot as SalesOrderbot

st.title("SalesOrderbot Chat UI")

with st.form("order_form"):
    cpo             = st.text_input("Customer PO Number")
    item_id         = st.text_input("Inventory Item ID")
    qty             = st.text_input("Ordered Quantity")
    unit_price      = st.text_input("Unit List Price")
    selling_price   = st.text_input("Unit Selling Price")
    payment_term_id = st.text_input("Payment Term ID")
    price_list_id   = st.text_input("Price List ID")
    salesrep_id     = st.text_input("Salesrep ID")
    ship_to_org     = st.text_input("Ship-to Org ID")
    sold_to_org     = st.text_input("Sold-to Org ID")
    operating_unit  = st.text_input("Operating Unit", value="Vision Operations")
    submit          = st.form_submit_button("Send Order")

if submit:
    if not (cpo and item_id and qty):
        st.error("Customer PO Number, Inventory Item ID, and Ordered Quantity are required.")
    else:
        try:
            # --- Parse numeric fields ---
            item_id_int = int(item_id.strip())
            qty_int     = SalesOrderbot.parse_salary_value(qty)

            if qty_int is None:
                st.error("Invalid quantity value. Please enter a valid number.")
                st.stop()

            price_val = (
                0 if unit_price.strip() in ("", "0")
                else (SalesOrderbot.parse_salary_value(unit_price) or 0)
            )
            selling_price_val = (
                0 if selling_price.strip() in ("", "0")
                else (SalesOrderbot.parse_salary_value(selling_price) or 0)
            )

            payment_term_int = int(payment_term_id.strip()) if payment_term_id.strip() else 0
            price_list_int   = int(price_list_id.strip())   if price_list_id.strip()   else 0
            salesrep_int     = int(salesrep_id.strip())     if salesrep_id.strip()     else 0
            ship_to_org_int  = int(ship_to_org.strip())     if ship_to_org.strip()     else 0
            sold_to_org_int  = int(sold_to_org.strip())     if sold_to_org.strip()     else 0

            # --- Build payload using SalesOrderBot.create_payload ---
            payload = SalesOrderbot.create_payload(
                p_cust_po        = cpo,
                p_item_id        = item_id_int,
                p_qty            = qty_int,
                p_price          = price_val,
                p_selling_price  = selling_price_val,
                p_payment_term_id= payment_term_int,
                p_price_list_id  = price_list_int,
                p_salesrep_id    = salesrep_int,
                p_line_type_id   = 1427,
                p_ship_to_org    = ship_to_org_int,
                p_sold_to_org    = sold_to_org_int,
                p_operating_unit = operating_unit or "Vision Operations",
            )

            st.subheader("Payload Sent")
            st.json(payload)

            # --- Send order using SalesOrderBot.send_order ---
            result = SalesOrderbot.send_order(payload)

            # --- Extract and display result ---
            order_number, header_id = SalesOrderbot.extract_order_header(result)

            if order_number and header_id:
                st.success("✅ Order successfully created!")
                st.write(f"**ORDER_NUMBER:** {order_number}")
                st.write(f"**HEADER_ID:** {header_id}")
            else:
                st.warning("Order submitted, but ORDER_NUMBER/HEADER_ID not returned in response.")

            st.subheader("Full API Response")
            st.json(result)

        except ValueError as e:
            st.error(f"Invalid input in numeric field: {e}")
        except RuntimeError as e:
            st.error(f"Server error: {e}")
        except Exception as e:
            st.error(f"Unexpected error: {e}")