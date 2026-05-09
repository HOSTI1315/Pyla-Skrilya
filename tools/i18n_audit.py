"""Audit i18n parity + scan JSX for hardcoded Russian/English strings.

Usage: py -3.11 tools/i18n_audit.py
"""
from __future__ import annotations
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "web_ui"

# ── Parity ───────────────────────────────────────────────────────────
content = (UI / "i18n.js").read_text(encoding="utf-8")
ru_block = content[content.index("ru:"):content.index("en:")]
en_block = content[content.index("en:"):]
key_re = re.compile(r"^\s+'([^']+)'\s*:", re.MULTILINE)
ru_keys = set(key_re.findall(ru_block))
en_keys = set(key_re.findall(en_block))
print(f"PARITY: ru={len(ru_keys)}  en={len(en_keys)}")
gap = ru_keys ^ en_keys
if gap:
    print(f"  parity gaps: {len(gap)} keys")
    for k in sorted(gap):
        side = "ru only" if k in ru_keys else "en only"
        print(f"    [{side}] {k}")
else:
    print("  OK every key has both ru and en")

# ── Hardcoded strings ────────────────────────────────────────────────
JSX_FILES = [
    "app.jsx", "more-pages.jsx", "components.jsx",
    "settings-page.jsx", "stats-page.jsx", "ui-extras.jsx",
    "data.jsx", "extra-data.jsx", "store.jsx",
]

# Cyrillic (a-я) — Russian leak; will detect both pure RU and mixed.
CYR = re.compile(r"[А-Яа-яЁё]")
# JSX text node between > and < (no JSX expression {})
TEXT_NODE_RE = re.compile(r">\s*([^<{][^<{]*?)\s*<", re.DOTALL)
# Attributes: placeholder=, title=, aria-label=
ATTR_RE = re.compile(r"(placeholder|title|aria-label)\s*=\s*[\"']([^\"']+)[\"']")
# Toast/confirm/alert calls
CALL_RE = re.compile(r"(?:pylaToast\??\.\(|confirm\(|alert\()\s*[`\"']([^`\"']+)[`\"']")

# Skip: pure punctuation/icons/symbols, pure-numeric, single chars, very short utility tokens
SKIP_LITERAL = {"×", "—", "▍", "●", "○", "↑", "↓", "🏆", "—", " · ", "·"}
SKIP_RE = re.compile(r"^[\s\d.,:;!?+\-*/×—·●○↑↓→←▍🏆()\[\]{}\"'`]+$")

# Lines containing these markers are noise (comments, etc)
def looks_like_real_text(s: str) -> bool:
    s = s.strip()
    if not s or len(s) < 2:
        return False
    if s in SKIP_LITERAL:
        return False
    if SKIP_RE.match(s):
        return False
    return True

total_ru = 0
total_other = 0
print()
print("HARDCODED STRINGS (not going through t()):")
for fname in JSX_FILES:
    fpath = UI / fname
    if not fpath.is_file():
        continue
    src = fpath.read_text(encoding="utf-8")
    findings_ru = []
    findings_other = []  # English text that's also user-visible

    # JSX text nodes
    for m in TEXT_NODE_RE.finditer(src):
        text = m.group(1).strip()
        if not looks_like_real_text(text):
            continue
        # Skip JSX boilerplate (className parts, t(...) results, etc)
        if "{" in text or "}" in text:
            continue
        # Skip URLs
        if text.startswith("http") or text.startswith("//"):
            continue
        line = src[:m.start()].count("\n") + 1
        if CYR.search(text):
            findings_ru.append((line, text))
        elif re.search(r"[A-Za-z]{3,}", text):
            # English text node — might be intentional brand/code, log if 3+ letters
            findings_other.append((line, text))

    # Attributes
    for m in ATTR_RE.finditer(src):
        text = m.group(2).strip()
        if not looks_like_real_text(text):
            continue
        line = src[:m.start()].count("\n") + 1
        if CYR.search(text):
            findings_ru.append((line, f"[{m.group(1)}=] {text}"))

    # Toast/confirm/alert
    for m in CALL_RE.finditer(src):
        text = m.group(1).strip()
        if not looks_like_real_text(text):
            continue
        line = src[:m.start()].count("\n") + 1
        if CYR.search(text):
            findings_ru.append((line, f"[call] {text}"))

    findings_ru = sorted(set(findings_ru))
    findings_other = sorted(set(findings_other))
    if findings_ru:
        print(f"  --- {fname} (RU: {len(findings_ru)}) ---")
        for line, text in findings_ru:
            snippet = text[:90] + ("..." if len(text) > 90 else "")
            print(f"    L{line}: {snippet}")
        total_ru += len(findings_ru)
    if findings_other:
        # Filter out single-word English likely-codes
        filtered = [(l, t) for l, t in findings_other
                    if len(t.split()) >= 2 or len(t) >= 8]
        # Skip code-like (ALL_CAPS, paths, identifiers)
        filtered = [(l, t) for l, t in filtered
                    if not re.match(r"^[A-Z_]{3,}$", t)
                    and "/" not in t and "." not in t.replace(" ", "")[:20]]
        if filtered:
            print(f"  --- {fname} (EN literals: {len(filtered)}) ---")
            for line, text in filtered[:10]:
                snippet = text[:90] + ("..." if len(text) > 90 else "")
                print(f"    L{line}: {snippet}")
            total_other += len(filtered)

print()
print(f"TOTAL hardcoded: RU={total_ru}, EN-literals={total_other}")
