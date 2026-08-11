#!/usr/bin/env python3
"""Sign in without a person, by driving `zad login` instead of going around it.

The browser flow already works: `zad login` starts a listener on 127.0.0.1, prints the
Keycloak URL and waits for the callback. All that is missing in an automated run is
somebody to open that URL and type a password, and that is exactly what a headless browser
is for.

Deliberately not a second implementation of the login: the token this stores is the one
`zad login` obtained, through the same flow, with the same audience check. A script that
talked to Keycloak itself would be testing its own code path rather than the CLI's.

Usage:
    uv run python docs/playbooks/login-headless.py            # admin / admin1234
    ZAD_LOGIN_USER=x ZAD_LOGIN_PASSWORD=y uv run python ... [--zad /path/to/zad]

Needs: playwright with chromium (`playwright install chromium`).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading

URL_RE = re.compile(r"(https://\S+/protocol/openid-connect/auth\?\S+)")


def _read_url(process: subprocess.Popen, out: list[str], found: threading.Event) -> None:
    """Collect the CLI's output, and signal as soon as the sign-in URL appears."""
    assert process.stderr is not None
    for line in process.stderr:
        out.append(line)
        # The URL is wrapped across lines by the console, so match on the accumulated text.
        if not found.is_set() and URL_RE.search("".join(out).replace("\n", "")):
            found.set()
    found.set()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zad", default=os.environ.get("ZAD", "zad"), help="How to invoke the CLI")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    user = os.environ.get("ZAD_LOGIN_USER", "admin")
    password = os.environ.get("ZAD_LOGIN_PASSWORD", "admin1234")

    # --no-open: this script is the browser. --browser forces the loopback flow, because
    # the device flow needs a code typed somewhere and there is nobody to type it.
    process = subprocess.Popen(
        [*args.zad.split(), "login", "--no-open", "--browser"],
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    collected: list[str] = []
    found = threading.Event()
    threading.Thread(target=_read_url, args=(process, collected, found), daemon=True).start()

    if not found.wait(timeout=30):
        process.kill()
        print("zad login printed no sign-in URL", file=sys.stderr)
        return 2

    match = URL_RE.search("".join(collected).replace("\n", ""))
    if not match:
        process.kill()
        print("".join(collected), file=sys.stderr)
        return 2
    url = match.group(1)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        # domcontentloaded, not the default "load": the sign-in page keeps a request open,
        # so waiting for every resource times out on a page that is long since usable.
        page.goto(url, wait_until="domcontentloaded")
        # The realm offers an identity provider as well as a username form; the form is the
        # one that can be filled without a second account somewhere else.
        page.fill("#username", user)
        page.fill("#password", password)
        page.click("#kc-login")
        # The callback goes to the CLI's listener, so the page ends up on 127.0.0.1.
        page.wait_for_url(re.compile(r"127\.0\.0\.1"), timeout=30_000)
        browser.close()

    try:
        process.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        print("zad login did not finish after the callback", file=sys.stderr)
        return 2

    sys.stderr.write("".join(collected))
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
