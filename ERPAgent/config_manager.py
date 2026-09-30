"""
Configuration Management Module for the ERP Sales Order Assistant.

Configuration is loaded from config.json next to this module, or from the
workspace-level config.json when no local file exists. Encrypted secret
values are decrypted in memory using the matching config.key file.
"""

import json
import os
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(BASE_DIR)
CONFIG_CANDIDATES = (
    os.path.join(BASE_DIR, "config.json"),
    os.path.join(WORKSPACE_DIR, "config.json"),
)
CONFIG_FILE = next((path for path in CONFIG_CANDIDATES if os.path.exists(path)), CONFIG_CANDIDATES[0])
KEY_FILE = os.path.join(os.path.dirname(CONFIG_FILE), "config.key")

ENCRYPTED_FIELDS = {
    "db_password",
    "api_password",
    "grok_api_key",
    "xai_api_key",
    "smtp_password",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    # ============ Database ============
    "db_host": "cendb.centroid.com",
    "db_port": "1541",
    "db_service": "EBS122",
    "db_user": "apps",
    "db_password": "",
    "oracle_client_path": r"C:\Oracle\instantclient_19_10",

    # ============ REST API ============
    "api_base_url": "https://cendb.ad.centroid.com:4463",
    "api_user": "operations",
    "api_password": "welcome",
    # The internal EBS endpoint uses a self-signed certificate.
    "verify_ssl": False,

    # ============ AI / LLM ============
    # Base URL / model must match the provider the API key belongs to
    # (gsk_... = Groq, xai-... = xAI https://api.x.ai/v1 with a grok-* model).
    "xai_api_key": "REDACTED_SECRET",
    "grok_api_key": "REDACTED_SECRET",
    "grok_base_url": "https://api.groq.com/openai/v1",
    "grok_model": "qwen/qwen3.8-27b",
    "grok_max_retries": 2,
    "grok_retry_base_seconds": 1.5,

    # ============ Oracle Apps ============
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

    # ============ Email ============
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_sender": "erp.assistant@yourdomain.com",
    "auto_email_enabled": False,
    "auto_email_to": "",

    # ============ Scheduler ============
    "scheduler_default_interval_mins": 60,
    "scheduler_default_customer_name": "",
    "scheduler_default_to_email": "",

    # ============ Flask App ============
    "app_host": "0.0.0.0",
    "app_port": 5000,
    "app_debug": False,
    "app_use_reloader": False,
    "app_tls_enabled": True,
    "trusted_proxy_hops": 0,
    "ngrok_public_url": "",
}

CONFIG_GROUPS: Dict[str, list] = {
    "database": ["db_host", "db_port", "db_service", "db_user", "db_password", "oracle_client_path"],
    "api": ["api_base_url", "api_user", "api_password", "verify_ssl"],
    "ai_llm": ["xai_api_key", "grok_api_key", "grok_base_url", "grok_model",
               "grok_max_retries", "grok_retry_base_seconds"],
    "oracle_apps": ["org_id", "order_type_id", "default_payment_term_id", "default_price_list_id",
                    "default_salesrep_id", "default_ship_to_org_id", "default_sold_to_org_id",
                    "default_inventory_item_id", "operating_unit", "max_choices", "responsibility",
                    "resp_application", "security_group", "nls_language"],
    "email": ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_sender",
              "auto_email_enabled", "auto_email_to"],
    "scheduler": ["scheduler_default_interval_mins", "scheduler_default_customer_name",
                  "scheduler_default_to_email"],
        "app": ["app_host", "app_port", "app_debug", "app_use_reloader", "app_tls_enabled",
            "trusted_proxy_hops", "ngrok_public_url"],
}


class ConfigManager:
    """Singleton configuration manager backed by a plain JSON file."""

    _instance: Optional["ConfigManager"] = None

    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._config = {}
            instance._load_config()
            cls._instance = instance
        return cls._instance

    def _load_config(self) -> None:
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                    file_config = json.load(fh)
                if isinstance(file_config, dict):
                    config.update(file_config)
            except Exception as exc:
                print(f"Warning: Could not load config file: {exc}")
        self._config = self._decrypt_secrets(config)

    @staticmethod
    def _decrypt_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
        decrypted = dict(config)
        encrypted_values = {
            field: value
            for field, value in config.items()
            if field in ENCRYPTED_FIELDS and isinstance(value, str) and value.startswith("enc:")
        }
        if not encrypted_values:
            return decrypted

        try:
            with open(KEY_FILE, "rb") as fh:
                fernet = Fernet(fh.read().strip())
            for field, value in encrypted_values.items():
                decrypted[field] = fernet.decrypt(value[4:].encode()).decode()
        except (OSError, ValueError, InvalidToken) as exc:
            raise RuntimeError(
                f"Could not decrypt secrets for {CONFIG_FILE}. "
                f"Ensure the matching config.key is present: {exc}"
            ) from exc
        return decrypted

    def _save_to_file(self) -> None:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(self._config, fh, indent=4)
        except Exception as exc:
            print(f"Warning: Could not save config file: {exc}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._config[key] = value
        self._save_to_file()

    def get_all(self) -> Dict[str, Any]:
        # Live dict so callers holding a reference see later updates.
        return self._config

    def get_group(self, group_name: str) -> Dict[str, Any]:
        if group_name not in CONFIG_GROUPS:
            raise ValueError(f"Unknown config group: {group_name}")
        return {key: self._config.get(key) for key in CONFIG_GROUPS[group_name]}

    def reload(self) -> None:
        self._load_config()


def load_config() -> Dict[str, Any]:
    return ConfigManager().get_all()


def get_config_value(key: str, default: Any = None) -> Any:
    return ConfigManager().get(key, default)


def set_config_value(key: str, value: Any) -> None:
    ConfigManager().set(key, value)


def get_config_group(group_name: str) -> Dict[str, Any]:
    return ConfigManager().get_group(group_name)


def reload_config() -> None:
    ConfigManager().reload()


app_config = load_config()


def get_org_id() -> int:
    return int(get_config_value("org_id", "204"))


def get_order_type_id() -> int:
    return int(get_config_value("order_type_id", 1437))


def get_default_payment_term_id() -> int:
    return int(get_config_value("default_payment_term_id", 4))


def get_default_price_list_id() -> int:
    return int(get_config_value("default_price_list_id", 1000))


def get_default_salesrep_id() -> int:
    return int(get_config_value("default_salesrep_id", 10067))


def get_default_ship_to_org_id() -> int:
    return int(get_config_value("default_ship_to_org_id", 6472))


def get_default_sold_to_org_id() -> int:
    return int(get_config_value("default_sold_to_org_id", 5391))


def get_default_inventory_item_id() -> int:
    return int(get_config_value("default_inventory_item_id", 12027))


def get_max_choices() -> int:
    return int(get_config_value("max_choices", 10))


def get_operating_unit() -> str:
    return str(get_config_value("operating_unit", "Vision Operations"))


def get_rest_header() -> Dict[str, str]:
    """Oracle Apps context headers required by the EBS ISG REST services."""
    return {
        "Responsibility": get_config_value("responsibility", "ORDER_MGMT_SUPER_USER"),
        "RespApplication": get_config_value("resp_application", "ONT"),
        "SecurityGroup": get_config_value("security_group", "STANDARD"),
        "NLSLanguage": get_config_value("nls_language", "AMERICAN"),
        "Org_Id": str(get_org_id()),
    }


def get_service_urls() -> Dict[str, str]:
    base = str(get_config_value("api_base_url", DEFAULT_CONFIG["api_base_url"])).rstrip("/")
    return {
        "get_order": f"{base}/webservices/rest/sales_order/GET_ORDER/",
        "process_order": f"{base}/webservices/rest/sales_order/PROCESS_ORDER/",
        "cust_so_dtls": f"{base}/webservices/rest/CustSODtls/XX_CUST_SO_DET_PRC1/",
    }
