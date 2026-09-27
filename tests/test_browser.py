from vinted_tracker.browser import RateLimiter, is_challenge, save_debug_page, should_block
from vinted_tracker.models import FetchedPage


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def limiter(clock, lo=8, hi=12, per_hour=360, gap=10.0):
    return RateLimiter(lo, hi, per_hour, clock=clock.now, sleep=clock.sleep, rand=lambda a, b: gap)


def test_first_wait_does_not_sleep():
    clock = FakeClock()
    limiter(clock).wait()
    assert clock.sleeps == []


def test_waits_the_rest_of_the_random_gap():
    clock = FakeClock()
    lim = limiter(clock)
    lim.wait()
    clock.t += 3
    lim.wait()
    assert clock.sleeps == [7.0]


def test_no_sleep_when_gap_already_passed():
    clock = FakeClock()
    lim = limiter(clock)
    lim.wait()
    clock.t += 30
    lim.wait()
    assert clock.sleeps == []


def test_hourly_cap():
    clock = FakeClock()
    lim = limiter(clock, lo=1, hi=1, per_hour=3, gap=1.0)
    for _ in range(4):
        lim.wait()
    assert clock.sleeps == [1.0, 1.0, 1.0, 3597.0]


def test_is_challenge():
    assert is_challenge(403, "")
    assert is_challenge(429, "")
    assert is_challenge(200, '<iframe src="https://geo.captcha-delivery.com/captcha/?x=1"></iframe>')
    assert not is_challenge(200, "<html>ok</html>")
    assert not is_challenge(404, "<html>not found</html>")


def test_should_block():
    assert should_block("image", "https://images1.vinted.net/t/x.webp")
    assert should_block("font", "https://www.vinted.ro/font.woff2")
    assert should_block("script", "https://securepubads.g.doubleclick.net/tag/js/gpt.js")
    assert should_block("xhr", "https://fastlane.rubiconproject.com/a/api/fastlane.json")
    assert not should_block("document", "https://www.vinted.ro/items/1")
    assert not should_block("script", "https://www.vinted.ro/_next/static/chunk.js")


def test_save_debug_page(tmp_path):
    page = FetchedPage(url="https://www.vinted.ro/items/1", status=200, html="<html>x</html>", text="x")
    path = save_debug_page(page, "item-1", tmp_path)
    assert path.read_text(encoding="utf-8") == "<html>x</html>"
    assert path.with_suffix(".txt").read_text(encoding="utf-8").startswith("URL: https://www.vinted.ro/items/1")
