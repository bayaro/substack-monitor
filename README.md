# substack-monitor

Pulls data for a Substack account (subscribers, posts, notes, replies, followers, ...) through the
web API and saves each endpoint as a YAML snapshot in `data/`. What is fetched and which columns
are kept is described in `config.yaml`, not in code.

## Usage

```
pip install -r requirements.txt
python cli.py -m subscribers            # one endpoint from config.yaml
python cli.py -m all                    # every endpoint
python cli.py -m replies --cache write  # always fetch
python cli.py -m replies --force        # start an interrupted download over
python -m pytest -q                     # tests
```

| option | meaning |
|---|---|
| `--cache auto` (default) | read the cache if younger than `cache_auto_age_minutes`, otherwise fetch and write it |
| `--cache write` | always fetch and write the cache |
| `--cache read` | never fetch, use the cache only |
| `--force` | do not continue an interrupted download |

An interrupted download (error, 429 retries used up, Ctrl+C) keeps its partial cache and the next
run continues from the saved cursor/offset.

Every run ends with a summary line, also after a failure:
`Summary: 12 requests, 1 rate limited, waited 3.0s, delay now 2.8s, took 9.4s`.

## Modules

| file | responsibility |
|---|---|
| `cli.py` | arguments, loops over endpoints, sorts and writes `data/<name>.yaml` |
| `config.py` | `CONFIG` (global settings as attributes, endpoint sections in `CONFIG.endpoints`), the defaults in `GLOBAL_KEYS`, `load_config()`, `validate_config()` |
| `fetch.py` | one endpoint: URL, pagination (offset/cursor), cache modes, resume, `user_id` lookup |
| `request.py` | one HTTP call: cookie file, rate-limit delay and 429 backoff, 401/403 cookie prompt |
| `record.py` | raw API items -> flat records: `filter`, `include`/`exclude`, `columns`/`delta`, drop empty values |

## What calls what

```
cli.main
 ├─ config.load_config()                        reads and validates config.yaml, fills config.CONFIG
 └─ cli.__collect(endpoint)                     for every endpoint
     ├─ fetch.do_request(endpoint)
     │   ├─ cache is fresh / --cache read ──▶ read cache/<name>.yaml ──▶ record.filter_items
     │   └─ otherwise ──▶ fetch.fetch(endpoint)
     │        ├─ fetch.__ensure_user_id()      only if the URL has {user_id}
     │        │    └─ fetch.do_request("users")   asks which user to use, saves user_id.txt
     │        ├─ request.ensure_cookie()       prompts if cookie.txt is missing
     │        └─ for every page:
     │             ├─ request.request(...)     see below
     │             ├─ write raw items to cache/<name>.yaml.tmp, save <name>.yaml.progress
     │             └─ record.filter_items(page)
     │           at the end: .tmp -> cache/<name>.yaml, remove .progress
     └─ sort by sort_key, write data/<name>.yaml

request.request
 ├─ sleep until the rate-limit gap since the last response has passed
 ├─ send with the Cookie from cookie.txt, store any Set-Cookie back
 ├─ 429      ──▶ raise the delay (3s, x2 ... max 60s, Retry-After), retry
 ├─ 401/403  ──▶ prompt for a new cookie, retry once
 └─ 2xx      ──▶ decay the delay by 5%, return JSON
```

## Files written next to the code (all git-ignored)

| path | content |
|---|---|
| `data/` | the result, one YAML list per endpoint |
| `cache/` | raw API responses; `*.tmp` and `*.progress` exist only for an interrupted download |
| `cookie.txt` | the `Cookie` header pasted from the browser, kept up to date from `Set-Cookie` |
| `user_id.txt` | the chosen user id for `{user_id}` URLs |
| `rate_delay.txt` | the current rate-limit delay, kept between runs |

## config.yaml

Top-level scalars are global settings (paths, `timeout`, `headers`, `rate_limit_*`, ...). Their
defaults live in `GLOBAL_KEYS` in `config.py`, so config.yaml only lists what differs; `account_name`
and `base_url` have no default and are required. In code a setting is read as
`config.CONFIG.timeout`. Every top-level section with a `url` is an endpoint. Endpoint keys: `url`, `method`, `params`, `body`,
`pagination` (`offset`/`cursor`), `limit`, `items_field`, `cursor_field`, `sort_key`, `filter`,
`include`, `exclude`, `columns`, `delta`. A key starting with `_` is inactive. The whole file is
validated at startup, unknown keys are reported with a hint.

`include` / `exclude` take field names, nested lists for sub-fields, and for lists a quoted
selector: `"[first]"`, `"[last]"`, `"[2]"`, `"[*]"` (include only). Nested keys are joined with `_`.
