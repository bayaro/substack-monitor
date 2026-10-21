import copy
import difflib

import yaml

# the known global settings and their defaults; None means "no default, must be set in config.yaml"
GLOBAL_KEYS = {
    "account_name": None,
    "base_url": None,
    "data_dir": "./data",
    "cache_dir": "./cache",
    "cache_auto_age_minutes": 10,
    "cookie_file": "./cookie.txt",
    "user_id_file": "./user_id.txt",
    "timeout": 30,
    "headers": {},
    "rate_limit_state_file": "./rate_delay.txt",
    "rate_limit_delay_seconds": 3,
    "rate_limit_max_delay_seconds": 60,
    "rate_limit_retries": 5,
    "rate_limit_decay": 0.05,
}
ENDPOINT_KEYS = {
    "url", "method", "params", "body", "pagination", "limit", "items_field", "cursor_field",
    "sort_key", "filter", "include", "exclude", "columns", "delta",
}


class ConfigError(Exception):
    pass


class Config:
    """The active configuration, read by every module as config.CONFIG.

    Global settings are attributes (config.CONFIG.timeout): the GLOBAL_KEYS defaults overlaid with
    config.yaml. Endpoint sections are in .endpoints[name]. cache and force come from the command line.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        for key, default in GLOBAL_KEYS.items():
            setattr(self, key, copy.deepcopy(default))
        self.endpoints = {}
        self.cache = None
        self.force = False

    def load(self, raw):
        self.reset()
        for name, value in raw.items():
            if name in GLOBAL_KEYS:
                setattr(self, name, value)
            elif isinstance(value, dict) and not str(name).startswith("_"):
                self.endpoints[name] = value


CONFIG = Config()


def load_config(path="config.yaml"):
    """Read and validate config.yaml and fill CONFIG; raises ConfigError listing every problem."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    errors = validate_config(raw)
    if errors:
        raise ConfigError("invalid config.yaml:\n  " + "\n  ".join(errors))
    CONFIG.load(raw)


def __unknown_key(key, known, where):
    hint = difflib.get_close_matches(str(key), known, n=1)
    return f"{where}: unknown key {key!r}" + (f", did you mean {hint[0]!r}?" if hint else "")


def validate_config(config):
    # keys starting with "_" are inactive and skipped; returns a list of problems
    errors = [f"config: {key} is required" for key, default in GLOBAL_KEYS.items()
              if default is None and config.get(key) in (None, "")]
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
