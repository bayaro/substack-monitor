def __flatten(item, prefix=""):
    record = {}
    for key, value in (item or {}).items():
        flat_key = f"{prefix}_{key}" if prefix else key
        if isinstance(value, dict):
            record.update(__flatten(value, flat_key))
        else:
            record[flat_key] = value
    return record


def __is_selector(key):
    return isinstance(key, str) and key.startswith("[") and key.endswith("]")


def __traverse_list(items, spec, prefix, mode):
    # spec entries pick list elements by a quoted bracket selector: "[first]", "[last]",
    # "[0]", "[-2]" or "[*]" for all. Columns: <prefix>_<first|last|index>_<field>
    record = {}
    for entry in spec:
        for selector, subspec in (entry if isinstance(entry, dict) else {entry: None}).items():
            text = str(selector)
            if not (text.startswith("[") and text.endswith("]")):
                raise ValueError(f"list selector must be bracketed, e.g. \"[last]\": {selector!r} under {prefix}")
            name = text[1:-1]
            if name == "*":
                picks = list(range(len(items)))
            elif name in ("first", "last"):
                picks = [0 if name == "first" else len(items) - 1] if items else []
            else:
                idx = int(name)
                picks = [idx % len(items)] if items and -len(items) <= idx < len(items) else []
            for idx in picks:
                label = name if name in ("first", "last") else idx
                key = f"{prefix}_{label}"
                if subspec:
                    record.update(__traverse(items[idx], subspec, key, mode))
                else:
                    value = items[idx]
                    record.update(__flatten(value, key) if isinstance(value, dict) else {key: value})
    return record


def __traverse(item, spec, prefix="", mode="include"):
    if not isinstance(item, dict):
        return {}
    spec_map = {e: None for e in spec if isinstance(e, str)}
    for e in spec:
        if isinstance(e, dict):
            spec_map.update(e)
    where = prefix or "<root>"
    for key in spec_map:
        if __is_selector(key):
            reason = "list selectors are only supported in include" if mode == "exclude" else "value is not a list"
            raise ValueError(f"list selector {key!r} under {where}: {reason}")
    record = {}
    for key, value in item.items():
        flat_key = f"{prefix}_{key}" if prefix else key
        subspec = spec_map.get(key)
        in_spec = key in spec_map
        if subspec and mode == "include" and isinstance(value, list):
            record.update(__traverse_list(value, subspec, flat_key, mode))
        elif subspec and isinstance(value, list):
            if any(__is_selector(k) for e in subspec for k in (e if isinstance(e, dict) else {e: None})):
                raise ValueError(f"list selectors are only supported in include (under {flat_key!r})")
            raise ValueError(f"exclude cannot look inside the list {flat_key!r}; exclude the whole key instead")
        elif subspec:
            record.update(__traverse(value or {}, subspec, flat_key, mode))
        elif (mode == "include") == in_spec:
            record.update(__flatten(value, flat_key) if isinstance(value, dict) else {flat_key: value})
    return record


def __filter_columns(items, include=None, exclude=None):
    if exclude:
        return [__traverse(item, exclude, mode="exclude") for item in items]
    if include:
        return [__traverse(item, include) for item in items]
    return [__flatten(item) for item in items]


def filter_items(items, endpoint):
    columns = endpoint.get("columns")
    if columns:  # rows are positional lists, e.g. [date, value]: name them
        items = [dict(zip(columns, row)) for row in items]
    delta = endpoint.get("delta")
    if delta:  # change versus the previous row, in ascending sort_key order
        items = sorted(items, key=lambda i: i[endpoint["sort_key"]]) if endpoint.get("sort_key") else items
        previous = None
        for item in items:
            value = item.get(delta)
            item[f"{delta}_delta"] = None if previous is None or value is None else value - previous
            previous = value
    for condition in endpoint.get("filter") or []:
        items = [i for i in items if all(i.get(k) == v for k, v in condition.items())]
    records = __filter_columns(items, endpoint.get("include"), endpoint.get("exclude"))
    return [{k: v for k, v in record.items() if v is not None and v != ""} for record in records]
