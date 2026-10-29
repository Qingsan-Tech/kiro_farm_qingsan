#!/usr/bin/env python3
"""Kiro Farm Qingsan — automated Kiro (AWS Q Developer) Google OAuth token farm.

Reads accounts, drives the Kiro OAuth device flow in headless Chromium,
captures the kiro:// callback code, exchanges it for an access token, saves
per-account tokens to tokens.json, and injects them into the 9router SQLite
DB (use --no-inject to skip the injection).

Usage:
    pip install -r requirements.txt
    playwright install chromium
    python3 kiro.py
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import sqlite3
import ssl
import sys
import urllib.parse
import urllib.request
import uuid

import certifi
from playwright.async_api import async_playwright

TOKEN_URL = "https://prod.us-east-1.auth.desktop.kiro.dev/oauth/token"
KIRO_LOGIN = "https://prod.us-east-1.auth.desktop.kiro.dev/login"
REDIRECT = "kiro://kiro.kiroAgent/authenticate-success"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def parse_accounts(path):
    """accounts.txt format:
         password: <shared-password>
         email1@domain.com
         email2@domain.com
    or, per-account:
         email1@domain.com:password1
         email2@domain.com:password2
    Returns (list_of_accounts, shared_password_or_None).
    """
    accounts = []
    shared_pw = None
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("="):
            continue
        low = line.lower()
        if low.startswith("pasword:") or low.startswith("password:"):
            shared_pw = line.split(":", 1)[1].strip()
            continue
        if ":" in line and "@" in line:
            email, _, pw = line.partition(":")
            accounts.append({"email": email.strip(), "password": pw.strip()})
        else:
            accounts.append({"email": line, "password": None})
    return accounts, shared_pw


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------

def pkce():
    verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode()
    return verifier, challenge, state


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------

def exchange(code, verifier):
    body = json.dumps({
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body,
        headers={"Content-Type": "application/json", "User-Agent": UA},
    )
    # macOS python3 ships no CA bundle; certifi supplies one.
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Browser login
# ---------------------------------------------------------------------------

async def login_one(page, account, password):
    """Drive Kiro Google OAuth for one account. Returns (code, verifier) or (None, None)."""
    verifier, challenge, state = pkce()
    redirect_uri = urllib.parse.quote(REDIRECT, safe="")
    login_url = (
        f"{KIRO_LOGIN}?idp=Google&redirect_uri={redirect_uri}"
        f"&code_challenge={challenge}&code_challenge_method=S256"
        f"&state={state}&prompt=select_account"
    )

    captured = {"code": None}

    def on_request(req):
        if req.url.startswith("kiro://"):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(req.url).query)
            captured["code"] = qs.get("code", [None])[0]

    page.on("request", on_request)

    # 1. Kiro login
    await page.goto(login_url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_timeout(4000)

    # 2. Google login
    if "accounts.google.com" in page.url:
        await page.fill('input[name="identifier"]', account["email"], timeout=15000)
        await page.click("#identifierNext", timeout=10000)
        await page.wait_for_timeout(3500)
        pw = page.locator(
            'input[type="password"]:not([aria-hidden="true"]):not([name="hiddenPassword"])'
        )
        await pw.fill(password, timeout=10000)
        await page.click("#passwordNext", timeout=10000)
        await page.wait_for_timeout(6000)
        
        # Handle post-password screens (fresh accounts often need extra clicks)
        for _ in range(5):
            if "accounts.google.com" not in page.url:
                break
            cur = page.url
            # Skip if already on consent/oauth page (check path, not query params)
            url_path = cur.split('?')[0]
            if "/oauth/v3/consent" in url_path or "/consent" in url_path:
                break
            try:
                # Scroll down gradually to enable buttons (e.g., ToS/welcome pages)
                for scroll_step in range(3):
                    await page.evaluate("window.scrollBy(0, window.innerHeight)")
                    await page.wait_for_timeout(800)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)
                
                btns = await page.query_selector_all('button, div[role="button"]')
                clicked = False
                for b in btns:
                    try:
                        t = (await b.inner_text() or "").strip().lower()
                    except Exception:
                        continue
                    # Common post-password button texts
                    if t in ("next", "continue", "skip", "not now", "confirm", "i understand", "berikutnya", "lewati", "下一步", "确认"):
                        if await b.is_visible():
                            try:
                                await b.scroll_into_view_if_needed()
                                await page.wait_for_timeout(500)
                                await b.click(timeout=5000)
                                clicked = True
                                await page.wait_for_timeout(3000)
                                break
                            except Exception:
                                continue
                if not clicked:
                    break
            except Exception:
                break

    # 3. Consent + wait for kiro:// code
    for _ in range(30):
        if captured["code"]:
            break
        cur = page.url
        if "accounts.google.com" in cur and ("consent" in cur or "oauth" in cur):
            try:
                btns = await page.query_selector_all('button, div[role="button"]')
                for b in btns:
                    try:
                        t = (await b.inner_text() or "").strip().lower()
                    except Exception:
                        continue
                    if t in ("continue", "accept", "allow", "同意", "lanjut", "lanjutkan", "ok"):
                        if await b.is_visible():
                            await b.click()
                            break
            except Exception:
                pass
        if "challenge" in cur or "captcha" in cur:
            print(f"    !! Google challenge/captcha detected for {account['email']}, skip")
            return None, None
        await page.wait_for_timeout(2000)

    page.remove_listener("request", on_request)
    return captured["code"], verifier


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def load_existing(out_path):
    if os.path.exists(out_path):
        try:
            return json.load(open(out_path))
        except Exception:
            return {}
    return {}


def save_tokens(out_path, tokens):
    with open(out_path, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"  saved {len(tokens)} tokens -> {out_path}")


def inject_9router(db_path, email, tok):
    """Optionally write a token into a 9router providerConnections table."""
    from datetime import datetime, timedelta, timezone
    db_path = os.path.expanduser(db_path)
    if not os.path.exists(db_path):
        print(f"  !! DB not found: {db_path}, skip inject")
        return
    expires = (datetime.now(timezone.utc) + timedelta(seconds=tok.get("expiresIn", 3600))).isoformat()
    data = {
        "accessToken": tok.get("accessToken"),
        "refreshToken": tok.get("refreshToken", ""),
        "expiresAt": expires,
        "providerSpecificData": {
            "profileArn": tok.get("profileArn"),
            "authMethod": "google",
            "provider": "Google",
        },
        "testStatus": "active",
    }
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    exists = con.execute(
        "SELECT 1 FROM providerConnections WHERE provider='kiro' AND email=? LIMIT 1",
        (email,),
    ).fetchone()
    if exists:
        print(f"  SKIP inject {email} (already in DB)")
        con.close()
        return
    con.execute(
        "INSERT INTO providerConnections (id, provider, authType, name, email, priority, isActive, data, createdAt, updatedAt)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), "kiro", "oauth", "Kiro - Google", email, 1, 1,
         json.dumps(data), now, now),
    )
    con.commit()
    con.close()
    print(f"  INJECTED {email} -> 9router DB")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BANNER = r"""
|  /   |||||  |||||   ||||   |||||   ||||   |||||  |\  /|
| /    |||   ||   | ||  ||   ||     ||  || ||   | | \/ |
|/     |||   |||||  ||  ||   |||||  |||||| |||||  |    |
|\     |||   ||  \  ||  ||   ||     ||  || ||  \  |    |
| \    |||||  ||   \  ||||   ||     ||  || ||   \ |    |

 ||||\ |||||  ||  ||  ||||   ||||   ||||   ||  ||
||  ||  |||   ||| || ||     ||     ||  || ||| ||
||  ||  |||   |||| | || |||  |||   |||||| |||| |
||  ||  |||   || ||| ||  ||     || ||  || || |||
 ||||\ |||||  ||  ||  ||||   ||||   ||  || ||  ||

        Kiro (AWS Q Developer) Google OAuth token farm
"""


async def main():
    print(BANNER, flush=True)
    ap = argparse.ArgumentParser(description="Kiro (AWS Q Developer) token farm")
    ap.add_argument("accounts", nargs="?", default="accounts.txt",
                    help="accounts file (default: accounts.txt)")
    ap.add_argument("--out", default="tokens.json", help="output JSON file")
    ap.add_argument("--inject", metavar="DB",
                    default=os.path.expanduser("~/.9router/db/data.sqlite"),
                    help="9router data.sqlite path (default: ~/.9router/db/data.sqlite)")
    ap.add_argument("--no-inject", action="store_true", help="skip 9router injection")
    ap.add_argument("--headful", action="store_true", help="run browser visible (debug)")
    args = ap.parse_args()

    db_path = None if args.no_inject else args.inject
    if db_path and not os.path.exists(db_path):
        print(f"WARN: 9router DB not found: {db_path} -- injection skipped")
        db_path = None

    if not os.path.exists(args.accounts):
        print(f"no accounts file: {args.accounts} (copy accounts.txt.example)")
        sys.exit(1)

    accounts, shared_pw = parse_accounts(args.accounts)
    for a in accounts:
        if a["password"] is None:
            a["password"] = shared_pw
    if not accounts:
        print("no accounts found in", args.accounts)
        sys.exit(1)

    tokens = load_existing(args.out)
    todo = [a for a in accounts if a["email"] not in tokens]
    print(f"accounts: {len(accounts)}, already have token: {len(accounts) - len(todo)}, todo: {len(todo)}")

    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not args.headful, args=["--no-sandbox"])
        for i, acc in enumerate(todo):
            email = acc["email"]
            print(f"\n[{i + 1}/{len(todo)}] {email}")
            ctx = await browser.new_context(user_agent=UA)
            page = await ctx.new_page()
            try:
                code, verifier = await login_one(page, acc, acc["password"])
                if not code:
                    print(f"  FAIL: no code for {email}")
                    results.append({"email": email, "status": "FAIL_NO_CODE"})
                    continue
                tok = exchange(code, verifier)
                tok["email"] = email
                tokens[email] = tok
                save_tokens(args.out, tokens)
                if db_path:
                    inject_9router(db_path, email, tok)
                print(f"  OK: arn={tok.get('profileArn', '')[:40]}")
                results.append({"email": email, "status": "OK"})
            except Exception as e:
                print(f"  ERROR {email}: {e}")
                results.append({"email": email, "status": f"ERR {e}"})
            finally:
                await ctx.close()
            await asyncio.sleep(3)

        await browser.close()

    ok = [r for r in results if r["status"] == "OK"]
    print(f"\n=== SUMMARY: {len(ok)}/{len(todo)} OK ===")
    for r in results:
        print(f"  {r['email']}: {r['status']}")


if __name__ == "__main__":
    asyncio.run(main())
