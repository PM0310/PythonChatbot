import streamlit as st
import SalesOrderBot2 as SalesOrderbot
import json

st.set_page_config(page_title="SalesOrderbot Assistant", page_icon="📦")
st.title("📦 SalesOrderbot Assistant")

# --- 1. Initialize Session State ---
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hello! I can help you create a Sales Order. What is the **Customer PO Number**?"}]

if "order_data" not in st.session_state:
    st.session_state.fields_to_collect = [
        "cpo", "item_id", "ordered_item", "qty", "unit_price", 
        "selling_price", "payment_term_id", "price_list_id", 
        "salesrep_id", "line_type_id", "ship_to_org", 
        "sold_to_org", "operating_unit"
    ]
    st.session_state.order_data = {}
    st.session_state.current_field_index = 0
    st.session_state.order_complete = False

# --- 2. Display Chat History ---
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- 3. Chat Input Logic ---
if prompt := st.chat_input("Type your response here..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    if not st.session_state.order_complete:
        current_idx = st.session_state.current_field_index
        field_list = st.session_state.fields_to_collect
        
        current_field_name = field_list[current_idx]
        st.session_state.order_data[current_field_name] = prompt
        
        st.session_state.current_field_index += 1
        
        if st.session_state.current_field_index < len(field_list):
            next_field_raw = field_list[st.session_state.current_field_index]
            next_field_display = next_field_raw.replace("_", " ").title()
            assistant_res = f"Got it. Now, please provide the **{next_field_display}**."
            
            st.session_state.messages.append({"role": "assistant", "content": assistant_res})
            with st.chat_message("assistant"):
                st.markdown(assistant_res)
        else:
            st.session_state.order_complete = True
            with st.chat_message("assistant"):
                st.write("Sending request to ERP... ⏳")
                
                try:
                    d = st.session_state.order_data
                    
                    parsed_qty = SalesOrderbot.parse_numeric_value(d['qty'], allow_float=False)
                    parsed_price = SalesOrderbot.parse_numeric_value(d['unit_price'], allow_float=True)
                    parsed_selling = SalesOrderbot.parse_numeric_value(d['selling_price'], allow_float=True)

                    payload = SalesOrderbot.create_payload(
                        p_cust_po         = d['cpo'],
                        p_item_id         = int(d['item_id']),
                        p_ordered_item    = d['ordered_item'],
                        p_qty             = parsed_qty,
                        p_price           = parsed_price or 0,
                        p_selling_price   = parsed_selling or 0,
                        p_payment_term_id = int(d['payment_term_id']),
                        p_price_list_id   = int(d['price_list_id']),
                        p_salesrep_id     = int(d['salesrep_id']),
                        p_line_type_id    = int(d['line_type_id']),
                        p_ship_to_org     = int(d['ship_to_org']),
                        p_sold_to_org     = int(d['sold_to_org']),
                        p_operating_unit  = d['operating_unit']
                    )
                    
                    # Send to API
                    result = SalesOrderbot.send_order(payload)
                    
                    # --- MODIFIED SECTION ---
                    # We no longer look for order_number or header_id
                    status_msg = "✅ API Request processed. See the response below for details."
                    st.session_state.messages.append({"role": "assistant", "content": status_msg})
                    st.success(status_msg)
                    
                    # Show the full result immediately or in an expander
                    st.json(result)
                    # -------------------------
                    
                    if st.button("Start New Session"):
                        for key in st.session_state.keys():
                            del st.session_state[key]
                        st.rerun()
                        
                except Exception as e:
                    error_msg = f"❌ Error: {str(e)}"
                    st.error(error_msg)
                    st.session_state.messages.append({"role": "assistant", "content": error_msg})