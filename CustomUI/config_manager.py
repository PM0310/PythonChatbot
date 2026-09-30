"""
Configuration Management Module
Centralized configuration for Sales Order Assistant

Secret fields are stored encrypted in config.json using Fernet symmetric
encryption. The encryption key is kept in config.key (never committed to VCS).
Plain-text values are automatically migrated to encrypted form on first load.
"""

import json
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet

CONFIG_FILE = "config.json"
KEY_FILE = "config.key"

# Fields whose values are stored encrypted in config.json.
# The stored value will be prefixed with "enc:" to distinguish from plaintext.
ENCRYPTED_FIELDS = {
    "db_password",
    "api_password",
    "github_copilot_token",
    "openai_api_key",
    "smtp_password",
    "login_password",
}


def _load_or_create_key() -> bytes:
    """Load the Fernet key from config.key, creating it if it does not exist."""
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as fh:
            return fh.read().strip()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as fh:
        fh.write(key)
    return key


def _get_fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt_value(plaintext: str) -> str:
    """Return an 'enc:<base64>' string for storage in config.json."""
    token = _get_fernet().encrypt(plaintext.encode()).decode()
    return f"enc:{token}"


def decrypt_value(stored: str) -> str:
    """Decrypt an 'enc:<base64>' value back to plaintext."""
    if stored.startswith("enc:"):
        return _get_fernet().decrypt(stored[4:].encode()).decode()
    return stored  # already plaintext (legacy / non-secret field)


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("enc:")


# Default configuration with all available options
DEFAULT_CONFIG: Dict[str, Any] = {
    # ============ Database Configuration ============
    "db_host": "cendb.centroid.com",
    "db_port": "1541",
    "db_service": "EBS122",
    "db_user": "apps",
    "db_password": "apps",
    "oracle_client_path": r"C:\\Oracle\\instantclient_19_10",

    # ============ API Configuration ============
    "api_base_url": "https://cendb.ad.centroid.com:4463",
    "api_user": "operations",
    "api_password": "welcome",

    # ============ AI/LLM Configuration ============
    "github_models_base_url": "https://models.github.ai/inference",
    "github_copilot_token": "",
    "copilot_model": "openai/gpt-4o",
    "llm_backend": "legacy",
    "openai_api_key": "",
    "openai_model": "gpt-4o",

    # ============ Oracle Apps Configuration ============
    "org_id": "204",
    "order_type_id": 1437,
    "default_payment_term_id": 4,
    "default_price_list_id": 1000,
    "default_salesrep_id": 10067,
    "default_ship_to_org_id": 6472,
    "default_sold_to_org_id": 5391,
    "default_inventory_item_id": 12027,
    "operating_unit": "Vision Operations",
    "max_choices": 10,
    "responsibility": "ORDER_MGMT_SUPER_USER",
    "resp_application": "ONT",
    "security_group": "STANDARD",
    "nls_language": "AMERICAN",

    # ============ Email Configuration ============
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_sender": "erp.assistant@yourdomain.com",
    "auto_email_enabled": False,
    "auto_email_to": "",

    # ============ Voice Configuration ============
    "voice_duration": 5,
    "sample_rate": 16000,
    "vosk_model_path": "",

    # ============ Scheduler Configuration ============
    "scheduler_default_interval_mins": 60,
    "scheduler_default_customer_name": "",
    "scheduler_default_to_email": "",

    # ============ Flask App Configuration ============
    "app_host": "0.0.0.0",
    "app_port": 5000,
    "app_debug": False,
    "app_use_reloader": False,
}

# Grouping for UI organization
CONFIG_GROUPS = {
    "database": ["db_host", "db_port", "db_service", "db_user", "db_password", "oracle_client_path"],
    "api": ["api_base_url", "api_user", "api_password"],
    "ai_llm": ["github_models_base_url", "github_copilot_token", "copilot_model", "llm_backend", "openai_api_key", "openai_model"],
    "oracle_apps": ["org_id", "order_type_id", "default_payment_term_id", "default_price_list_id", 
                    "default_salesrep_id", "default_ship_to_org_id", "default_sold_to_org_id", 
                    "default_inventory_item_id", "operating_unit", "max_choices", "responsibility", 
                    "resp_application", "security_group", "nls_language"],
    "email": ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_sender", 
              "auto_email_enabled", "auto_email_to"],
    "voice": ["voice_duration", "sample_rate", "vosk_model_path"],
    "scheduler": ["scheduler_default_interval_mins", "scheduler_default_customer_name", "scheduler_default_to_email"],
    "app": ["app_host", "app_port", "app_debug", "app_use_reloader"],
}


class ConfigManager:
    """Centralized configuration manager with transparent field-level encryption."""

    _instance: Optional['ConfigManager'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self) -> None:
        """Load configuration from file, decrypt secret fields, and migrate any
        plaintext secrets to encrypted form."""
        cfg = dict(DEFAULT_CONFIG)

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    file_cfg = json.load(f)
                if isinstance(file_cfg, dict):
                    cfg.update(file_cfg)
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")

        # Migrate any plaintext secret fields to encrypted form and persist.
        migrated = False
        for field in ENCRYPTED_FIELDS:
            val = cfg.get(field)
            if val and isinstance(val, str) and not is_encrypted(val):
                cfg[field] = encrypt_value(val)
                migrated = True

        if migrated:
            try:
                with open(CONFIG_FILE, "w") as f:
                    json.dump(cfg, f, indent=4)
            except Exception as e:
                print(f"Warning: Could not save encrypted config: {e}")

        # Keep the raw (possibly encrypted) config for persistence, and build a
        # decrypted view for runtime use.
        self._raw_config = cfg
        self._config = self._decrypt_all(cfg)

    def _decrypt_all(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of cfg with all encrypted fields decrypted."""
        result = dict(cfg)
        for field in ENCRYPTED_FIELDS:
            val = result.get(field)
            if val and is_encrypted(val):
                try:
                    result[field] = decrypt_value(val)
                except Exception as e:
                    print(f"Warning: Could not decrypt '{field}': {e}")
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """Get a decrypted configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value, encrypting it if it is a secret field."""
        # Update the decrypted runtime view
        self._config[key] = value
        # Store encrypted form for secret fields
        if key in ENCRYPTED_FIELDS and value and isinstance(value, str):
            self._raw_config[key] = encrypt_value(value)
        else:
            self._raw_config[key] = value
        self._save_to_file()

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration (decrypted)."""
        return dict(self._config)

    def get_group(self, group_name: str) -> Dict[str, Any]:
        """Get configuration group by name."""
        if group_name not in CONFIG_GROUPS:
            raise ValueError(f"Unknown config group: {group_name}")
        keys = CONFIG_GROUPS[group_name]
        return {key: self._config.get(key) for key in keys}

    def _save_to_file(self) -> None:
        """Save raw (encrypted) configuration to file."""
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self._raw_config, f, indent=4)
        except Exception as e:
            print(f"Warning: Could not save config file: {e}")

    def reload(self) -> None:
        """Reload configuration from file."""
        self._instance = None  # force re-init
        self._load_config()


# Convenience functions for quick access
def load_config() -> Dict[str, Any]:
    """Load and return configuration dictionary."""
    manager = ConfigManager()
    return manager.get_all()


def get_config_value(key: str, default: Any = None) -> Any:
    """Get a configuration value."""
    manager = ConfigManager()
    return manager.get(key, default)


def set_config_value(key: str, value: Any) -> None:
    """Set a configuration value."""
    manager = ConfigManager()
    manager.set(key, value)


def get_config_group(group_name: str) -> Dict[str, Any]:
    """Get a configuration group."""
    manager = ConfigManager()
    return manager.get_group(group_name)


# Legacy compatibility functions (used by app7.py)
app_config = load_config()


def get_org_id() -> int:
    """Get organization ID."""
    return int(get_config_value("org_id", "204"))


def get_order_type_id() -> int:
    """Get order type ID."""
    return int(get_config_value("order_type_id", 1437))


def get_default_payment_term_id() -> int:
    """Get default payment term ID."""
    return int(get_config_value("default_payment_term_id", 4))


def get_default_price_list_id() -> int:
    """Get default price list ID."""
    return int(get_config_value("default_price_list_id", 1000))


def get_default_salesrep_id() -> int:
    """Get default sales rep ID."""
    return int(get_config_value("default_salesrep_id", 10067))


def get_default_ship_to_org_id() -> int:
    """Get default ship-to org ID."""
    return int(get_config_value("default_ship_to_org_id", 6472))


def get_default_sold_to_org_id() -> int:
    """Get default sold-to org ID."""
    return int(get_config_value("default_sold_to_org_id", 5391))


def get_default_inventory_item_id() -> int:
    """Get default inventory item ID."""
    return int(get_config_value("default_inventory_item_id", 12027))


def get_max_choices() -> int:
    """Get max choices value."""
    return int(get_config_value("max_choices", 10))


def get_operating_unit() -> str:
    """Get operating unit name."""
    return get_config_value("operating_unit", "Vision Operations")


def get_rest_header() -> Dict[str, str]:
    """Build REST API header with Oracle Apps context."""
    return {
        "Responsibility": get_config_value("responsibility", "ORDER_MGMT_SUPER_USER"),
        "RespApplication": get_config_value("resp_application", "ONT"),
        "SecurityGroup": get_config_value("security_group", "STANDARD"),
        "NLSLanguage": get_config_value("nls_language", "AMERICAN"),
        "Org_Id": str(get_org_id()),
    }


def get_service_urls() -> Dict[str, str]:
    """Get service URLs from configuration."""
    base = get_config_value("api_base_url", DEFAULT_CONFIG["api_base_url"]).rstrip("/")
    return {
        "get_order": f"{base}/webservices/rest/sales_order/GET_ORDER/",
        "process_order": f"{base}/webservices/rest/sales_order/PROCESS_ORDER/",
        "cust_so_dtls": f"{base}/webservices/rest/CustSODtls/XX_CUST_SO_DET_PRC1/"
    }
