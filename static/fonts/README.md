# Font assets

Retrieved 2026-09-09 from the Google Fonts CSS API and its official fonts.gstatic.com CDN.
These are official WOFF2 subsets, not copies from PathHub. The corresponding
upstream SIL Open Font License 1.1 texts are included in this directory.

| File | Bytes | Source |
|---|---:|---|
| Manrope-latin.woff2 | 24836 | https://fonts.gstatic.com/s/manrope/v20/xn7gYHE41ni1AdIRggexSg.woff2 |
| JetBrainsMono-latin.woff2 | 31432 | https://fonts.gstatic.com/s/jetbrainsmono/v24/tDbv2o-flEEny0FZhsfKu5WU4zr3E_BX0PnT8RD8yKwBNntkaToggR7BYRbKPxDcwg.woff2 |

Manrope is used for Latin UI text; JetBrains Mono for code. Noto Sans SC is now
self-hosted as all 101 unique WOFF2 subsets returned by the official CSS request
below. Chinese rendering does not need a runtime connection to Google Fonts.
The browser selects needed subsets using the original Unicode ranges; it does
not need to download the entire collection for each page.

## Noto Sans SC

- Official CSS: https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400..600&display=swap
- Google CDN version: `notosanssc/v40`; variable normal weight `400 600`.
- Files: `NotoSansSC-001.woff2` through `NotoSansSC-101.woff2`.
- Total: **4,516,508 bytes** (4.52 MB / 4.31 MiB); largest: **76,800 bytes**.
- No repeated CDN URLs, no single large TTF, no locally modified font binaries.
- `NotoSansSC-upstream.css` preserves the source CSS for provenance only. It is
  not linked by the running app and does not trigger external font requests.
- `NotoSansSC-manifest.json` records the exact source URL, Unicode range, byte
  length and SHA-256 digest of each local file, plus the request User-Agent.
- `OFL-notosanssc.txt` is the complete upstream license from
  https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt.

Coverage means the complete **returned CSS distribution**, not the complete
upstream Noto font or all Unicode Chinese characters. The union of declared
Unicode ranges contains 15,605 code points, including 12,258 in U+4E00–U+9FFF.
This is a CSS range count, not a decoded glyph inventory. Missing characters
continue through the system fallback stack (PingFang SC, Microsoft YaHei,
Noto Sans CJK SC, sans-serif); no claim is made that every extension ideograph
uses Noto Sans SC. Runtime Latin, Chinese and code fonts are locally served.

## Integration and verification

Streamlit 1.63.0 explicitly supports `unicodeRange` in `theme.fontFaces`.
The 101 tables in `.streamlit/config.toml` map each original Unicode range to
`app/static/fonts/NotoSansSC-NNN.woff2`; the two existing Latin font tables remain.
`server.enableStaticServing = true` enables these same-origin URLs. The theme's
font-family stack no longer contains a Google Fonts URL.

2026-09-09 local deterministic checks passed: Python `tomllib` and Streamlit's
own `config.get_option('theme.fontFaces')` parsed all 103 tables; all 101 Noto
range/URL mappings matched the saved upstream CSS; all WOFF2 signatures, encoded
file lengths and SHA-256 digests matched the manifest; each file is below 500 KB
and the Noto collection is below 8 MB. `.venv/Scripts/python.exe -m pytest
tests/test_frontend.py -k font -q`: 1 passed, 33 deselected.

After the integrator started the existing app at `http://127.0.0.1:8501`, an
HTTPX GET check of all 101 local Noto URLs passed: HTTP 200, WOFF2 bytes and
SHA-256 identical to the manifest, and `X-Content-Type-Options: nosniff`.
This Windows Streamlit server reports `Content-Type: application/octet-stream`
for these font responses; no server MIME override was introduced. The integrator
must still confirm browser font loading/selection rather than infer it from 200.
`black --check frontend/accounts.py` and `flake8 frontend/accounts.py` both passed
after updating its font explanation; no other business behavior changed here.

Visual/glyph selection verification belongs to the integration browser gate;
these static checks alone do not prove which font the browser used per glyph.

Font source discovery:
https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap

Licenses:
https://raw.githubusercontent.com/google/fonts/main/ofl/manrope/OFL.txt
https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/OFL.txt
https://raw.githubusercontent.com/google/fonts/main/ofl/notosanssc/OFL.txt
