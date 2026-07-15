"""Inspect user/login light theme CSS structure for iOS26 port."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
out_lines: list[str] = []


def log(s: str = "") -> None:
    out_lines.append(s)


from m365_copilot_openai_proxy.template_user import _USER_HTML  # type: ignore
from m365_copilot_openai_proxy.template_login import _LOGIN_HTML  # type: ignore
from m365_copilot_openai_proxy.template_admin_css import _ADMIN_CSS

admin = _ADMIN_CSS
m = re.search(
    r'/\* iOS26 Liquid Glass light theme.*?body\[data-theme="light"\]\{[^}]+\}',
    admin,
    re.S,
)
log("=== ADMIN light token block ===")
log(m.group(0) if m else "MISSING")
log("\n=== ADMIN component marker present === " + str("iOS26 light — component overrides" in admin))

# Extract component override block
m2 = re.search(r"/\* iOS26 light — component overrides.*?$", admin, re.S)
if m2:
    log("\n=== ADMIN component block (first 2500) ===")
    log(m2.group(0)[:2500])

for name, html in [("USER", _USER_HTML), ("LOGIN", _LOGIN_HTML)]:
    log(f"\n\n######## {name} ########")
    log(f"len {len(html)}")
    styles = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I)
    log(f"style blocks {len(styles)} total css chars {sum(len(s) for s in styles)}")
    css = "\n".join(styles)
    Path(f"_tmp_{name.lower()}_css.txt").write_text(css, encoding="utf-8")
    lights = re.findall(r'body\[data-theme="light"\][^{]*\{[^}]*\}', css)
    log(f"light rules {len(lights)}")
    for i, r in enumerate(lights[:50]):
        log(f"  L{i}: {r[:200].replace(chr(10), ' ')}")
    for label, pat in [
        (":root", r":root\{[^}]+\}"),
        ("button", r"button\{[^}]+\}"),
        ("button:hover", r"button:hover\{[^}]+\}"),
        ("input:focus", r"input:focus[^{]*\{[^}]+\}"),
        ("fieldFlow", r"@keyframes fieldFlow\{[^}]+\}"),
        (".orb", r"\.orb\{[^}]+\}"),
        ("body::before", r"body::before\{[^}]+\}"),
        (".card::before", r"\.card::before\{[^}]+\}"),
        (".card", r"\.card\{[^}]+\}"),
        ("a color", r"a\{color:[^;]+;"),
        (".msg.ok", r"\.msg\.ok\{[^}]+\}"),
        (".msg.err", r"\.msg\.err\{[^}]+\}"),
        (".sidebar", r"\.sidebar\{[^}]+\}"),
        (".layout", r"\.layout\{[^}]+\}"),
        (".login-card", r"\.login-card\{[^}]+\}"),
        (".panel", r"\.panel\{[^}]+\}"),
        (".chip", r"\.chip\{[^}]+\}"),
        (".badge", r"\.badge\{[^}]+\}"),
        (".switch", r"\.switch[^{]*\{[^}]+\}"),
        ("glass-select light", r'body\[data-theme="light"\] \.glass-select[^{]*\{[^}]+\}'),
    ]:
        mm = re.search(pat, css)
        snippet = mm.group(0)[:180] if mm else "NOT FOUND"
        log(f"  {label}: {snippet}")
    old = []
    for c in lights:
        for tok in (
            "99,102,180",
            "96,180,242",
            "14,116,144",
            "0e7490",
            "243049",
            "5b6785",
            "96,242,255",
            "d6fbff",
        ):
            if tok in c:
                old.append((tok, c[:160]))
    log(f"  residual in light: {len(old)}")
    for t, c in old[:20]:
        log(f"   {t} -> {c}")

for f in [
    "src/m365_copilot_openai_proxy/template_user.py",
    "src/m365_copilot_openai_proxy/template_login.py",
]:
    raw = Path(f).read_text(encoding="utf-8")
    log(f"\n=== {f} structure ===")
    log(f"lines {raw.count(chr(10)) + 1} len {len(raw)}")
    # find :root and light blocks positions in source
    for needle in [':root{', 'data-theme="light"', 'body[data-theme="light"]', '_USER_HTML', '_LOGIN_HTML', '_GLASS']:
        idx = raw.find(needle)
        log(f"  find {needle!r} -> {idx}")
    # show first 60 lines briefly
    for i, line in enumerate(raw.splitlines()[:50], 1):
        if len(line) > 140:
            line = line[:140] + "..."
        log(f"{i:4d}|{line}")

Path("_tmp_inspect_out.txt").write_text("\n".join(out_lines), encoding="utf-8")
print("WROTE", len(out_lines), "lines")
