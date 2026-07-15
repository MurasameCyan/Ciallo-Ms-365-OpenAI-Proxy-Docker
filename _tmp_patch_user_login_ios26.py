"""Port iOS26 light theme to user + login pages. Dark theme untouched."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
USER = ROOT / "src/m365_copilot_openai_proxy/template_user.py"
LOGIN = ROOT / "src/m365_copilot_openai_proxy/template_login.py"

# --- USER: replace light token block with admin-aligned iOS26 tokens ---
USER_OLD_TOKENS = (
    'body[data-theme="light"]{--muted:#5b6785;--line:rgba(99,102,180,.22);--strong:#243049;--faint:#7581a3;'
    '--inner:rgba(255,255,255,.72);--inner-border:rgba(99,102,180,.22);--text:#1f2740;'
    '--card:linear-gradient(180deg,rgba(255,255,255,.9),rgba(244,247,253,.84));'
    '--bg:radial-gradient(circle at 18% 12%,rgba(96,180,242,.16),transparent 28%),'
    'radial-gradient(circle at 84% 10%,rgba(140,107,255,.14),transparent 26%),'
    'radial-gradient(circle at 50% 92%,rgba(255,150,220,.12),transparent 28%),'
    'linear-gradient(135deg,#edf3fb 0%,#e4ebf6 48%,#eef2f8 100%);'
    '--chip:rgba(99,102,180,.08);--chip-border:rgba(99,102,180,.22)}'
)

USER_NEW_TOKENS = (
    '/* iOS26 Liquid Glass light theme — aligned with admin; dark :root untouched */\n'
    'body[data-theme="light"]{\n'
    '--cyan:#007aff;--violet:#5856d6;--pink:#ff2d55;--gold:#ff9f0a;\n'
    '--muted:#6b6b70;--line:rgba(60,60,67,.12);\n'
    '--bg:radial-gradient(circle at 16% 10%,rgba(0,122,255,.05),transparent 30%),'
    'radial-gradient(circle at 84% 8%,rgba(88,86,214,.04),transparent 28%),'
    'radial-gradient(circle at 50% 92%,rgba(0,0,0,.02),transparent 32%),'
    'linear-gradient(160deg,#f2f3f7 0%,#e9ebf0 48%,#f4f5f8 100%);\n'
    '--text:#1c1c1e;--card:linear-gradient(180deg,rgba(255,255,255,.72),rgba(255,255,255,.52));'
    '--strong:#000000;--faint:#8e8e93;\n'
    '--inner:rgba(255,255,255,.62);--inner-border:rgba(120,120,128,.18);'
    '--chip:rgba(120,120,128,.1);--chip-border:rgba(120,120,128,.16);'
    '--shadow:0 8px 28px rgba(0,0,0,.07);'
    '--h1grad:linear-gradient(135deg,#1d1d1f,#3a3a3c 70%,#636366)}\n'
)

USER_REPLACEMENTS: list[tuple[str, str]] = [
    (USER_OLD_TOKENS, USER_NEW_TOKENS),
    (
        'body[data-theme="light"] .modal-card{background:rgba(255,255,255,.3);border-color:rgba(99,102,180,.22)}',
        'body[data-theme="light"] .modal-card{background:rgba(255,255,255,.72);border-color:rgba(60,60,67,.12);box-shadow:0 16px 40px rgba(0,0,0,.1);backdrop-filter:blur(28px) saturate(160%)}',
    ),
    (
        'body[data-theme="light"] .account-main select option{background:#fff;color:#243049}',
        'body[data-theme="light"] .account-main select option{background:#fff;color:#1c1c1e}',
    ),
    (
        'body[data-theme="light"] .qs-link{color:#0e7490;border-color:rgba(14,116,144,.3);background:linear-gradient(135deg,rgba(14,116,144,.1),rgba(124,58,237,.1))}',
        'body[data-theme="light"] .qs-link{color:#007aff;border-color:rgba(0,122,255,.22);background:linear-gradient(135deg,rgba(0,122,255,.08),rgba(88,86,214,.06))}',
    ),
    (
        'body[data-theme="light"] .hint,body[data-theme="light"] label,body[data-theme="light"] .call-param-row,body[data-theme="light"] .status-line{color:#4b5878}',
        'body[data-theme="light"] .hint,body[data-theme="light"] label,body[data-theme="light"] .call-param-row,body[data-theme="light"] .status-line{color:#6b6b70}',
    ),
    (
        'body[data-theme="light"] code,body[data-theme="light"] .call-param-row code{color:#4f46e5}',
        'body[data-theme="light"] code,body[data-theme="light"] .call-param-row code{color:#5856d6}',
    ),
    (
        'body[data-theme="light"] .pill{background:rgba(99,102,180,.12);color:#334155}',
        'body[data-theme="light"] .pill{background:rgba(120,120,128,.12);color:#3a3a3c}',
    ),
    (
        'body[data-theme="light"] .account-side{background:linear-gradient(180deg,rgba(255,255,255,.72),rgba(240,245,255,.62));border-color:rgba(99,102,180,.24);box-shadow:inset 0 1px 0 rgba(255,255,255,.86),0 12px 32px rgba(80,100,160,.12)}',
        'body[data-theme="light"] .account-side{background:linear-gradient(180deg,rgba(255,255,255,.78),rgba(242,243,247,.62));border-color:rgba(60,60,67,.12);box-shadow:inset 0 1px 0 rgba(255,255,255,.9),0 10px 28px rgba(0,0,0,.05)}',
    ),
    (
        'body[data-theme="light"] .status-line,body[data-theme="light"] .status-line:first-child{border-color:rgba(99,102,180,.18)}',
        'body[data-theme="light"] .status-line,body[data-theme="light"] .status-line:first-child{border-color:rgba(60,60,67,.12)}',
    ),
]

# User-specific iOS26 component overrides (no admin-only selectors).
USER_IOS26_BLOCK = r'''
/* iOS26 light — component overrides (user page; dark base rules untouched) */
body[data-theme="light"]{scrollbar-color:rgba(0,122,255,.28) rgba(120,120,128,.08)}
body[data-theme="light"]::-webkit-scrollbar-track{background:rgba(120,120,128,.08)}
body[data-theme="light"]::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(0,122,255,.4),rgba(88,86,214,.32));border-color:rgba(255,255,255,.5)}
body[data-theme="light"]::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,rgba(0,122,255,.55),rgba(88,86,214,.42))}
body[data-theme="light"]::before{background:linear-gradient(rgba(60,60,67,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(60,60,67,.05) 1px,transparent 1px);background-size:44px 44px;opacity:.55}
body[data-theme="light"] .orb{opacity:.1;filter:blur(28px);background:conic-gradient(from 160deg,rgba(0,122,255,.55),rgba(88,86,214,.45),rgba(255,45,85,.28),rgba(0,122,255,.55))}
body[data-theme="light"] h1{background:var(--h1grad);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
body[data-theme="light"] .card{border-radius:22px;backdrop-filter:blur(28px) saturate(160%);-webkit-backdrop-filter:blur(28px) saturate(160%);box-shadow:var(--shadow)}
body[data-theme="light"] .card::before{background:linear-gradient(135deg,rgba(255,255,255,.75),transparent 42%,rgba(0,122,255,.12),rgba(88,86,214,.08));opacity:.55}
body[data-theme="light"] .card:has(details[open])::after{background:linear-gradient(90deg,transparent,rgba(0,122,255,.45),rgba(88,86,214,.28),transparent);animation:none;opacity:.7}
body[data-theme="light"] details[open] summary{background:linear-gradient(135deg,rgba(0,122,255,.05),rgba(88,86,214,.04))}
body[data-theme="light"] button{color:#fff;background:linear-gradient(180deg,#0a84ff 0%,#007aff 100%);box-shadow:0 4px 14px rgba(0,122,255,.28),inset 0 1px 0 rgba(255,255,255,.28);text-shadow:none;border-radius:12px;font-weight:700}
body[data-theme="light"] button:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,122,255,.32),inset 0 1px 0 rgba(255,255,255,.32)}
body[data-theme="light"] button:active{transform:translateY(0);filter:brightness(.96)}
body[data-theme="light"] .btn-ghost,body[data-theme="light"] button.btn-ghost{color:#1c1c1e!important;background:rgba(120,120,128,.12)!important;border:1px solid rgba(60,60,67,.12)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.7)!important}
body[data-theme="light"] input:focus,body[data-theme="light"] select:focus,body[data-theme="light"] textarea:focus{border:1px solid rgba(0,122,255,.45)!important;background-image:none!important;background:var(--inner)!important;box-shadow:0 0 0 4px rgba(0,122,255,.14)!important;animation:none!important;outline:none}
body[data-theme="light"] #login-card input{background:rgba(255,255,255,.72)!important;border:1px solid rgba(60,60,67,.14)!important;-webkit-text-fill-color:#1c1c1e;-webkit-box-shadow:0 0 0 1000px rgba(255,255,255,.72) inset;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}
body[data-theme="light"] #login-card input:focus{border:1px solid rgba(0,122,255,.45)!important;background-image:none!important;background:rgba(255,255,255,.86)!important;-webkit-box-shadow:0 0 0 1000px rgba(255,255,255,.86) inset,0 0 0 4px rgba(0,122,255,.14)!important;box-shadow:0 0 0 4px rgba(0,122,255,.14)!important;animation:none!important}
body[data-theme="light"] a{color:#007aff}
body[data-theme="light"] .glass-select.open .glass-select-trigger{border-color:rgba(0,122,255,.4)!important;box-shadow:0 0 0 3px rgba(0,122,255,.12),0 4px 14px rgba(0,0,0,.05)!important}
body[data-theme="light"] .glass-select-menu:before{background:linear-gradient(90deg,rgba(0,122,255,.35),rgba(88,86,214,.25),rgba(0,122,255,.35));animation:none;opacity:.45}
body[data-theme="light"] .glass-select-option:hover{background:rgba(0,122,255,.08)!important;color:#1c1c1e!important}
body[data-theme="light"] .glass-select-option.active{color:#007aff!important;background:rgba(0,122,255,.12)!important;box-shadow:inset 3px 0 0 #007aff!important}
'''

# --- LOGIN: add light theme (follows admin_theme); dark CSS unchanged ---
LOGIN_IOS26_BLOCK = r'''
/* iOS26 light — admin login follows localStorage admin_theme; dark defaults untouched */
body[data-theme="light"]{--cyan:#007aff;--violet:#5856d6;--pink:#ff2d55;--gold:#ff9f0a;--text:#1c1c1e;--muted:#6b6b70;--line:rgba(60,60,67,.12);--strong:#000000;--faint:#8e8e93;--inner:rgba(255,255,255,.72);scrollbar-color:rgba(0,122,255,.28) rgba(120,120,128,.08);background:radial-gradient(circle at 16% 10%,rgba(0,122,255,.05),transparent 30%),radial-gradient(circle at 84% 8%,rgba(88,86,214,.04),transparent 28%),radial-gradient(circle at 50% 92%,rgba(0,0,0,.02),transparent 32%),linear-gradient(160deg,#f2f3f7 0%,#e9ebf0 48%,#f4f5f8 100%)}
body[data-theme="light"]::before{background:linear-gradient(rgba(60,60,67,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(60,60,67,.05) 1px,transparent 1px);background-size:44px 44px;opacity:.55}
body[data-theme="light"] .orb{opacity:.1;filter:blur(28px);background:conic-gradient(from 160deg,rgba(0,122,255,.55),rgba(88,86,214,.45),rgba(255,45,85,.28),rgba(0,122,255,.55))}
body[data-theme="light"] .login-box{background:linear-gradient(180deg,rgba(255,255,255,.78),rgba(255,255,255,.58));border-color:rgba(60,60,67,.12);box-shadow:0 16px 40px rgba(0,0,0,.08);backdrop-filter:blur(28px) saturate(160%);-webkit-backdrop-filter:blur(28px) saturate(160%)}
body[data-theme="light"] .login-box::before{background:linear-gradient(135deg,rgba(255,255,255,.8),transparent 42%,rgba(0,122,255,.14),rgba(88,86,214,.1));opacity:.55}
body[data-theme="light"] .brand-mark{background:linear-gradient(135deg,#0a84ff,#007aff);box-shadow:0 4px 18px rgba(0,122,255,.28),inset 0 1px 0 rgba(255,255,255,.35)}
body[data-theme="light"] .login-box h1{background:linear-gradient(135deg,#1d1d1f,#3a3a3c 70%,#636366);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
body[data-theme="light"] input{background:rgba(255,255,255,.72);border:1px solid rgba(60,60,67,.14);color:#1c1c1e;-webkit-text-fill-color:#1c1c1e;box-shadow:inset 0 1px 0 rgba(255,255,255,.9)}
body[data-theme="light"] input:focus{border:1px solid rgba(0,122,255,.45);background-image:none;background:rgba(255,255,255,.86);box-shadow:0 0 0 4px rgba(0,122,255,.14);animation:none}
body[data-theme="light"] input:-webkit-autofill,body[data-theme="light"] input:-webkit-autofill:focus,body[data-theme="light"] input:-webkit-autofill:hover{-webkit-text-fill-color:#1c1c1e!important;box-shadow:0 0 0 1000px rgba(255,255,255,.86) inset!important}
body[data-theme="light"] button{color:#fff;background:linear-gradient(180deg,#0a84ff 0%,#007aff 100%);box-shadow:0 4px 14px rgba(0,122,255,.28),inset 0 1px 0 rgba(255,255,255,.28)}
body[data-theme="light"] button:hover{transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,122,255,.32),inset 0 1px 0 rgba(255,255,255,.32)}
body[data-theme="light"] .lang-btn{background:rgba(120,120,128,.12);border-color:rgba(60,60,67,.14);color:#1c1c1e;box-shadow:none}
body[data-theme="light"] .msg.err{background:rgba(254,226,226,.85);color:#b91c1c;border-color:rgba(239,68,68,.35)}
body[data-theme="light"]::-webkit-scrollbar-track{background:rgba(120,120,128,.08)}
body[data-theme="light"]::-webkit-scrollbar-thumb{background:linear-gradient(180deg,rgba(0,122,255,.4),rgba(88,86,214,.32));border-color:rgba(255,255,255,.5)}
'''

LOGIN_THEME_JS = r'''
function applyTheme(){
  const th=localStorage.getItem('admin_theme')||'dark';
  document.body.setAttribute('data-theme',th);
}
applyTheme();
'''


def apply_pairs(path: Path, pairs: list[tuple[str, str]]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    log: list[str] = []
    for old, new in pairs:
        n = text.count(old)
        if n == 0:
            log.append(f"MISS {path.name}: {old[:90]}...")
            continue
        text = text.replace(old, new)
        log.append(f"OK({n}) {path.name}: {old[:70]}...")
    path.write_text(text, encoding="utf-8")
    return log


def insert_before_closing_style(path: Path, block: str, marker: str) -> str:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return f"BLOCK already in {path.name}"
    # Insert before first </style> (main page stylesheet)
    idx = text.find("</style>")
    if idx < 0:
        raise SystemExit(f"no </style> in {path}")
    text = text[:idx] + "\n" + block + text[idx:]
    path.write_text(text, encoding="utf-8")
    return f"BLOCK inserted before </style> in {path.name}"


def patch_login_theme_js() -> str:
    text = LOGIN.read_text(encoding="utf-8")
    if "admin_theme" in text and "function applyTheme" in text:
        return "LOGIN theme JS already present"
    # Insert applyTheme just before applyLang(); or after lang init
    needle = "applyLang();\nasync function doLogin()"
    if needle not in text:
        # try alternate
        needle2 = "applyLang();"
        if needle2 not in text:
            return "MISS login applyLang injection point"
        text = text.replace(needle2, LOGIN_THEME_JS + "applyLang();", 1)
    else:
        text = text.replace(needle, LOGIN_THEME_JS + "applyLang();\nasync function doLogin()", 1)
    LOGIN.write_text(text, encoding="utf-8")
    return "LOGIN theme JS injected"


def main() -> None:
    logs: list[str] = []
    logs.extend(apply_pairs(USER, USER_REPLACEMENTS))
    logs.append(insert_before_closing_style(USER, USER_IOS26_BLOCK, "iOS26 light — component overrides (user page"))
    logs.append(insert_before_closing_style(LOGIN, LOGIN_IOS26_BLOCK, "iOS26 light — admin login"))
    logs.append(patch_login_theme_js())

    # verify
    import re
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    # reimport fresh
    for mod in list(sys.modules):
        if mod.startswith("m365_copilot_openai_proxy"):
            del sys.modules[mod]
    from m365_copilot_openai_proxy.template_user import _USER_HTML
    from m365_copilot_openai_proxy.template_login import _LOGIN_HTML

    u_styles = re.findall(r"<style[^>]*>(.*?)</style>", _USER_HTML, re.S | re.I)
    u_css = "\n".join(u_styles)
    l_styles = re.findall(r"<style[^>]*>(.*?)</style>", _LOGIN_HTML, re.S | re.I)
    l_css = "\n".join(l_styles)

    def light_residuals(css: str) -> list[str]:
        hits = []
        for chunk in re.findall(r'body\[data-theme="light"\][^{]*\{[^}]*\}', css):
            for tok in ("99,102,180", "96,180,242", "14,116,144", "#0e7490", "#243049", "#5b6785", "#d6fbff"):
                if tok in chunk:
                    hits.append(f"{tok} in {chunk[:100]}")
        return hits

    checks = {
        "user_tokens_ios": "--cyan:#007aff" in u_css and 'body[data-theme="light"]' in u_css,
        "user_btn_blue": "linear-gradient(180deg,#0a84ff 0%,#007aff 100%)" in u_css,
        "user_block": "iOS26 light — component overrides (user page" in u_css,
        "user_residuals": light_residuals(u_css),
        "login_block": "iOS26 light — admin login" in l_css,
        "login_btn_blue": 'body[data-theme="light"] button{color:#fff' in l_css,
        "login_theme_js": "admin_theme" in _LOGIN_HTML and "function applyTheme" in _LOGIN_HTML,
        "login_dark_root_untouched": ":root{--cyan:#60f2ff" in l_css,
        "user_dark_root_untouched": ":root{--cyan:#60f2ff" in u_css,
    }
    Path("_tmp_patch_user_login_log.txt").write_text(
        "\n".join(logs) + "\n\nVERIFY\n" + "\n".join(f"{k}: {v}" for k, v in checks.items()),
        encoding="utf-8",
    )
    for line in logs:
        print(line)
    print("VERIFY", checks)
    if checks["user_residuals"]:
        print("WARN residuals", checks["user_residuals"])


if __name__ == "__main__":
    main()
