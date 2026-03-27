#!/usr/bin/env python3
"""
CLI wrapper: same Selenium login + accesstoken capture as ``modules.auth.Auth`` / ``tradovate_selenium_login``.

  pip install selenium
  python enable.py              # headless by default
  python enable.py --headed     # visible browser (debug)
"""

from __future__ import annotations

import argparse
import getpass
import sys
import time

from modules.client_config import developer_mode
from modules.console_theme import accent, bold, dim, err, ok, print_http_trace
from modules.tradovate_selenium_login import (
    START_URL,
    build_driver,
    dismiss_common_overlays,
    find_and_fill_login,
    wait_for_accesstoken_body,
)


def _print_timings(t_wall_start: float, t_auto_start: float | None) -> None:
    wall = time.perf_counter() - t_wall_start
    print(
        f"\n{dim('Time:')} {accent('wall')} {bold(f'{wall:.2f}s')} {dim('(includes prompts)')}",
        flush=True,
    )
    if t_auto_start is not None:
        auto = time.perf_counter() - t_auto_start
        print(
            f"{dim('Time:')} {accent('automation')} {bold(f'{auto:.2f}s')} {dim('(Chrome → token capture)')}",
            flush=True,
        )


def main() -> int:
    p = argparse.ArgumentParser(description="Tradovate web login + capture accesstokenrequest response body")
    p.add_argument("--url", default=START_URL, help="Open this URL first (default: trader home)")
    p.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (default: headless)",
    )
    p.add_argument("--timeout", type=float, default=120.0, help="Seconds to wait for token response after submit")
    p.add_argument(
        "--no-wait",
        action="store_true",
        help="With --headed, skip Enter before closing (headless never pauses)",
    )
    p.add_argument(
        "--wait-enter",
        action="store_true",
        help="With --headed, always pause for Enter before closing (overrides --no-wait)",
    )
    args = p.parse_args()

    headless = not args.headed
    pause_before_close = args.headed and (args.wait_enter or not args.no_wait)
    if headless:
        pause_before_close = False

    t_wall = time.perf_counter()

    user = input("Tradovate username: ").strip()
    if not user:
        print("Username required.", file=sys.stderr)
        _print_timings(t_wall, None)
        return 1
    pwd = getpass.getpass("Tradovate password: ")
    if not pwd:
        print("Password required.", file=sys.stderr)
        _print_timings(t_wall, None)
        return 1

    driver = None
    t_auto: float | None = None
    try:
        mode = "headless" if headless else "headed"
        print(
            f"{ok('▸')} {accent('Chrome')} {dim(mode)} {dim('· network capture on')}",
            flush=True,
        )
        t_auto = time.perf_counter()
        driver = build_driver(headless)
        driver.get(args.url)
        time.sleep(2)
        dismiss_common_overlays(driver)

        print(
            f"{dim('→')} {accent('Login')} {dim('email/password path (skipping Google SSO)')}",
            flush=True,
        )
        find_and_fill_login(driver, user, pwd)

        print(
            f"{dim('…')} {accent('Waiting')} {dim('for /auth/accesstokenrequest …')}",
            flush=True,
        )
        body = wait_for_accesstoken_body(driver, timeout=args.timeout)
        if not body:
            print(
                "No accesstoken response captured. Try --headed if the site blocks headless, "
                "or extend --timeout.",
                file=sys.stderr,
            )
            _print_timings(t_wall, t_auto)
            return 2

        if developer_mode():
            print_http_trace("accesstokenrequest", 200, body)
        else:
            print(
                f"{ok('✓')} {accent('Token captured')} {dim('— set')} "
                f"{accent('developer_mode')} {dim(': true in assets/config.json for full JSON')}",
                flush=True,
            )
        _print_timings(t_wall, t_auto)
        return 0
    except Exception as e:
        print(f"{err('✗')} {e}", file=sys.stderr)
        _print_timings(t_wall, t_auto)
        return 1
    finally:
        if driver is not None:
            if pause_before_close:
                try:
                    input("\nPress Enter to close the browser...")
                except EOFError:
                    pass
            driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
