from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
from m365_copilot_openai_proxy.template_user import _USER_HTML
from m365_copilot_openai_proxy.template_login import _LOGIN_HTML

out: list[str] = []


def log(s: str = "") -> None:
    out.append(s)


# USER: full light token block (first body[data-theme=light] that sets vars)
user_src = Path("src/m365_copilot_openai_proxy/template_user.py").read_text(encoding="utf-8")
login_src = Path("src/m365_copilot_openai_proxy/template_login.py").read_text(encoding="utf-8")

# line 15-16 area: dump first 2500 chars of style
style_start = user_src.find("<style>")
style_end = user_src.find("</style>")
css = user_src[style_start + 7 : style_end]
log("USER css len " + str(len(css)))
# first light rule full
m = re.search(r'body\[data-theme="light"\]\{[^}]+\}', css)
log("USER light tokens FULL:\n" + (m.group(0) if m else "NONE"))

# all light rules full
lights = re.findall(r'body\[data-theme="light"\][^{]*\{[^}]*\}', css)
log(f"\nUSER light count {len(lights)}")
for i, r in enumerate(lights):
    log(f"L{i}: {r}")

# button / focus / orb etc
for pat in [
    r"button\{[^}]+\}",
    r"button:hover\{[^}]+\}",
    r"input:focus,select:focus,textarea:focus\{[^}]+\}",
    r"input:focus\{[^}]+\}",
    r"#login-card input:focus\{[^}]+\}",
    r"#login-card input\{[^}]+\}",
    r"\.orb\{[^}]+\}",
    r"body::before\{[^}]+\}",
    r"\.card::before\{[^}]+\}",
    r"\.card:has\(details\[open\]\)::after\{[^}]+\}",
    r"details\[open\] summary\{[^}]+\}",
    r"h1\{[^}]+\}",
    r"html\{[^}]+\}",
    r"::-webkit-scrollbar-thumb\{[^}]+\}",
    r"\.qs-link\{[^}]+\}",
    r"\.pill\{[^}]+\}",
    r"\.account-side\{[^}]+\}",
    r"\.account-icon-btn-pass\{[^}]+\}",
    r"\.account-icon-btn-out\{[^}]+\}",
]:
    mm = re.search(pat, css)
    log(f"\n{pat[:40]} -> {(mm.group(0) if mm else 'NF')[:300]}")

# theme toggle in user
for needle in ["data-theme", "theme", "localStorage", "prefers-color"]:
    for m in re.finditer(needle, user_src):
        pass
log("\nUSER theme-related JS snippets:")
for m in re.finditer(r".{0,80}(theme|data-theme|prefers-color).{0,120}", user_src, re.I):
    s = m.group(0).replace("\n", " ")
    if len(s) > 200:
        s = s[:200]
    log("  " + s)

# LOGIN full CSS + theme
login_style = login_src[login_src.find("<style>") + 7 : login_src.find("</style>")]
log("\n\nLOGIN css len " + str(len(login_style)))
log(login_style[:3500])
log("\n... tail ...\n")
log(login_style[-800:])
log("\nLOGIN theme mentions:")
for m in re.finditer(r".{0,60}(theme|data-theme|prefers-color|localStorage).{0,100}", login_src, re.I):
    log("  " + m.group(0).replace("\n", " ")[:200])

# body tag attributes
for name, src in [("USER", user_src), ("LOGIN", login_src)]:
    bm = re.search(r"<body[^>]*>", src)
    log(f"\n{name} body tag: {bm.group(0) if bm else 'NF'}")

Path("_tmp_inspect2_out.txt").write_text("\n".join(out), encoding="utf-8")
print("ok", len(out))
