"""TTY-aware ANSI colors and quiet vs verbose (developer_mode) console output."""

from __future__ import annotations

import json
import sys
from typing import Any

from modules.client_config import developer_mode


def use_color() -> bool:
    return sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    if not use_color():
        return s
    return f"\033[{code}m{s}\033[0m"


def dim(s: str) -> str:
    return _c("2;37", s)


def ok(s: str) -> str:
    return _c("32", s)


def warn(s: str) -> str:
    return _c("33", s)


def err(s: str) -> str:
    return _c("31", s)


def info(s: str) -> str:
    return _c("36", s)


def bold(s: str) -> str:
    return _c("1", s)


def accent(s: str) -> str:
    return _c("96", s)


def magenta(s: str) -> str:
    return _c("35", s)


def tag_open(name: str) -> str:
    return f"{dim('[')}{accent(name)}{dim(']')}"


def summarize_response_body(text: str) -> str:
    if not text or not text.strip():
        return ""
    try:
        j = json.loads(text)
        if isinstance(j, dict):
            inner = j.get("d")
            if isinstance(inner, dict):
                for k in ("orderId", "errorText", "message", "s"):
                    if inner.get(k) is not None:
                        return f"{k}={inner.get(k)!r}"
            for k in ("orderId", "errorText", "error", "message"):
                if j.get(k) is not None:
                    return f"{k}={j.get(k)!r}"
        s = json.dumps(j, ensure_ascii=False, default=str)
        return s[:140] + ("…" if len(s) > 140 else "")
    except (json.JSONDecodeError, TypeError):
        one = text.strip().replace("\n", " ")
        return one[:120] + ("…" if len(one) > 120 else "")


def print_http_trace(label: str, status_code: int, text: str) -> None:
    """Full body when developer_mode; else one compact line."""
    if developer_mode():
        print(f"{dim('──')} {bold(label)} {dim(str(status_code))}")
        try:
            j = json.loads(text) if text else None
            if isinstance(j, (dict, list)):
                pretty = json.dumps(j, indent=2, ensure_ascii=False, default=str)
            else:
                pretty = text or ""
        except json.JSONDecodeError:
            pretty = text or ""
        for ln in pretty.splitlines():
            print(dim(ln))
        return

    sym = ok("✓") if 200 <= status_code < 300 else err("✗")
    tail = summarize_response_body(text)
    line = f"{sym} {accent(label)} {bold(str(status_code))}"
    if tail:
        line += f" {dim(tail)}"
    print(line)


def print_auth_payload(data: dict[str, Any]) -> None:
    if developer_mode():
        print(dim("── login payload"))
        print(dim(json.dumps(data, indent=2, ensure_ascii=False, default=str)))
        return
    exp = data.get("expirationTime")
    uid = data.get("userId")
    parts = [ok("✓"), accent("session"), bold("ready")]
    if uid is not None:
        parts.append(dim(f"· user {uid}"))
    if isinstance(exp, str) and exp.strip():
        parts.append(dim(f"· exp {exp.strip()}"))
    print(" ".join(parts))


def print_execute_result_bundle(result: dict[str, Any]) -> None:
    """Optional full ``_execute`` return value (developer_mode only); HTTP traces already printed per request."""
    if not developer_mode():
        return
    print(dim("── combined execute result"))
    print(dim(json.dumps(result, indent=2, ensure_ascii=False, default=str)))


def watch_line(level: str, msg: str) -> None:
    """Colored [watch] lines."""
    styles = {"ok": ok, "warn": warn, "err": err, "info": info}
    sty = styles.get(level, dim)
    print(f"{tag_open('watch')} {sty(msg)}")


def app_line(level: str, msg: str) -> None:
    styles = {"ok": ok, "warn": warn, "err": err, "info": info}
    sty = styles.get(level, dim)
    print(f"{tag_open('app')} {sty(msg)}")
