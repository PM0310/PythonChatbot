# Quick Start Guide - Refactored Sales Order Assistant

## Overview
Your Sales Order Assistant has been refactored for better maintainability and flexibility. The core functionality remains the same, but the code is now organized into separate modules for configuration and prompts.

## New Structure

### 1. **config_manager.py** - Configuration Management
Handles all application configuration from `config.json`.

**Quick Usage:**
```python
import config_manager

# Get a config value
host = config_manager.get_config_value("db_host")

# Set a config value
config_manager.set_config_value("db_host", "new_host")

# Get a config group
email_config = config_manager.get_config_group("email")
```

### 2. **system_prompts.py** - AI Prompts
Contains all system prompts for LLM/AI models.

**Quick Usage:**
```python
from system_prompts import INTENT_EXTRACTION_SYSTEM_PROMPT
from system_prompts import DYNAMIC_SQL_GENERATION_SYSTEM_PROMPT
from system_prompts import build_intent_user_prompt
```

### 3. **app7.py** - Flask Application
Main application with API routes. Now uses the two modules above.

**No changes needed to usage** - all features work as before.

### 4. **index7.html** - Web UI
Same web interface as before. No functional changes.

## Running the Application

```bash
# From the CustomUI directory
python app7.py
```

The app will start on `http://localhost:5000` (or the configured host/port).

## Configuration

### Via Settings Panel
1. Click the **⚙️ Settings** button in the web interface
2. Edit configuration values
3. Click **Save Configuration**

### Via config.json
Edit the `config.json` file directly (will be auto-created on first run).

### Important Config Groups

**Database:**
- db_host, db_port, db_service, db_user, db_password

**AI/LLM:**
- github_copilot_token, copilot_model, openai_api_key

**Email:**
- smtp_host, smtp_port, smtp_user, smtp_password

**Oracle Apps:**
- org_id, order_type_id, default_payment_term_id, etc.

## Using the Chat Interface

### Getting Orders
- "Get order 67965"
- "Show orders for ACME Corp"
- "Orders this month"
- "Show booked orders"

### Creating Orders
- "Create a new order for customer ABC"
- The system will show a form to fill in details

### Dynamic Queries
- "Show items with zero inventory"
- "Which customers ordered more than 10 items this month?"
- The system generates Oracle SQL queries automatically

### Email Reports
- "Send results to john@example.com"
- Excel files are automatically attached

## Oracle Apps Standard Tables

The dynamic SQL generation now uses Oracle Apps standard tables:

**Sales Orders:**
- OE_ORDER_HEADERS_ALL
- OE_ORDER_LINES_ALL

**Customers:**
- HZ_PARTIES
- HZ_CUST_ACCOUNTS

**Inventory:**
- MTL_SYSTEM_ITEMS_B
- MTL_ONHAND_QUANTITIES

See `REFACTORING_NOTES.md` for complete table reference.

## Customizing Prompts

To change how the AI behaves:

1. Open `system_prompts.py`
2. Edit the relevant prompt:
   - `INTENT_EXTRACTION_SYSTEM_PROMPT` - How the AI understands user requests
   - `DYNAMIC_SQL_GENERATION_SYSTEM_PROMPT` - How the AI generates SQL queries
   - `AI_SUMMARY_GENERATION_PROMPT` - How the AI summarizes results
3. Save the file
4. Restart the application (or it will pick up changes on next request)

**Example: Add a new action type**
```python
# In INTENT_EXTRACTION_SYSTEM_PROMPT
# Add this rule:
# 8) If user asks about inventory levels -> action=inventory_query
```

## Adding New Configuration Values

1. Edit `config_manager.py`
2. Add the key to `DEFAULT_CONFIG`
3. Optionally add to a `CONFIG_GROUPS` group
4. Use in code: `config_manager.get_config_value("my_key")`

## Troubleshooting

### Config not saving?
- Check file permissions on `config.json`
- Ensure the directory is writable

### Prompts not updating?
- Restart the Flask application
- Check the `system_prompts.py` file for syntax errors

### AI not generating correct SQL?
- Check the `DYNAMIC_SQL_GENERATION_SYSTEM_PROMPT` for clarity
- Update the table schemas if using different tables
- Provide more specific user requests

### Database connection errors?
- Verify config_manager settings (db_host, db_port, db_service)
- Check network connectivity to the Oracle database
- Ensure Oracle client is installed

## Common Tasks

### Disable Email Sending
```python
# In config.json or Settings panel
"auto_email_enabled": false
```

### Change AI Model
```python
# In config.json or Settings panel
"copilot_model": "gpt-4"  # or any other model
```

### Use Different Oracle Instance
```python
# In config.json or Settings panel
"db_host": "your_host"
"db_port": "1521"
"db_service": "your_service"
```

### Enable Voice Recognition
1. Install required packages: `pip install vosk sounddevice pyttsx3`
2. Set vosk_model_path in config.json
3. Use voice input in the chat interface

## Support

For issues or questions:
1. Check `REFACTORING_NOTES.md` for detailed documentation
2. Review the source code comments in the modules
3. Check the `/memories/repo/app7_refactoring_summary.md` for change details

## Next Steps

1. **Test** - Try out the chat interface with various commands
2. **Customize** - Update prompts and config as needed
3. **Deploy** - Use the configured instance for your needs
4. **Monitor** - Check logs and adjust prompts based on results
