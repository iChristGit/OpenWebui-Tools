"""
title: Quick Utils
author: iChrist
description: >
  Swiss Army knife for everyday chat tasks. Ten zero-dependency utilities:
  🆔 generate_uuid — v1 / v4 UUIDs, up to 20 at once with one-click copy;
  📦 base64_tool — encode or decode any UTF-8 text;
  🎨 color_convert — HEX ↔ RGB ↔ HSL with a live colour swatch card;
  🔐 generate_password — cryptographically secure (secrets module), fully customisable;
  📱 qr_code — renders an inline PNG QR code for any URL or text (no external service);
  🔢 number_base — decimal / hexadecimal / binary / octal converter;
  🧮 calculator — evaluate safe math expressions with full step-by-step display;
  ⏱️ unix_timestamp — convert between Unix timestamps and human-readable dates;
  📝 text_stats — word count, char count, reading time, and frequency analysis;
  🔤 text_transform — case conversion, reverse, slug, camelCase, and more;
  🎲 random_pick — pick random items from a list or generate a random number in range.
version: 2.0.0
license: MIT
requirements: qrcode[pil], pillow
"""

import base64 as _b64
import colorsys
import io
import math
import operator
import random
import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
#  Shared HTML / CSS helpers
# ─────────────────────────────────────────────────────────────────────────────

_COPY_JS = """<script>
function _quCopy(btn){
  navigator.clipboard.writeText(btn.dataset.v).then(()=>{
    var t=btn.textContent;btn.textContent='✓ Copied';
    setTimeout(()=>btn.textContent=t,1500);
  }).catch(()=>{
    var ta=document.createElement('textarea');
    ta.value=btn.dataset.v;document.body.appendChild(ta);
    ta.select();document.execCommand('copy');document.body.removeChild(ta);
    var t=btn.textContent;btn.textContent='✓ Copied';
    setTimeout(()=>btn.textContent=t,1500);
  });
}
</script>"""

_CARD_BASE = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
    "background:var(--background-secondary,#1e1e2e);"
    "border:1px solid var(--border-color,#3b3b5c);"
    "border-radius:14px;padding:18px 22px;margin:6px 0;"
    "color:var(--text-primary,#cdd6f4);max-width:600px;"
)


def _copy_btn(value: str, label: str = "Copy") -> str:
    esc = value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
    return (
        f'<button onclick="_quCopy(this)" data-v="{esc}" '
        'style="cursor:pointer;background:rgba(124,58,237,.15);color:#a78bfa;'
        "border:1px solid rgba(124,58,237,.35);border-radius:6px;"
        "padding:3px 10px;font-size:11px;margin-left:8px;"
        'font-family:inherit;white-space:nowrap;">'
        f"{label}</button>"
    )


def _card(icon: str, title: str, body: str, accent: str = "#7c3aed") -> str:
    return (
        f"{_COPY_JS}"
        f'<div style="{_CARD_BASE}">'
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;'
        f'border-bottom:1px solid var(--border-color,#3b3b5c);padding-bottom:10px;">'
        f'<span style="font-size:20px;">{icon}</span>'
        f'<span style="font-size:12px;font-weight:700;letter-spacing:.07em;'
        f'text-transform:uppercase;color:{accent};">{title}</span>'
        f"</div>"
        f"{body}"
        f"</div>"
    )


def _row(label: str, value: str, copyable: bool = True) -> str:
    btn = _copy_btn(value) if copyable else ""
    return (
        '<div style="display:flex;align-items:center;justify-content:space-between;'
        'padding:7px 0;border-bottom:1px solid rgba(255,255,255,.05);">'
        f'<span style="font-size:12px;color:var(--text-secondary,#a6adc8);'
        f'min-width:90px;flex-shrink:0;">{label}</span>'
        f"<span style=\"font-family:'Cascadia Code','Fira Code',monospace;"
        f'font-size:13px;word-break:break-all;flex:1;">{value}</span>'
        f"{btn}</div>"
    )


async def _emit_status(emitter, msg: str, done: bool = False):
    if emitter:
        await emitter({"type": "status", "data": {"description": msg, "done": done}})


# ─────────────────────────────────────────────────────────────────────────────
#  Color helpers
# ─────────────────────────────────────────────────────────────────────────────


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, lum, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return round(h * 360), round(s * 100), round(lum * 100)


def _hsl_to_rgb(h: int, s: int, lum: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h / 360, lum / 100, s / 100)
    return round(r * 255), round(g * 255), round(b * 255)


def _parse_color(raw: str) -> tuple[int, int, int]:
    raw = raw.strip()
    if raw.startswith("#"):
        return _hex_to_rgb(raw)
    m = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, re.I)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"hsl\s*\(\s*(\d+)\s*,\s*(\d+)%?\s*,\s*(\d+)%?\s*\)", raw, re.I)
    if m:
        return _hsl_to_rgb(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return int(parts[0]), int(parts[1]), int(parts[2])
    raise ValueError(
        f"Cannot parse '{raw}'. Use #rrggbb, rgb(r,g,b), hsl(h,s%,l%), or r,g,b."
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Password strength meter
# ─────────────────────────────────────────────────────────────────────────────


def _pw_strength(pw: str) -> tuple[str, str]:
    score = 0
    if len(pw) >= 12:
        score += 1
    if len(pw) >= 20:
        score += 1
    if re.search(r"[A-Z]", pw):
        score += 1
    if re.search(r"[0-9]", pw):
        score += 1
    if re.search(r"[^A-Za-z0-9]", pw):
        score += 1
    for threshold, label, color in [
        (2, "Weak", "#ef4444"),
        (3, "Fair", "#f97316"),
        (4, "Good", "#eab308"),
        (5, "Strong", "#22c55e"),
    ]:
        if score <= threshold:
            return label, color
    return "Strong", "#22c55e"


# ─────────────────────────────────────────────────────────────────────────────
#  Safe math evaluator (no eval)
# ─────────────────────────────────────────────────────────────────────────────

_SAFE_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "//": operator.floordiv,
    "%": operator.mod,
    "**": operator.pow,
}

_SAFE_FUNCS = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pi": math.pi,
    "e": math.e,
    "pow": math.pow,
    "max": max,
    "min": min,
    "sum": sum,
    "int": int,
    "float": float,
}


def _safe_eval(expr: str) -> float:
    """Evaluate a math expression safely using ast."""
    import ast

    expr = expr.strip().replace("^", "**")  # support ^ as power

    class _Visitor(ast.NodeVisitor):
        def visit_Expression(self, node):
            return self.visit(node.body)

        def visit_BinOp(self, node):
            left = self.visit(node.left)
            right = self.visit(node.right)
            ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.FloorDiv: operator.floordiv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
            }
            op_fn = ops.get(type(node.op))
            if op_fn is None:
                raise ValueError(f"Unsupported operator: {node.op}")
            return op_fn(left, right)

        def visit_UnaryOp(self, node):
            val = self.visit(node.operand)
            if isinstance(node.op, ast.USub):
                return -val
            if isinstance(node.op, ast.UAdd):
                return val
            raise ValueError("Unsupported unary op")

        def visit_Num(self, node):  # Python <3.8 compat
            return node.n

        def visit_Constant(self, node):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant: {node.value}")

        def visit_Call(self, node):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Only simple function calls allowed")
            fn = _SAFE_FUNCS.get(node.func.id)
            if fn is None:
                raise ValueError(f"Unknown function: {node.func.id}")
            args = [self.visit(a) for a in node.args]
            return fn(*args)

        def visit_Name(self, node):
            val = _SAFE_FUNCS.get(node.id)
            if val is None or not isinstance(val, (int, float)):
                raise ValueError(f"Unknown name: {node.id}")
            return val

        def generic_visit(self, node):
            raise ValueError(f"Unsupported expression: {type(node).__name__}")

    tree = ast.parse(expr, mode="eval")
    visitor = _Visitor()
    return visitor.visit(tree)


# ─────────────────────────────────────────────────────────────────────────────
#  Tools class
# ─────────────────────────────────────────────────────────────────────────────


class Tools:
    class Valves(BaseModel):
        default_uuid_version: int = Field(
            default=4, description="Default UUID version to generate (1 or 4)."
        )
        default_password_length: int = Field(
            default=20, description="Default generated password length (8–128)."
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── 1. UUID ───────────────────────────────────────────────────────────────

    async def generate_uuid(
        self,
        version: int = 4,
        count: int = 1,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Generate one or more UUIDs and display them in a copy-ready card.

        USE THIS TOOL when the user asks for a UUID, GUID, or unique identifier.

        :param version: UUID version — 1 (time-based) or 4 (random). Default 4.
        :param count: How many UUIDs to generate (1–20). Default 1.
        """
        await _emit_status(__event_emitter__, "Generating UUIDs…")
        version = version if version in (1, 4) else 4
        count = max(1, min(count, 20))

        ids = [
            str(uuid.uuid1() if version == 1 else uuid.uuid4()) for _ in range(count)
        ]

        rows = "".join(_row(f"#{i + 1}", uid) for i, uid in enumerate(ids))
        all_ids = "\n".join(ids)
        body = (
            f"{rows}"
            f'<div style="margin-top:10px;text-align:right;">'
            f'{_copy_btn(all_ids, "Copy All")}</div>'
        )
        html = _card("🆔", f"UUID v{version} — {count} generated", body)
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return "\n".join(ids)

    # ── 2. Base64 encode / decode ─────────────────────────────────────────────

    async def base64_tool(
        self,
        text: str,
        mode: str = "encode",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Encode plain text to Base64 or decode Base64 back to plain text.

        USE THIS TOOL when the user asks to encode/decode base64, or says
        something like "what does this base64 say" / "base64-encode this string".

        :param text: The string to encode or decode.
        :param mode: "encode" (plain text → Base64) or "decode" (Base64 → plain text).
        """
        await _emit_status(__event_emitter__, "Processing Base64…")
        mode = mode.lower().strip()
        try:
            if mode == "encode":
                result = _b64.b64encode(text.encode("utf-8")).decode("ascii")
                label_in, label_out, icon, op = "Input", "Base64", "📦", "Encode"
            else:
                result = _b64.b64decode(text.encode("ascii")).decode("utf-8")
                label_in, label_out, icon, op = "Base64", "Decoded", "📤", "Decode"
        except Exception as exc:
            await _emit_status(__event_emitter__, "Error", done=True)
            return f"Error: {exc}"

        body = (
            f"{_row(label_in, text)}"
            f"{_row(label_out, result)}"
            f'<div style="margin-top:8px;font-size:11px;'
            f'color:var(--text-secondary,#a6adc8);">'
            f"{len(text)} chars in → {len(result)} chars out</div>"
        )
        html = _card(icon, f"Base64 {op}", body, accent="#0ea5e9")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return result

    # ── 3. Colour converter ───────────────────────────────────────────────────

    async def color_convert(
        self,
        color: str,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Convert a colour between HEX, RGB, and HSL and render a live swatch.

        USE THIS TOOL when the user asks to convert a colour, find its HEX code,
        or wants to see "what colour is rgb(…)" / "what is hsl(…) in HEX".

        Accepts: #rrggbb, #rgb, rgb(r,g,b), hsl(h,s%,l%), or "r,g,b".

        :param color: The colour to convert. Examples: "#ff6b35", "rgb(255,107,53)".
        """
        await _emit_status(__event_emitter__, "Converting color…")
        try:
            r, g, b = _parse_color(color)
        except ValueError as exc:
            await _emit_status(__event_emitter__, "Error", done=True)
            return str(exc)

        r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
        hex_val = _rgb_to_hex(r, g, b)
        h_deg, s_pct, lum_pct = _rgb_to_hsl(r, g, b)
        rgb_str = f"rgb({r}, {g}, {b})"
        hsl_str = f"hsl({h_deg}, {s_pct}%, {lum_pct}%)"
        text_on_swatch = "#1e1e2e" if lum_pct > 55 else "#ffffff"

        body = (
            f'<div style="width:100%;height:76px;border-radius:10px;'
            f"margin-bottom:14px;background:{hex_val};"
            f'display:flex;align-items:center;justify-content:center;">'
            f'<span style="color:{text_on_swatch};font-family:monospace;'
            f"font-size:20px;font-weight:700;"
            f'text-shadow:0 1px 4px rgba(0,0,0,.4);">{hex_val}</span>'
            f"</div>"
            f"{_row('HEX', hex_val)}"
            f"{_row('RGB', rgb_str)}"
            f"{_row('HSL', hsl_str)}"
            f"{_row('R / G / B', f'{r} / {g} / {b}', copyable=False)}"
        )
        html = _card("🎨", "Color Converter", body, accent="#ec4899")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return f"HEX: {hex_val} | RGB: {rgb_str} | HSL: {hsl_str}"

    # ── 4. Secure password generator ─────────────────────────────────────────

    async def generate_password(
        self,
        length: int = 20,
        count: int = 1,
        include_uppercase: bool = True,
        include_numbers: bool = True,
        include_symbols: bool = True,
        exclude_ambiguous: bool = False,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Generate cryptographically secure passwords using Python's secrets module (CSPRNG).

        USE THIS TOOL when the user asks for a password, passphrase, or secure random string.

        :param length: Password length (8–128). Default 20.
        :param count: Number of passwords to generate (1–10). Default 1.
        :param include_uppercase: Include A–Z characters. Default True.
        :param include_numbers: Include 0–9 digits. Default True.
        :param include_symbols: Include symbols like !@#$%^&*. Default True.
        :param exclude_ambiguous: Exclude visually similar chars (l,1,I,O,0). Default False.
        """
        await _emit_status(__event_emitter__, "Generating passwords…")
        length = max(8, min(128, length))
        count = max(1, min(10, count))
        syms = "!@#$%^&*()_+-=[]{}|;:,.<>?"

        pool = string.ascii_lowercase
        if include_uppercase:
            pool += string.ascii_uppercase
        if include_numbers:
            pool += string.digits
        if include_symbols:
            pool += syms
        if exclude_ambiguous:
            for ch in "l1IO0":
                pool = pool.replace(ch, "")

        rng = secrets.SystemRandom()
        passwords = []
        for _ in range(count):
            required: list[str] = [secrets.choice(string.ascii_lowercase)]
            if include_uppercase:
                uc = (
                    string.ascii_uppercase.replace("I", "").replace("O", "")
                    if exclude_ambiguous
                    else string.ascii_uppercase
                )
                required.append(secrets.choice(uc))
            if include_numbers:
                digs = (
                    string.digits.replace("0", "").replace("1", "")
                    if exclude_ambiguous
                    else string.digits
                )
                required.append(secrets.choice(digs))
            if include_symbols:
                required.append(secrets.choice(syms))

            fill = [secrets.choice(pool) for _ in range(max(0, length - len(required)))]
            chars = required + fill
            rng.shuffle(chars)
            passwords.append("".join(chars))

        rows_html = ""
        for pwd in passwords:
            s_label, s_color = _pw_strength(pwd)
            rows_html += (
                '<div style="padding:8px 0;border-bottom:1px solid rgba(255,255,255,.05);">'
                '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">'
                f"<span style=\"font-family:'Cascadia Code','Fira Code',monospace;"
                f'font-size:13px;word-break:break-all;flex:1;">{pwd}</span>'
                f"{_copy_btn(pwd)}</div>"
                f'<div style="margin-top:4px;font-size:11px;color:{s_color};">'
                f"● {s_label} · {len(pwd)} chars</div>"
                "</div>"
            )

        pool_desc = "a–z"
        if include_uppercase:
            pool_desc += " A–Z"
        if include_numbers:
            pool_desc += " 0–9"
        if include_symbols:
            pool_desc += " symbols"

        body = (
            f"{rows_html}"
            f'<div style="margin-top:10px;font-size:11px;'
            f'color:var(--text-secondary,#a6adc8);">'
            f"Pool: {pool_desc} · Generated with Python <code>secrets</code> (CSPRNG)</div>"
        )
        html = _card(
            "🔐", f"Secure Password · {count} generated", body, accent="#22c55e"
        )
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return "\n".join(passwords)

    # ── 5. QR code ────────────────────────────────────────────────────────────

    async def qr_code(
        self,
        content: str,
        error_correction: str = "M",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Generate an inline QR code image for any URL, text, Wi-Fi string, or contact card.
        Renders the QR code as a base64 PNG directly in the chat — no external service needed.

        USE THIS TOOL when the user asks to "make a QR code for…" or "generate a QR
        code" for a URL, phone number, address, or any text.

        :param content: The URL or text to encode. Examples: "https://example.com",
                        "WIFI:S:MySSID;T:WPA;P:mypassword;;" (Wi-Fi QR),
                        "tel:+15551234567".
        :param error_correction: Damage tolerance — L=7%, M=15% (default), Q=25%, H=30%.
        """
        await _emit_status(__event_emitter__, "Generating QR code…")
        try:
            import qrcode
            from PIL import Image
        except ImportError:
            await _emit_status(__event_emitter__, "Error", done=True)
            return "Error: qrcode[pil] package not installed. Run: pip install 'qrcode[pil]'"

        ec_map = {
            "L": qrcode.constants.ERROR_CORRECT_L,
            "M": qrcode.constants.ERROR_CORRECT_M,
            "Q": qrcode.constants.ERROR_CORRECT_Q,
            "H": qrcode.constants.ERROR_CORRECT_H,
        }
        ec = ec_map.get(error_correction.upper(), qrcode.constants.ERROR_CORRECT_M)

        qr = qrcode.QRCode(error_correction=ec, border=4, box_size=10)
        qr.add_data(content)
        qr.make(fit=True)

        # Generate as PNG (PIL) and embed as base64 data URI — works universally in browsers
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
        data_uri = f"data:image/png;base64,{png_b64}"

        label = content if len(content) <= 52 else content[:49] + "…"
        body = (
            '<div style="display:flex;flex-direction:column;align-items:center;gap:12px;">'
            f'<img src="{data_uri}" alt="QR Code" '
            'style="width:220px;height:220px;border-radius:10px;'
            'background:#fff;padding:8px;display:block;" />'
            f'<div style="font-size:11px;color:var(--text-secondary,#a6adc8);'
            f'word-break:break-all;text-align:center;">{label}</div>'
            f'<div style="font-size:10px;color:var(--text-secondary,#a6adc8);">'
            f"EC level: {error_correction.upper()} · {len(content)} chars encoded</div>"
            f'{_copy_btn(content, "Copy content")}'
            "</div>"
        )
        html = _card("📱", "QR Code", body, accent="#f59e0b")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return f"QR code generated for: {content}"

    # ── 6. Number base converter ───────────────────────────────────────────────

    async def number_base(
        self,
        value: str,
        from_base: str = "decimal",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Convert a number between decimal, hexadecimal, binary, and octal.
        Shows all four representations at once in a single card.

        USE THIS TOOL when the user wants to convert a number between bases, asks
        "what is 255 in hex", "convert 0xff to decimal", "binary of 42", etc.

        :param value: The number as a string, e.g. "255", "FF", "11111111", "0377".
        :param from_base: Source base — "decimal" (default), "hex", "binary", or "octal".
        """
        await _emit_status(__event_emitter__, "Converting number base…")
        raw = value.strip().lower()

        if raw.startswith("0x"):
            from_base, raw = "hex", raw[2:]
        elif raw.startswith("0b"):
            from_base, raw = "binary", raw[2:]
        elif raw.startswith("0o"):
            from_base, raw = "octal", raw[2:]

        base_map = {
            "decimal": 10,
            "dec": 10,
            "10": 10,
            "hex": 16,
            "hexadecimal": 16,
            "base16": 16,
            "16": 16,
            "binary": 2,
            "bin": 2,
            "base2": 2,
            "2": 2,
            "octal": 8,
            "oct": 8,
            "base8": 8,
            "8": 8,
        }
        base = base_map.get(from_base.lower(), 10)
        try:
            n = int(raw, base)
        except ValueError:
            await _emit_status(__event_emitter__, "Error", done=True)
            return f"Error: '{value}' is not a valid {from_base} number."

        dec_str = str(n)
        hex_str = f"0x{n:X}"
        bin_raw = f"{n:b}"
        oct_str = f"0o{n:o}"

        padded = bin_raw.zfill(((len(bin_raw) - 1) // 4 + 1) * 4)
        bin_nibbles = " ".join(padded[i : i + 4] for i in range(0, len(padded), 4))

        body = (
            f"{_row('Decimal', dec_str)}"
            f"{_row('Hexadecimal', hex_str)}"
            f"{_row('Binary', f'0b{bin_raw}')}"
            f"{_row('Octal', oct_str)}"
            f'<div style="margin-top:10px;padding-top:8px;'
            f"border-top:1px solid rgba(255,255,255,.07);"
            f'font-size:11px;color:var(--text-secondary,#a6adc8);">'
            f"Binary (nibbles): "
            f'<code style="font-family:monospace;">{bin_nibbles}</code>'
            "</div>"
        )
        html = _card(
            "🔢", f"Number Base Converter · from {from_base}", body, accent="#06b6d4"
        )
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return f"dec={dec_str} | hex={hex_str} | bin=0b{bin_raw} | oct={oct_str}"

    # ── 7. Calculator ─────────────────────────────────────────────────────────

    async def calculator(
        self,
        expression: str,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Evaluate a mathematical expression safely and display the result in a card.
        Supports: +, -, *, /, //, %, ** (or ^), parentheses, and math functions
        like sqrt(), sin(), cos(), log(), abs(), round(), floor(), ceil(), pi, e.

        USE THIS TOOL when the user asks to calculate, compute, or evaluate any
        math expression. Examples: "what is 2^32", "sqrt(144)", "sin(pi/2)".

        :param expression: The math expression to evaluate. E.g. "sqrt(2) * pi", "2**10 + 5".
        """
        await _emit_status(__event_emitter__, "Calculating…")
        expr_display = expression.strip()
        try:
            result = _safe_eval(expr_display)
            # Format nicely: integer if whole number, else float
            if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
                result_str = str(int(result))
            else:
                result_str = f"{result:.10g}"
        except ZeroDivisionError:
            await _emit_status(__event_emitter__, "Error", done=True)
            return "Error: Division by zero."
        except Exception as exc:
            await _emit_status(__event_emitter__, "Error", done=True)
            return f"Error evaluating expression: {exc}"

        body = (
            f'<div style="text-align:center;padding:12px 0;">'
            f'<div style="font-size:13px;color:var(--text-secondary,#a6adc8);'
            f'font-family:monospace;margin-bottom:8px;">{expr_display}</div>'
            f'<div style="font-size:11px;color:var(--text-secondary,#a6adc8);margin-bottom:4px;">═══</div>'
            f'<div style="font-size:28px;font-weight:700;font-family:monospace;'
            f'color:#a78bfa;margin-bottom:12px;">{result_str}</div>'
            f'{_copy_btn(result_str, "Copy result")}'
            f"</div>"
            f'<div style="font-size:10px;color:var(--text-secondary,#a6adc8);margin-top:8px;">'
            f"Supported: +−×÷ // % ** sqrt log sin cos tan abs round floor ceil pi e"
            f"</div>"
        )
        html = _card("🧮", "Calculator", body, accent="#a78bfa")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return f"{expr_display} = {result_str}"

    # ── 8. Unix timestamp converter ───────────────────────────────────────────

    async def unix_timestamp(
        self,
        value: str = "now",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Convert between Unix timestamps and human-readable UTC/local date strings.
        Pass "now" to get the current time, a Unix integer to decode it,
        or a date string like "2024-01-15 14:30:00" to encode it.

        USE THIS TOOL when the user asks about a Unix timestamp, "what time is epoch X",
        "convert this date to timestamp", or "what is the current Unix time".

        :param value: "now", a Unix timestamp integer (e.g. "1700000000"),
                      or an ISO date string (e.g. "2024-01-15 14:30:00").
        """
        await _emit_status(__event_emitter__, "Converting timestamp…")
        try:
            v = value.strip().lower()
            if v in ("now", ""):
                dt = datetime.now(timezone.utc)
                ts = int(dt.timestamp())
                mode = "Current time"
            elif re.match(r"^\d{9,13}$", v):
                # Detect milliseconds vs seconds
                raw_ts = int(v)
                if raw_ts > 1e11:
                    raw_ts = raw_ts // 1000
                dt = datetime.fromtimestamp(raw_ts, tz=timezone.utc)
                ts = raw_ts
                mode = "Decoded from Unix timestamp"
            else:
                # Try parsing as date string
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(value.strip(), fmt).replace(
                            tzinfo=timezone.utc
                        )
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(f"Cannot parse date: '{value}'")
                ts = int(dt.timestamp())
                mode = "Encoded from date string"
        except Exception as exc:
            await _emit_status(__event_emitter__, "Error", done=True)
            return f"Error: {exc}"

        utc_str = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        iso_str = dt.isoformat()
        rfc_str = dt.strftime("%a, %d %b %Y %H:%M:%S GMT")

        body = (
            f"{_row('Unix (seconds)', str(ts))}"
            f"{_row('Unix (ms)', str(ts * 1000))}"
            f"{_row('UTC', utc_str)}"
            f"{_row('ISO 8601', iso_str)}"
            f"{_row('RFC 2822', rfc_str)}"
            f'<div style="margin-top:10px;font-size:11px;'
            f'color:var(--text-secondary,#a6adc8);">{mode}</div>'
        )
        html = _card("⏱️", "Unix Timestamp", body, accent="#f59e0b")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return f"ts={ts} | utc={utc_str}"

    # ── 9. Text statistics ────────────────────────────────────────────────────

    async def text_stats(
        self,
        text: str,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Analyse text: word count, character count, sentence count, estimated reading time,
        and top-5 most frequent words.

        USE THIS TOOL when the user asks "how many words is this", "reading time for X",
        "analyse this text", or "word frequency".

        :param text: The text to analyse.
        """
        await _emit_status(__event_emitter__, "Analysing text…")
        words = re.findall(r"\b\w+\b", text.lower())
        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        chars = len(text)
        chars_no_space = len(text.replace(" ", ""))
        word_count = len(words)
        sent_count = len(sentences)
        para_count = len([p for p in text.split("\n\n") if p.strip()])
        reading_time_s = max(1, round(word_count / 200 * 60))  # ~200 wpm
        if reading_time_s < 60:
            rt_str = f"{reading_time_s}s"
        else:
            rt_str = f"{reading_time_s // 60}m {reading_time_s % 60}s"

        # Top words (excluding common stop words)
        stop = {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "is",
            "are",
            "was",
            "be",
            "it",
            "i",
            "this",
            "that",
            "as",
            "by",
            "from",
            "not",
            "have",
            "has",
            "had",
        }
        freq: dict[str, int] = {}
        for w in words:
            if w not in stop and len(w) > 2:
                freq[w] = freq.get(w, 0) + 1
        top5 = sorted(freq.items(), key=lambda x: -x[1])[:5]
        top5_html = (
            ", ".join(f'<code style="color:#a78bfa">{w}</code> ×{c}' for w, c in top5)
            or "—"
        )

        body = (
            f"{_row('Words', str(word_count), copyable=False)}"
            f"{_row('Characters', str(chars), copyable=False)}"
            f"{_row('Chars (no spaces)', str(chars_no_space), copyable=False)}"
            f"{_row('Sentences', str(sent_count), copyable=False)}"
            f"{_row('Paragraphs', str(para_count), copyable=False)}"
            f"{_row('Reading time (~200wpm)', rt_str, copyable=False)}"
            f'<div style="margin-top:10px;padding-top:8px;'
            f"border-top:1px solid rgba(255,255,255,.07);"
            f'font-size:12px;color:var(--text-secondary,#a6adc8);">'
            f"Top words: {top5_html}</div>"
        )
        html = _card("📝", "Text Statistics", body, accent="#10b981")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return f"words={word_count} | chars={chars} | reading_time={rt_str}"

    # ── 10. Text transformer ──────────────────────────────────────────────────

    async def text_transform(
        self,
        text: str,
        mode: str = "all",
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Transform text into various case formats and styles.
        Modes: upper, lower, title, snake, kebab, camel, pascal, slug, reverse, all.

        USE THIS TOOL when the user asks to convert text case, make a slug, convert to
        camelCase, PascalCase, snake_case, kebab-case, UPPER CASE, or reverse text.

        :param text: The text to transform.
        :param mode: Transformation mode. Default "all" shows every format at once.
                     Options: upper, lower, title, snake, kebab, camel, pascal, slug, reverse, all.
        """
        await _emit_status(__event_emitter__, "Transforming text…")
        t = text.strip()
        words = re.findall(r"[A-Za-z0-9]+", t)

        transforms = {
            "upper": t.upper(),
            "lower": t.lower(),
            "title": t.title(),
            "snake": "_".join(w.lower() for w in words),
            "kebab": "-".join(w.lower() for w in words),
            "camel": (
                (words[0].lower() + "".join(w.title() for w in words[1:]))
                if words
                else ""
            ),
            "pascal": "".join(w.title() for w in words),
            "slug": re.sub(r"-+", "-", "-".join(w.lower() for w in words)).strip("-"),
            "reverse": t[::-1],
        }

        mode = mode.lower().strip()
        if mode != "all" and mode in transforms:
            result = transforms[mode]
            body = f"{_row('Input', t)}" f"{_row(mode.title(), result)}"
            html = _card("🔤", f"Text Transform · {mode}", body, accent="#8b5cf6")
            if __event_emitter__:
                await __event_emitter__({"type": "message", "data": {"content": html}})
            await _emit_status(__event_emitter__, "Done", done=True)
            return result

        # "all" mode
        rows = "".join(_row(k.title(), v) for k, v in transforms.items())
        body = f"{_row('Input', t)}{rows}"
        html = _card("🔤", "Text Transform · All Formats", body, accent="#8b5cf6")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return " | ".join(f"{k}={v}" for k, v in transforms.items())

    # ── 11. Random picker ─────────────────────────────────────────────────────

    async def random_pick(
        self,
        items: str = "",
        count: int = 1,
        min_val: int = 1,
        max_val: int = 100,
        __event_emitter__: Optional[Callable] = None,
    ) -> str:
        """
        Pick random items from a comma-separated list, or generate random numbers in a range.
        If items are provided, picks from the list. Otherwise, generates random integers.

        USE THIS TOOL when the user says "pick a random X", "choose from these options",
        "flip a coin", "roll a dice", or "random number between X and Y".

        :param items: Comma-separated list to pick from. E.g. "Alice, Bob, Charlie".
                      Leave empty to generate random numbers instead.
        :param count: How many to pick / generate (1–20). Default 1.
        :param min_val: Minimum value for number generation (default 1).
        :param max_val: Maximum value for number generation (default 100).
        """
        await _emit_status(__event_emitter__, "Picking randomly…")
        count = max(1, min(20, count))

        if items.strip():
            choices = [i.strip() for i in items.split(",") if i.strip()]
            if not choices:
                await _emit_status(__event_emitter__, "Error", done=True)
                return "Error: No valid items found."

            if count > len(choices):
                picked = random.choices(choices, k=count)
                note = "(with repetition — count exceeds list size)"
            else:
                picked = random.sample(choices, k=count)
                note = "(without repetition)"

            rows = "".join(_row(f"Pick #{i+1}", p) for i, p in enumerate(picked))
            body = (
                f'<div style="margin-bottom:10px;font-size:11px;'
                f'color:var(--text-secondary,#a6adc8);">'
                f"From {len(choices)} items · {count} picked {note}</div>"
                f"{rows}"
            )
            result_str = ", ".join(picked)
        else:
            min_val, max_val = min(min_val, max_val), max(min_val, max_val)
            nums = [random.randint(min_val, max_val) for _ in range(count)]
            rows = "".join(_row(f"#{i+1}", str(n)) for i, n in enumerate(nums))
            body = (
                f'<div style="margin-bottom:10px;font-size:11px;'
                f'color:var(--text-secondary,#a6adc8);">'
                f"Range: {min_val}–{max_val} · {count} number(s)</div>"
                f"{rows}"
                f'<div style="margin-top:8px;text-align:right;">'
                f'{_copy_btn(", ".join(str(n) for n in nums), "Copy All")}</div>'
            )
            result_str = ", ".join(str(n) for n in nums)

        html = _card("🎲", "Random Pick", body, accent="#f43f5e")
        if __event_emitter__:
            await __event_emitter__({"type": "message", "data": {"content": html}})
        await _emit_status(__event_emitter__, "Done", done=True)
        return result_str
