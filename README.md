<div align="center">

# 🌾 Kiro Farm Qingsan

**Automated Kiro (AWS Q Developer) Google OAuth token farm**

<p>
<img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+">
<img src="https://img.shields.io/badge/platform-macOS%20%7C%20Linux-lightgrey?style=flat-square" alt="macOS | Linux">
<img src="https://img.shields.io/badge/license-MIT-2ea44f?style=flat-square" alt="MIT License">
</p>

```
accounts.txt ──▶ Kiro sign-up ──▶ tokens.json ──▶ 9router
  email + pw     headless Chrom    access token    Kiro - Google
```

</div>

---

## ⚡ Quick start

```bash
# 1 — install
pip install -r requirements.txt
playwright install chromium

# 2 — add your accounts
cp accounts.txt.example accounts.txt

# 3 — run
python3 kiro.py
```

Tokens land in `tokens.json` and are pushed into 9router automatically.
Re-run the same command any time — finished accounts are skipped.

---

## 📝 Accounts file

Edit `accounts.txt` and pick whichever format fits.

| Format | File looks like | Use when |
|---|---|---|
| **Shared password** | `password: xxx` on line 1, then one email per line | every account uses the same password |
| **Per-account** | `email:password` on every line | each account has its own password |

```text
# shared password
password: my-secret-password
alice@gmail.com
bob@gmail.com
```

```text
# per-account
alice@gmail.com:password-a
bob@gmail.com:password-b
```

Lines starting with `#` and blank lines are ignored.

---

## 🚀 Run

```bash
python3 kiro.py
```

Reads `accounts.txt`, saves tokens to `tokens.json`, and injects them into
9router at `~/.9router/db/data.sqlite` as **Kiro - Google** providers.

---

## 🎛 Options

| Command | What it does |
|---|---|
| `python3 kiro.py` | Farm `accounts.txt`, save `tokens.json`, inject into 9router |
| `python3 kiro.py --no-inject` | Farm and save tokens only, skip 9router |
| `python3 kiro.py other.txt` | Use a different accounts file |
| `python3 kiro.py --headful` | Show the browser while it works (debugging) |
| `python3 inject.py` | Inject an existing `tokens.json` into 9router |

---

## 🩹 Troubleshooting

<details>
<summary><b>SSL: CERTIFICATE_VERIFY_FAILED</b></summary>

macOS's bundled Python ships without a working certificate list.

```bash
pip install certifi
```

`certifi` is already in `requirements.txt`, so this only happens when it was
never installed.
</details>

<details>
<summary><b>Every account says FAIL_NO_CODE</b></summary>

Google is showing a captcha or security check. Sign into that account by hand
in your normal browser once, clear the check, then run the farm again.
Brand-new accounts that never signed in from this machine are the most likely
to be blocked.
</details>

<details>
<summary><b>WARN: 9router DB not found</b></summary>

The default path `~/.9router/db/data.sqlite` does not exist on this machine.
Injection is skipped and tokens are still saved. Pass the real path if 9router
lives elsewhere:

```bash
python3 kiro.py --inject /path/to/data.sqlite
```
</details>

<details>
<summary><b>no accounts found / no accounts file</b></summary>

The file is empty, only has comments, or does not exist. Copy the example and
add real account lines:

```bash
cp accounts.txt.example accounts.txt
```
</details>

---

## 🔒 Keep it private

> [!WARNING]
> `accounts.txt` holds your passwords in plain text and `tokens.json` holds
> live tokens that can spend your quota. Do not share either file, do not put
> them in git, and do not leave them in a shared folder.

---

<div align="center">

## 📄 License

MIT

</div>
