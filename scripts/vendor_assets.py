"""Tai toan bo CSS/JS/font tu CDN ve app/static/vendor/ de chay local.

Loi ich:
  - Khong phu thuoc internet ra ngoai (jsdelivr, fonts.googleapis.com)
  - Trang load nhanh + on dinh hon, khong bi block boi DNS / TLS
    handshake toi server xa
  - Privacy: khong leak User-Agent / Referer toi Google Fonts CDN
  - Hoat dong khi VPS bi mat ket noi tam thoi voi internet

Idempotent — co the chay lai bat ky luc nao. Chi tai lai khi file moi.

Usage:
  venv\\Scripts\\python.exe scripts\\vendor_assets.py
"""
from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "app" / "static" / "vendor"

# Chrome UA so Google Fonts returns woff2 (modern format).
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def download(url: str, dest: Path, *, ua: str | None = None) -> bytes:
    if dest.exists():
        size = dest.stat().st_size
        print(f"  [SKIP] {dest.relative_to(ROOT)} ({size} bytes, already cached)")
        return dest.read_bytes()
    headers = {"User-Agent": ua or "Mozilla/5.0 (vic-ocr-vendor)"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  [OK]   {dest.relative_to(ROOT)} ({len(data)} bytes from {url})")
    return data


def vendor_bootstrap() -> None:
    print("=== Bootstrap 5.3.3 ===")
    download(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        VENDOR / "bootstrap" / "bootstrap.min.css",
    )
    download(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
        VENDOR / "bootstrap" / "bootstrap.bundle.min.js",
    )


def vendor_bootstrap_icons() -> None:
    print("=== Bootstrap Icons 1.11.3 ===")
    css_url = (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css"
    )
    css_dest = VENDOR / "bootstrap-icons" / "bootstrap-icons.min.css"
    download(css_url, css_dest)
    # Font files referenced by CSS (relative path: ./fonts/bootstrap-icons.woff2)
    download(
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2",
        VENDOR / "bootstrap-icons" / "fonts" / "bootstrap-icons.woff2",
    )
    download(
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff",
        VENDOR / "bootstrap-icons" / "fonts" / "bootstrap-icons.woff",
    )


def vendor_google_fonts() -> None:
    print("=== Google Fonts (Inter + Orbitron) ===")
    css_url = (
        "https://fonts.googleapis.com/css2?"
        "family=Inter:wght@400;500;600;700&"
        "family=Orbitron:wght@500;700&"
        "display=swap"
    )
    raw = download(
        css_url,
        VENDOR / "fonts" / "_remote-fonts.css",  # Temp marker for unfetched state
        ua=CHROME_UA,
    ).decode("utf-8")

    font_urls = sorted(set(re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+\.woff2)\)", raw)))
    print(f"  {len(font_urls)} woff2 file(s) detected")

    rewritten = raw
    for fu in font_urls:
        fname = fu.rsplit("/", 1)[-1].split("?", 1)[0]
        download(fu, VENDOR / "fonts" / "files" / fname, ua=CHROME_UA)
        rewritten = rewritten.replace(fu, f"./files/{fname}")

    final_css = VENDOR / "fonts" / "fonts.css"
    final_css.write_text(rewritten, encoding="utf-8")
    print(f"  [OK]   {final_css.relative_to(ROOT)} (rewritten with local paths)")
    # Cleanup marker file
    marker = VENDOR / "fonts" / "_remote-fonts.css"
    if marker.exists():
        marker.unlink()


def main() -> int:
    print(f"Vendoring assets to: {VENDOR}\n")
    VENDOR.mkdir(parents=True, exist_ok=True)
    try:
        vendor_bootstrap()
        vendor_bootstrap_icons()
        vendor_google_fonts()
    except Exception as exc:
        print(f"\n[LOI] {exc}", file=sys.stderr)
        return 1
    print("\n=== Hoan tat. base.html da co the dung url_for('static', filename='vendor/...') ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
