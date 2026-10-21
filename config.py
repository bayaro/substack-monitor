import difflib

import yaml

GLOBAL_KEYS = {
    "account_name", "base_url", "data_dir", "cache_dir", "cache_auto_age_minutes", "cookie_file",
    "user_id_file", "timeout", "headers", "rate_limit_state_file", "rate_limit_delay_seconds",
    "rate_limit_max_delay_seconds", "rate_limit_retries", "rate_limit_decay",
}
ENDPOINT_KEYS = {
    "url", "method", "params", "body", "pagination", "limit", "items_field", "cursor_field",
    "sort_key", "filter", "include", "exclude", "columns", "delta",
}


# the active configuration, filled by load_config() and read by every module as config.CONFIG
CONFIG = {}


def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        CONFIG.clear()
        CONFIG.update(yaml.safe_load(f))
    return CONFIG


def __unknown_key(key, known, where):
    hint = difflib.get_close_matches(str(key), known, n=1)
    return f"{where}: unknown key {key!r}" + (f", did you mean {hint[0]!r}?" if hint else "")


def validate_config(config):
    # keys starting with "_" are inactive and skipped; returns a list of problems
    errors = []
    for name, section in config.items():
        if str(name).startswith("_") or name in GLOBAL_KEYS:
            continue
        if not isinstance(section, dict):
            errors.append(__unknown_key(name, GLOBAL_KEYS, "config"))
            continue
        if "url" not in section:
            errors.append(__unknown_key(name, GLOBAL_KEYS, "config") + f" (section {name!r} has no url)")
            continue
        for key in section:
            if not str(key).startswith("_") and key not in ENDPOINT_KEYS:
                errors.append(__unknown_key(key, ENDPOINT_KEYS, name))
        if section.get("method", "get") not in ("get", "post"):
            errors.append(f"{name}: method must be get or post, not {section['method']!r}")
        if section.get("pagination") not in (None, "offset", "cursor"):
            errors.append(f"{name}: pagination must be offset or cursor, not {section['pagination']!r}")
        for key in ("include", "exclude", "filter", "columns"):
            if key in section and not isinstance(section[key], list):
                errors.append(f"{name}: {key} must be a list")
        if section.get("delta") and isinstance(section.get("columns"), list) and section["delta"] not in section["columns"]:
            errors.append(f"{name}: delta {section['delta']!r} is not one of columns")
    return errors
