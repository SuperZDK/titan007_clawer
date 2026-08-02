"""
Playwright-based HTTP fetcher singleton.
Replaces requests.Session for zq/1x2d fetching.
One browser context per thread (thread-safe).
"""
import atexit
import time
import random
import threading
from typing import Optional

from playwright.sync_api import sync_playwright, Browser
from core.user_agents import UA_LIST

_browser: Optional[Browser] = None
_playwright = None
_lock = threading.Lock()
_contexts = threading.local()


def _get_browser() -> Browser:
    global _browser, _playwright
    if _browser is None:
        with _lock:
            if _browser is None:
                _playwright = sync_playwright().start()
                _browser = _playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                )
    return _browser


def _get_context():
    if not hasattr(_contexts, "ctx") or _contexts.ctx is None:
        browser = _get_browser()
        _contexts.ctx = browser.new_context(
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            viewport={
                "width": random.randint(1200, 1400),
                "height": random.randint(800, 900),
            },
            user_agent=random.choice(UA_LIST),
            extra_http_headers={
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
    return _contexts.ctx


def fetch_text(
    url: str,
    referer: Optional[str] = None,
    accept: str = "text/html,*/*",
    timeout: int = 30000,
    max_retry: int = 2,
) -> Optional[str]:
    ctx = _get_context()
    for attempt in range(max_retry):
        page = ctx.new_page()
        try:
            headers = {"Accept": accept}
            if referer:
                headers["Referer"] = referer
            page.set_extra_http_headers(headers)
            resp = page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if resp:
                if resp.ok:
                    return resp.text()
                if resp.status == 404:
                    return None
        except Exception:
            if attempt < max_retry - 1:
                time.sleep(2)
        finally:
            page.close()
    return None


def fetch_bytes(
    url: str,
    referer: Optional[str] = None,
    accept: str = "text/html,*/*",
    timeout: int = 30000,
    max_retry: int = 2,
) -> Optional[bytes]:
    ctx = _get_context()
    for attempt in range(max_retry):
        page = ctx.new_page()
        try:
            headers = {"Accept": accept}
            if referer:
                headers["Referer"] = referer
            page.set_extra_http_headers(headers)
            resp = page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            if resp:
                if resp.ok:
                    return resp.body()
                if resp.status == 404:
                    return None
        except Exception:
            if attempt < max_retry - 1:
                time.sleep(2)
        finally:
            page.close()
    return None


def close():
    global _browser, _playwright
    with _lock:
        if _browser:
            try:
                _browser.close()
            except Exception:
                pass
            _browser = None
        if _playwright:
            try:
                _playwright.stop()
            except Exception:
                pass
            _playwright = None


atexit.register(close)
