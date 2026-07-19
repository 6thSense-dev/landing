#!/usr/bin/env python3
"""
Vendor all external webfonts locally so the site makes NO runtime font request.

Downloads woff2 files into public/fonts/ and regenerates src/fonts.css with
@font-face rules pointing at those local files. Run whenever the design's font
families/weights change, then commit both the woff2 files and src/fonts.css.

Sources (must match what index.html used to request):
  - Google Fonts (css2): Geist Mono, Fraunces, Newsreader, Outfit
  - Fontshare:           General Sans

Only the `latin` and `latin-ext` unicode subsets are kept (English site).
Heming + Chillax are already self-hosted and declared in src/scroll-hero.css;
they are intentionally NOT touched here.

Usage:  python3 scripts/fetch-fonts.py
Requires network access + curl.
"""

import subprocess, re, os, hashlib

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "fonts")
CSS_OUT = os.path.join(ROOT, "src", "fonts.css")
os.makedirs(OUT, exist_ok=True)

GOOGLE = {
    "Geist Mono": "https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;500&display=swap",
    "Fraunces": "https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,500&display=swap",
    "Newsreader": "https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&display=swap",
    "Outfit": "https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap",
}
FONTSHARE = {
    "General Sans": "https://api.fontshare.com/v2/css?f[]=general-sans@400,500,600,700&display=swap",
}
KEEP_SUBSETS = {"latin", "latin-ext"}


def curl(url, binary=False):
    r = subprocess.run(["curl", "-sSL", "-A", UA, url], capture_output=True)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def slug(name):
    return name.lower().replace(" ", "")


def fetch_google(blocks_out, downloaded):
    for fam, url in GOOGLE.items():
        css = curl(url)
        parts = re.split(r"(/\*\s*[\w-]+\s*\*/)", css)
        cur_subset = None
        for p in parts:
            m = re.match(r"/\*\s*([\w-]+)\s*\*/", p.strip())
            if m:
                cur_subset = m.group(1)
                continue
            if "@font-face" not in p or cur_subset not in KEEP_SUBSETS:
                continue
            block = p[p.index("@font-face") :]
            style = re.search(r"font-style:\s*([^;]+);", block)
            weight = re.search(r"font-weight:\s*([^;]+);", block)
            srcm = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            if not srcm:
                continue
            src_url = srcm.group(1)
            style_v = style.group(1).strip() if style else "normal"
            weight_v = weight.group(1).strip() if weight else "400"
            if src_url in downloaded:
                fn = downloaded[src_url]
            else:
                h = hashlib.md5(src_url.encode()).hexdigest()[:6]
                fn = (
                    f"{slug(fam)}-{weight_v}-"
                    f"{'ital' if 'italic' in style_v else 'norm'}-{cur_subset}-{h}.woff2"
                )
                open(os.path.join(OUT, fn), "wb").write(curl(src_url, binary=True))
                downloaded[src_url] = fn
                print(f"  DL {fn}")
            unicode_m = re.search(r"unicode-range:\s*([^;]+);", block)
            b = (
                "@font-face {\n"
                f"  font-family: '{fam}';\n"
                f"  font-style: {style_v};\n"
                f"  font-weight: {weight_v};\n"
                "  font-display: swap;\n"
                f"  src: url('/fonts/{fn}') format('woff2');\n"
            )
            if unicode_m:
                b += f"  unicode-range: {unicode_m.group(1).strip()};\n"
            b += "}"
            blocks_out.append((f"/* {fam} - {weight_v} {style_v} - {cur_subset} */", b))


def fetch_fontshare(blocks_out):
    for fam, url in FONTSHARE.items():
        css = curl(url)
        for b in re.split(r"(?=@font-face)", css):
            if "@font-face" not in b:
                continue
            w = re.search(r"font-weight:\s*(\d+)", b)
            u = re.search(r"url\('(//cdn\.fontshare\.com/[^']+\.woff2)'\)", b)
            if not (w and u):
                continue
            weight = w.group(1)
            fn = f"{slug(fam)}-{weight}-norm.woff2"
            open(os.path.join(OUT, fn), "wb").write(
                curl("https:" + u.group(1), binary=True)
            )
            print(f"  DL {fn}")
            block = (
                "@font-face {\n"
                f"  font-family: '{fam}';\n"
                "  font-style: normal;\n"
                f"  font-weight: {weight};\n"
                "  font-display: swap;\n"
                f"  src: url('/fonts/{fn}') format('woff2');\n"
                "}"
            )
            blocks_out.append((f"/* {fam} - {weight} normal */", block))


def main():
    fontshare_blocks, google_blocks, downloaded = [], [], {}
    fetch_fontshare(fontshare_blocks)
    fetch_google(google_blocks, downloaded)
    header = (
        "/*\n"
        " * Self-hosted webfonts - vendored so there is NO external font request at\n"
        " * runtime (previously loaded from fonts.googleapis.com + api.fontshare.com).\n"
        " * GENERATED by scripts/fetch-fonts.py - do not hand-edit; rerun the script.\n"
        " * Families/weights match exactly what index.html requested before.\n"
        " * Heming + Chillax are declared in scroll-hero.css (already self-hosted).\n"
        " */\n\n"
    )
    with open(CSS_OUT, "w") as f:
        f.write(header)
        for c, b in fontshare_blocks + google_blocks:
            f.write(c + "\n" + b + "\n\n")
    print(
        f"Wrote {CSS_OUT}: {len(fontshare_blocks) + len(google_blocks)} @font-face blocks"
    )


if __name__ == "__main__":
    main()
