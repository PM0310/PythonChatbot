from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import json

# Import your existing core logic
import SOS1 as bot

app = FastAPI()

# Allow frontend to communicate with backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory state to replace Streamlit's st.session_state
session_state = {
    "stage": "chat",
    "collected": {},
    "messages": [],
    "action": None,
    "pending_field": None,
    "email_payload_html": "",
    "auto_email_enabled": False,
    "auto_email_to": ""
}

def reset_session():
    session_state["stage"] = "chat"
    session_state["collected"] = {}
    session_state["action"] = None
    session_state["pending_field"] = None

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serves the custom HTML frontend."""
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.post("/api/chat")
async def handle_chat(request: Request):
    """Receives messages from the frontend and processes them."""
    data = await request.json()
    prompt = data.get("message", "").strip()
    
    if not prompt:
        return {"response": "Please enter a message.", "stage": session_state["stage"]}

    # Log user message
    session_state["messages"].append({"role": "user", "content": prompt})

    prompt_lower = prompt.lower()
    
    # -------------------------------------------------------------------
    # Simplified Routing Logic (Expand this to match your full Stream.py)
    # -------------------------------------------------------------------
    response_text = ""

    if prompt_lower in ["exit", "quit", "stop", "cancel"]:
        reset_session()
        response_text = "Operation cancelled. How can I help you next?"
    
    elif "create order" in prompt_lower or session_state["action"] == "create":
        session_state["action"] = "create"
        if not session_state["collected"].get("cpo"):
            response_text = "Got it. Let's create an order. What is the Customer PO Number?"
        elif not session_state["collected"].get("ordered_item"):
            session_state["collected"]["cpo"] = prompt
            response_text = "What is the Ordered Item code you would like?"
        else:
            response_text = "Processing order creation... (Backend integration required here)"
            reset_session()

    elif "get order" in prompt_lower or session_state["action"] == "get":
        session_state["action"] = "get"
        response_text = "Please provide the specific Order Number you want to retrieve."

    elif "send email" in prompt_lower:
        response_text = "Preparing email draft. Please provide the destination address."

    else:
        # Generic fallback
        response_text = "I am your Sales Order Assistant. You can ask me to 'Create an order', 'Get an order', or 'Search orders'."

    # Log assistant message
    session_state["messages"].append({"role": "assistant", "content": response_text})
    
    return {
        "response": response_text, 
        "stage": session_state["stage"]
    }

@app.post("/api/reset")
async def api_reset():
    reset_session()
    return {"response": "Chat cleared and session reset. How can I help?"}

if __name__ == "__main__":
    print("🚀 Starting Centroid Sales Order Assistant API...")
    uvicorn.run(app, host="127.0.0.1", port=8000)