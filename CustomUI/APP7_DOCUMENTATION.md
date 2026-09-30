# app7.py Documentation

## Overview

`app7.py` is a Flask-based Sales Order Assistant backend that combines:

- Oracle EBS REST operations (get order, create order, add line)
- Oracle database dynamic SQL querying for reporting and tracking
- AI-assisted intent detection, SQL generation, and summaries (GitHub Models/Copilot token)
- Email delivery with Excel/CSV/JSON attachments
- Optional voice input/output (Vosk and pyttsx3)

The UI is served from `static/index7.html`.

## Main Components

- `app7.py`: Main Flask app and API routes
- `config_manager.py`: Centralized config read/write and defaults
- `system_prompts.py`: Centralized prompts for intent extraction and SQL generation
- `config.json`: Runtime configuration persisted by config manager

## Prerequisites

1. Python 3.9+
2. Oracle connectivity to your target DB/EBS environment
3. Optional Oracle Instant Client (if your environment requires thick mode)
4. SMTP access (if email features are needed)
5. AI token for GitHub Models/Copilot features

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run

```bash
python app7.py
```

Startup uses these config keys:

- `app_host` (default `0.0.0.0`)
- `app_port` (default `5000`)
- `app_debug` (default `false`)
- `app_use_reloader` (default `false`)

Default URL:

- `http://localhost:5000/`

## Configuration

Configuration is loaded via `config_manager.load_config()` and updated through:

- `POST /api/config` (UI/API)
- direct updates to `config.json`

Important groups of keys:

- Database: `db_host`, `db_port`, `db_service`, `db_user`, `db_password`
- Oracle client: `oracle_client_path`
- AI/LLM: `github_copilot_token`, `github_models_base_url`, `copilot_model`
- EBS/Org defaults: `org_id`, `order_type_id`, `default_*`
- Login: `login_username`, `login_password`
- Email/SMTP: `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_use_tls`, `smtp_use_ssl`
- Auto-email/scheduler: `auto_email_enabled`, `auto_email_to`, `scheduler_default_*`
- Voice: `vosk_model_path`, `voice_duration`

## Runtime Flow

`/api/chat` is the main orchestration route.

1. Validates input and handles greetings/help.
2. Extracts intent using AI (`ai_extract_intent`) or rule-based fallback.
3. Branches into deterministic actions (`create`, `add_line`, `email`, `get`, `get_range`) when possible.
4. Uses tracking SQL path for multi-filter order tracking (`_build_order_tracking_query`).
5. Detects combined operations (`detect_combined_operations`) and builds optimized SQL (`generate_combined_sql`).
6. Falls back to AI-generated dynamic SQL (`generate_dynamic_sql`) when needed.
7. Enforces SQL safety (`is_safe_select_query` allows SELECT-only).
8. Stores last result in `_last_operation` for email/download APIs.

## API Endpoints

### Core UI/Auth/Config

- `GET /` -> serves `static/index7.html`
- `POST /api/login` -> validates credentials from config
- `GET /api/config` -> returns full config
- `POST /api/config` -> updates config keys

### Chat

- `POST /api/chat`
  - Main natural-language endpoint
  - Returns typed payloads such as `text`, `order`, `orders_advanced`, `dynamic_table`, `create_form`, `email_form`, and error responses
  - Includes `ui_state` timing metadata in responses

### Lookup APIs (create/order assistant)

- `GET /api/lookup-items`
- `GET /api/lookup-customers`
- `GET /api/lookup-customer-sites`
- `GET /api/lookup-prices`
- `GET /api/lookup-payment-terms`
- `GET /api/lookup-salesreps`

### Operations

- `POST /api/create-order`
- `GET /api/orders-advanced`
- `POST /api/add-line`

### Email/Automation

- `POST /api/send-email`
- `GET /api/email-preview`
- `POST /api/auto-email`
- `GET /api/auto-email`
- `POST /api/scheduler/start`
- `POST /api/scheduler/stop`
- `GET /api/scheduler/status`
- `POST /api/auto-loop/start`
- `POST /api/auto-loop/stop`
- `GET /api/auto-loop/status`

### Voice

- `POST /api/voice` (speech-to-text via Vosk)
- `POST /api/speak` (text-to-speech via pyttsx3)

### Downloads

- `GET /api/download-excel`
- `GET /api/download?format=excel|csv|json`

Downloads depend on `_last_operation` data from the most recent successful operation.

## AI and Dynamic SQL Notes

- AI token is read from config/env via `get_copilot_token()`.
- If token is missing, app falls back to deterministic behavior where possible.
- Dynamic SQL generation is constrained by:
  - schema context (`get_order_schema_context`)
  - operator-preservation instructions
  - safety checks (SELECT-only)
- Combined operations support includes scenarios like:
  - orders + customers
  - orders + inventory
  - customers + orders
  - orders + setup data
  - status/date combinations

## Output and Email Behavior

- `_last_operation` tracks the latest result payload, raw data, generated email HTML, and AI summary.
- `send_erp_email()` attaches data as `xlsx`, `csv`, or `json`.
- Auto-email can trigger after successful operations when enabled.

## Optional Features and Fallbacks

- `openpyxl` missing: Excel download/email attachment fails with a clear message.
- `oracledb` missing: DB operations fail; install `oracledb`.
- `vosk/sounddevice` missing: `/api/voice` returns guidance to use browser mic.
- `pyttsx3` missing: `/api/speak` returns package-not-installed error.

## Troubleshooting

### App fails at startup

- Verify Python env and dependencies:

```bash
pip install -r requirements.txt
```

- Check that `config.json` has valid JSON.

### Oracle connection errors

- Validate `db_*` values.
- Check DB reachability and credentials.
- If needed, set `oracle_client_path` to Instant Client folder.

### AI responses not working

- Set `github_copilot_token` in `config.json`.
- Optionally set `github_models_base_url` and `copilot_model`.

### Email sending fails

- Validate SMTP host/port/user/password.
- Confirm TLS/SSL settings match your mail server.
- Check recipient address and network/firewall access.

### Download endpoint says no data

- Run a successful operation first (chat query, order fetch, create order, etc.).

## Quick Test Checklist

1. `GET /` returns `index7.html`.
2. `POST /api/login` succeeds with configured credentials.
3. `POST /api/chat` with "Get order 67965" returns order/dynamic response.
4. `POST /api/chat` with a tracking-style prompt returns `dynamic_table`.
5. `GET /api/download?format=csv` returns attachment after successful query.
6. `POST /api/send-email` succeeds after a successful data operation.

## Related Documents

- `QUICKSTART.md`
- `IMPLEMENTATION_DETAILS.md`
- `COMBINED_OPERATIONS_GUIDE.md`
- `REFACTORING_NOTES.md`