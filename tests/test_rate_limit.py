from pathlib import Path

import pytest
import requests

import config
import request


@pytest.fixture
def clock(monkeypatch):
    """Fake time: sleep() advances it instantly and is recorded; tick() simulates processing time."""
    class Clock:
        now = 1000.0
        sleeps = []

        def sleep(self, seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        def tick(self, seconds):
            self.now += seconds

    fake = Clock()
    fake.sleeps = []
    monkeypatch.setattr("time.sleep", fake.sleep)
    monkeypatch.setattr("time.monotonic", lambda: fake.now)
    return fake


@pytest.fixture
def sleeps(clock):
    return clock.sleeps


@pytest.fixture
def state_file(env):
    return Path(config.CONFIG.rate_limit_state_file)


def limited(times, headers=None):
    """Handler answering 429 `times` times, then 200."""
    served = []

    def handler(req):
        served.append(req)
        return (429, {}, headers or {}) if len(served) <= times else (200, [], {})
    return handler


def test_no_delay_by_default(env,server, sleeps):
    request.request(f"{server.url}/x")
    assert sleeps == []


def test_first_429_sets_initial_delay_and_retries(env,server, sleeps, state_file):
    server.handler = limited(1)
    assert request.request(f"{server.url}/x") == []
    assert len(server.requests) == 2
    assert sleeps == [3]
    assert float(state_file.read_text()) == pytest.approx(3 * 0.95)  # decayed once by the success


def test_repeated_429_doubles_the_delay(env,server, sleeps):
    server.handler = limited(3)
    request.request(f"{server.url}/x")
    assert sleeps == [3, 6, 12]


def test_success_decays_the_delay_by_five_percent(env,server, sleeps):
    request.__set_delay(10)
    request.request(f"{server.url}/x")
    request.request(f"{server.url}/x")
    request.request(f"{server.url}/x")
    assert sleeps == [pytest.approx(9.5), pytest.approx(9.025)]
    assert request.__delay() == pytest.approx(10 * 0.95 ** 3)


def test_first_request_is_not_delayed(env,server, sleeps):
    request.__set_delay(10)
    request.request(f"{server.url}/x")
    assert sleeps == []


def test_processing_time_counts_towards_the_delay(env,server, clock):
    request.__set_delay(10)
    request.request(f"{server.url}/x")  # delay is now 9.5
    clock.tick(4)
    request.request(f"{server.url}/x")
    assert clock.sleeps == [pytest.approx(5.5)]


def test_no_wait_when_processing_took_longer_than_the_delay(env,server, clock):
    request.__set_delay(10)
    request.request(f"{server.url}/x")
    clock.tick(60)
    request.request(f"{server.url}/x")
    assert clock.sleeps == []


def test_tiny_delay_snaps_to_zero(env,server, sleeps):
    request.__set_delay(0.1)
    request.request(f"{server.url}/x")
    assert request.__delay() == 0


def test_delay_is_capped(env,server, sleeps):
    config.CONFIG.rate_limit_max_delay_seconds = 5
    server.handler = limited(3)
    request.request(f"{server.url}/x")
    assert sleeps == [3, 5, 5]


def test_retry_after_header_wins_when_larger(env,server, sleeps):
    server.handler = limited(1, {"Retry-After": "20"})
    request.request(f"{server.url}/x")
    assert sleeps == [20]


def test_garbled_retry_after_is_ignored(env,server, sleeps):
    server.handler = limited(1, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    request.request(f"{server.url}/x")
    assert sleeps == [3]


def test_gives_up_after_the_retry_limit(env,server, sleeps):
    config.CONFIG.rate_limit_retries = 2
    server.handler = lambda req: (429, {}, {})
    with pytest.raises(requests.HTTPError):
        request.request(f"{server.url}/x")
    assert len(server.requests) == 3  # the first try and two retries


def test_delay_is_saved_and_loaded_by_the_next_run(env,server, sleeps, state_file):
    server.handler = limited(1)
    request.request(f"{server.url}/x")
    saved = float(state_file.read_text())
    request.RATE["delay"] = None  # a new process
    assert request.__delay() == pytest.approx(saved, abs=0.001)


@pytest.mark.parametrize("content", ["", "abc", "-5"])
def test_bad_state_file_means_no_delay(env,state_file, content):
    state_file.write_text(content)
    assert request.__delay() == 0


def test_other_errors_do_not_change_the_delay(env,server, sleeps):
    server.handler = lambda req: (500, {}, {})
    with pytest.raises(requests.HTTPError):
        request.request(f"{server.url}/x")
    assert request.__delay() == 0
