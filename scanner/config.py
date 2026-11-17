import json
import os
from pathlib import Path

WEB_APP_URL = os.getenv(
    "SHEETS_WEB_APP_URL",
    "https://script.google.com/macros/s/AKfycbxwx2aahfkilC3IOWUZtb1jfRuG1dWTNfEsPA0_WDFWB2xzmqBMyEhJloZKpafLnRVi_A/exec",
)
CONFIG_PATH = Path(__file__).resolve().parent.parent / "source_config.json"
DEFAULT_SOURCE_CONFIG = {
    "mode": "auto", "max_pages": 1, "max_items": 200,
    "timeout_connect": 8, "timeout_read": 18, "follow_pagination": False,
}

def load_source_config():
    if not CONFIG_PATH.exists():
        return {"defaults": {}, "sources": {}}
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        data.setdefault("defaults", {})
        data.setdefault("sources", {})
        return data
    except Exception as exc:
        raise RuntimeError(f"Cannot read source_config.json: {exc}") from exc

def config_for_source(source, config_data):
    merged = dict(DEFAULT_SOURCE_CONFIG)
    merged.update(config_data.get("defaults", {}))
    source_map = config_data.get("sources", {})
    url_key = (source.get("url") or "").rstrip("/")
    name_key = (source.get("name") or "").strip()
    merged.update(source_map.get(url_key) or source_map.get(name_key) or {})
    return merged
