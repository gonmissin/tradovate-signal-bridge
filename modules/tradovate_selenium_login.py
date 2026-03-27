"""
Tradovate web trader login via Selenium + Chrome performance logs / CDP,
same flow as enable.py: capture /auth/accesstokenrequest response body.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import urlparse

START_URL = "https://trader.tradovate.com/"

try:
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
except ImportError as e:
    raise ImportError("Selenium is required: pip install selenium") from e


def build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
        opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def _parse_performance_log_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return json.loads(entry["message"])["message"]
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def _decode_response_body(body: dict[str, Any]) -> str | None:
    raw = body.get("body") or ""
    if body.get("base64Encoded"):
        try:
            return base64.b64decode(raw).decode("utf-8", errors="replace")
        except Exception:
            return None
    return raw if isinstance(raw, str) else None


def capture_accesstoken_response_items(driver: webdriver.Chrome) -> list[tuple[str, str]]:
    """List of (decoded body, full request URL) for each accesstokenrequest response."""
    found: list[tuple[str, str]] = []
    seen_rids: set[str] = set()
    for entry in driver.get_log("performance"):
        msg = _parse_performance_log_entry(entry)
        if not msg or msg.get("method") != "Network.responseReceived":
            continue
        params = msg.get("params") or {}
        response = params.get("response") or {}
        url_full = response.get("url") or ""
        url_l = url_full.lower()
        if "accesstokenrequest" not in url_l or "tradovateapi.com" not in url_l:
            continue
        rid = params.get("requestId")
        if not rid or rid in seen_rids:
            continue
        seen_rids.add(rid)
        try:
            body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
        except Exception:
            continue
        text = _decode_response_body(body)
        if text is not None and text.strip():
            found.append((text.strip(), url_full))
    return found


def wait_for_accesstoken_pair(
    driver: webdriver.Chrome,
    timeout: float = 120.0,
    poll: float = 0.5,
) -> tuple[str, str] | None:
    """Wait until JSON includes non-empty accessToken; return (body, request_url)."""
    deadline = time.monotonic() + timeout
    last_pair: tuple[str, str] | None = None
    while time.monotonic() < deadline:
        items = capture_accesstoken_response_items(driver)
        if items:
            body, url = items[-1]
            last_pair = (body, url)
            try:
                data = json.loads(body)
                tok = data.get("accessToken")
                if isinstance(tok, str) and tok.strip():
                    return (body, url)
            except json.JSONDecodeError:
                pass
        time.sleep(poll)
    return last_pair


def wait_for_accesstoken_body(
    driver: webdriver.Chrome,
    timeout: float = 120.0,
    poll: float = 0.5,
) -> str | None:
    p = wait_for_accesstoken_pair(driver, timeout=timeout, poll=poll)
    return p[0] if p else None


def api_v1_base_from_token_request_url(url: str) -> str:
    u = urlparse(url)
    if not u.scheme or not u.netloc:
        return "https://demo.tradovateapi.com/v1"
    return f"{u.scheme}://{u.netloc}/v1"


def dismiss_common_overlays(driver: webdriver.Chrome) -> None:
    for text in ("Accept", "Agree", "OK", "Close", "Got it"):
        try:
            els = driver.find_elements(By.XPATH, f"//button[contains(normalize-space(.), '{text}')]")
            for el in els:
                if el.is_displayed():
                    t = (el.text or "").lower()
                    if "google" in t:
                        continue
                    el.click()
                    time.sleep(0.3)
                    break
        except Exception:
            continue


def _text_lower(el) -> str:
    try:
        return (el.text or el.get_attribute("innerText") or "").lower()
    except Exception:
        return ""


def _is_third_party_auth_control(el) -> bool:
    t = _text_lower(el)
    if any(x in t for x in ("google", "apple", "facebook", "microsoft", "github")):
        return True
    try:
        html = el.get_attribute("outerHTML") or ""
        h = html.lower()
        if "google" in h and ("google.com" in h or "g_id" in h or "googleusercontent" in h):
            return True
    except Exception:
        pass
    return False


def reveal_tradovate_email_password_login(driver: webdriver.Chrome, wait: WebDriverWait) -> None:
    needles = (
        "log in with email",
        "sign in with email",
        "email and password",
        "username and password",
        "use email",
        "continue with email",
        "tradovate login",
    )
    for _ in range(3):
        clicked = False
        for needle in needles:
            xpath = (
                "//*[self::button or self::a]["
                f"contains(translate(normalize-space(.), "
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{needle}')"
                "]"
            )
            for el in driver.find_elements(By.XPATH, xpath):
                if not el.is_displayed() or not el.is_enabled():
                    continue
                if _is_third_party_auth_control(el):
                    continue
                try:
                    el.click()
                    clicked = True
                    time.sleep(1.2)
                    break
                except Exception:
                    continue
            if clicked:
                break
        if not clicked:
            break


def _password_in_google_shell(el) -> bool:
    lc = "translate(@class, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
    lid = "translate(@id, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
    try:
        el.find_element(
            By.XPATH,
            f"./ancestor-or-self::*[contains({lc}, 'google') or contains({lid}, 'google')][1]",
        )
        return True
    except NoSuchElementException:
        return False


def pick_tradovate_password_field(driver: webdriver.Chrome, wait: WebDriverWait):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        candidates = driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]')
        scored: list[tuple[int, Any]] = []
        for el in candidates:
            try:
                if not el.is_displayed():
                    continue
                if _password_in_google_shell(el):
                    continue
                if not el.is_enabled():
                    continue
                rect = el.rect
                area = int(rect.get("width", 0) * rect.get("height", 0))
                scored.append((area, el))
            except Exception:
                continue
        scored.sort(key=lambda x: -x[0])
        for _area, el in scored:
            return el
        time.sleep(0.4)
    raise TimeoutException("No suitable password field (try email/password link on the page first).")


def find_username_in_same_form(password_el) -> Any:
    try:
        form = password_el.find_element(By.XPATH, "./ancestor::form[1]")
    except NoSuchElementException:
        form = password_el.find_element(By.XPATH, "./ancestor::div[position()<=6][1]")

    for css in (
        'input[type="email"]',
        'input[name="username"]',
        'input[name="name"]',
        'input[name="email"]',
        'input[autocomplete="username"]',
        'input[type="text"]',
    ):
        try:
            for cand in form.find_elements(By.CSS_SELECTOR, css):
                if cand.is_displayed() and cand != password_el:
                    t = (cand.get_attribute("type") or "").lower()
                    if t == "hidden":
                        continue
                    return cand
        except Exception:
            continue
    raise RuntimeError("Found password field but no username/email input in the same form.")


def submit_tradovate_login_form(password_el) -> None:
    try:
        form = password_el.find_element(By.XPATH, "./ancestor::form[1]")
    except NoSuchElementException:
        password_el.submit()
        return

    for inp in form.find_elements(By.CSS_SELECTOR, 'input[type="submit"], button[type="submit"]'):
        try:
            if inp.is_displayed() and inp.is_enabled() and not _is_third_party_auth_control(inp):
                inp.click()
                return
        except Exception:
            continue

    for btn in form.find_elements(By.TAG_NAME, "button"):
        try:
            if not btn.is_displayed() or not btn.is_enabled():
                continue
            if _is_third_party_auth_control(btn):
                continue
            t = (btn.text or "").strip().lower()
            if not t:
                continue
            if any(x in t for x in ("log in", "sign in", "login", "submit", "continue")):
                btn.click()
                return
        except Exception:
            continue

    password_el.submit()


def find_and_fill_login(driver: webdriver.Chrome, username: str, password: str) -> None:
    wait = WebDriverWait(driver, 35)
    reveal_tradovate_email_password_login(driver, wait)
    time.sleep(0.5)

    password_el = pick_tradovate_password_field(driver, wait)
    user_el = find_username_in_same_form(password_el)

    user_el.clear()
    user_el.send_keys(username)
    password_el.clear()
    password_el.send_keys(password)
    time.sleep(0.2)
    submit_tradovate_login_form(password_el)


def login_and_capture(
    username: str,
    password: str,
    *,
    headless: bool = True,
    start_url: str = START_URL,
    timeout: float = 120.0,
) -> tuple[dict[str, Any], str]:
    """
    Open trader, fill username/password (non-Google path), capture accesstokenrequest JSON.

    Returns (parsed_response_dict, request_url) for setting API base (demo vs live).
    """
    driver = build_driver(headless)
    try:
        driver.get(start_url)
        time.sleep(2)
        dismiss_common_overlays(driver)
        find_and_fill_login(driver, username, password)
        pair = wait_for_accesstoken_pair(driver, timeout=timeout)
        if not pair:
            raise RuntimeError(
                "Browser login did not produce an accesstokenresponse (try TRADOVATE_SELENIUM_HEADED=1, "
                "or increase timeout)."
            )
        body, request_url = pair
        data = json.loads(body)
        if not isinstance(data, dict):
            raise RuntimeError("accesstokenresponse was not a JSON object")
        tok = data.get("accessToken")
        if not isinstance(tok, str) or not tok.strip():
            raise RuntimeError("accesstokenresponse missing accessToken")
        return data, request_url
    finally:
        driver.quit()
