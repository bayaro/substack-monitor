import json
import time
from pathlib import Path

import requests

import config


def __read_cookies():
    text = Path(config.CONFIG.cookie_file).read_text(encoding="utf-8").strip()
    cookies = {}
    for pair in text.split(";"):
        name, sep, value = pair.strip().partition("=")
        if sep:
            cookies[name] = value
    return cookies


def __save_cookies(cookies):
    Path(config.CONFIG.cookie_file).write_text(
        "; ".join(f"{k}={v}" for k, v in cookies.items()), encoding="utf-8"
    )


def __prompt_cookie():
    print(
        "\nTo get a fresh cookie:\n"
        "  1. Open your browser and go to substack.com\n"
        "  2. Open DevTools (F12) > Network tab\n"
        "  3. Reload the page, click any request to substack.com\n"
        "  4. In Request Headers, find 'Cookie' and copy its full value\n"
    )
    cookie = input("Paste cookie value: ").strip()
    Path(config.CONFIG.cookie_file).write_text(cookie, encoding="utf-8")
    print(f"Saved to {config.CONFIG.cookie_file}\n")


def ensure_cookie():
    if not Path(config.CONFIG.cookie_file).exists():
        print("Cookie file is missing.")
        __prompt_cookie()


# delay: minimum gap in seconds between requests, loaded lazily from rate_limit_state_file
# last: monotonic time the previous response arrived (None before the first request)
RATE = {"delay": None, "last": None}

# counters for summary(): requests sent, 429 answers, seconds slept for the rate limit
STATS = {"requests": 0, "rate_limited": 0, "waited": 0.0}


def __delay():
    if RATE["delay"] is None:
        try:
            RATE["delay"] = max(0.0, float(Path(config.CONFIG.rate_limit_state_file).read_text().strip()))
        except (OSError, ValueError):
            RATE["delay"] = 0.0
    return RATE["delay"]


def __set_delay(value):
    if value < 0.1:
        value = 0.0
    if value != __delay():
        RATE["delay"] = value
        Path(config.CONFIG.rate_limit_state_file).write_text(f"{value:.3f}", encoding="utf-8")


def __slow_down(response, attempt):
    delay = max(__delay() * 2, config.CONFIG.rate_limit_delay_seconds)
    try:
        delay = max(delay, float(response.headers.get("Retry-After", 0)))
    except ValueError:
        pass
    delay = min(delay, config.CONFIG.rate_limit_max_delay_seconds)
    __set_delay(delay)
    print(f"Rate limited, waiting {delay:.1f}s before every request (retry {attempt + 1}/{config.CONFIG.rate_limit_retries})")


def summary():
    return (f"{STATS['requests']} requests, {STATS['rate_limited']} rate limited, "
            f"waited {STATS['waited']:.1f}s, delay now {__delay():.1f}s")


def request(url, params=None, method="get", body=None, retry=True, attempt=0):
    if RATE["last"] is not None:  # time spent processing the previous response counts towards the delay
        wait = __delay() - (time.monotonic() - RATE["last"])
        if wait > 0:
            time.sleep(wait)
            STATS["waited"] += wait
    STATS["requests"] += 1
    cookies = __read_cookies()
    full_url = requests.Request(method, url, params=params).prepare().url
    suffix = f" body={json.dumps(body)}" if body else ""
    print(f"{method.upper()} {full_url}{suffix}", end="", flush=True)
    started = time.perf_counter()
    try:
        response = getattr(requests, method)(
            url,
            params=params,
            json=body,
            headers={
                **config.CONFIG.headers,
                "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
            },
            timeout=config.CONFIG.timeout,
        )
    except Exception as e:
        RATE["last"] = time.monotonic()
        print(f" -> {type(e).__name__} in {time.perf_counter() - started:.2f}s")
        raise
    RATE["last"] = time.monotonic()
    print(f" -> {response.status_code} in {time.perf_counter() - started:.2f}s")
    updated = {**cookies, **response.cookies.get_dict()}
    if updated != cookies:
        __save_cookies(updated)
    if response.status_code == 429:
        STATS["rate_limited"] += 1
    if response.status_code == 429 and attempt < config.CONFIG.rate_limit_retries:
        __slow_down(response, attempt)
        return request(url, params, method, body, retry, attempt + 1)
    if response.status_code in (401, 403) and retry:
        print("Cookie was rejected by the server.")
        __prompt_cookie()
        return request(url, params, method, body, retry=False, attempt=attempt)
    response.raise_for_status()
    __set_delay(__delay() * (1 - config.CONFIG.rate_limit_decay))
    return response.json()
