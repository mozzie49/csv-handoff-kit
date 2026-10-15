# Browser all-text XLSX trial

A focused, browser-only entry point for CSV Handoff Kit. Choose a UTF-8 CSV or click **Try a fictional sample**, then download an XLSX with one `Data` sheet. Every field is stored as an actual string with Text number format, including formula-looking strings. No leading apostrophe is added.

The browser page does **not** implement the CLI's numeric-column choices, risk receipts, contracts, keyed matching, or return verification. The existing Python CLI is unchanged. This is not a promise that arbitrary spreadsheet applications preserve every value through future edits/saves, or a way to recover digits already lost upstream.

## Run a local preview

For development only, use Node.js 22+ (CI uses 24):

```sh
cd browser
npm ci
npm run build
npm run serve
```

Open the printed `http://127.0.0.1:4175` address. `dist/` is a static site; a host can serve that folder without Node.js, Python, a backend, or runtime CDN dependencies. Relative asset paths support a project subdirectory. Opening `index.html` with `file://` is not supported because browsers restrict module workers. There is no deployment workflow in this change; publishing requires a separate reviewed action.

## Supported subset

- Valid UTF-8, optional one initial UTF-8 BOM. Invalid bytes fail; they are never replaced or guessed. A second or internal U+FEFF remains data
- Explicit comma, semicolon, tab, or pipe separator. It is never inferred
- Standard double-quoted fields, with doubled double quotes inside fields. Quoted delimiters and CR/LF/CRLF are preserved. Mixed outer CR/LF/CRLF endings are supported
- Strict grammar: bare quotes inside unquoted fields, spaces before opening/after closing quotes, and suffixes after closing quotes are rejected. This is intentionally narrower than some Python `csv.reader` cases
- Unique, nonempty exact headers; rectangular records. Physical blank lines are rejected, including in one-column CSVs. Quote an intentional empty field as `""`
- No trimming, case folding, number/date inference, Unicode normalization, formula evaluation, or external link generation
- Up to 10 MiB input, 10,000 rows including header, 256 columns, 250,000 cells, and 32,767 UTF-16 code units per field
- XML-disallowed controls and lone surrogates are rejected. Tab, CR, LF, and supplementary Unicode such as emoji are supported
- Generated XLSX is capped at 10 MiB; XML parts at 20 MiB each / 40 MiB total. Extremely compressible parts use stored ZIP to avoid >1,000× expansion ratios. Inputs within their limits may still require splitting if expanded/output limits are exceeded

OOXML escape-like literals use the CLI writer's overlapping-token escape rule. CR uses a character reference so XML newline normalization does not change it. All cells, including empty ones and headers, use `inlineStr`; there are no formula or hyperlink elements. Static package parts match the existing CLI writer.

## Privacy and lifecycle

Input is read with the File API and transferred to a dedicated worker. Conversion uses no fetch/XHR/WebSocket calls, analytics, remote fonts, or runtime CDNs. The fictional sample is bundled. The page's meta CSP prohibits page connections and form submission; it does not extend to a URL-loaded worker. The preview server also sends a CSP response header for the worker. A production host that supports response headers should retain that header. The bundled worker itself contains no network calls. Processing is local; page/code requests still go to its host. A trusted host and browser (including extensions) are prerequisites.

The page does not use persistent storage. Cancel, Clear, changing the separator, and selecting another file invalidate the current job and result. Superseded workers are terminated and object URLs are revoked. Downloads contain original values and should be treated as sensitive whenever the CSV is sensitive. No input is included in a URL or sent to GitHub.

Preview text is DOM text, not HTML; it shows at most 5 data rows, 6 columns, and 100 Unicode code points per cell. This truncation is display-only. The workbook contains full accepted values.

## Tests

```sh
# Pure parsing, boundaries, XML/ZIP generation, and static build:
npm test
npm run build
# Existing CLI oracle + direct XML checks + independent openpyxl 3.1.5:
python -m pip install -r ../requirements-dev.txt
npm run test:readback
# Real browser download, state/cancellation, privacy-request and layout checks:
npx playwright install --with-deps chromium
npm run test:e2e
```

`npm run check` combines the core, build, and independent-reader checks. `.github/workflows/browser.yml` also runs real Chromium tests, then retains screenshots/traces and the static build as CI artifacts. The existing Python workflow continues unchanged.

Local validation on 2026-10-15: 33 JavaScript core tests passed; two generated fixtures passed CLI, direct OOXML, and openpyxl ordinary-value/type checks; all 91 existing CLI tests passed. Local Chromium could not start due an environment process-socket restriction. The separately available cloud browser could not reach the isolated local preview. Those local restrictions were followed by real remote browser validation below.

Remote validation on 2026-10-15: [Chromium CI run 38732909788](https://github.com/mozzie49/csv-handoff-kit/actions/runs/38732909788) passed all **6 browser tests** for `db07bd33f1f02702b86af89fd222c7868053b066`, including actual download, malformed/oversize rejection, in-flight cancellation/replacement, repeated use/reload, pending reads, URL cleanup, and project-subdirectory hosting. The earlier run exposed a test-harness worker-cache issue; cancellation and replacement now run in isolated contexts and still require proof that each network gate was entered. No product code changed for that test correction.

The run's 390px/mobile and 1280px/desktop screenshots were visually reviewed without clipping or overlap blockers. Its actual downloaded fictional workbook was independently read with openpyxl: all 24 expected values matched exactly, with string storage and Text format throughout. SHA-256: `1e560a06c156ae05bc42119e6cf8ab4f64cfee86f7b5d36d32fa8ad39a676c26`. All seven static build files matched the reviewed local build byte-for-byte. These are synthetic tests, not a customer trial or a broad spreadsheet-application compatibility claim. [Draft PR #3](https://github.com/mozzie49/csv-handoff-kit/pull/3) records the final-commit checks; merge and deployment remain separate actions.

As in the CLI's existing validation notes, openpyxl exposes an escape prefix for some inline OOXML-looking literals; those cases are checked against the CLI decoder and direct XML instead. Microsoft Excel and stable LibreOffice have not been tested for this browser build.

## Dependencies and licenses

Runtime dependencies are pinned to the official npm registry: `csv-parse` 7.0.3 (MIT) and `fflate` 0.8.3 (MIT). esbuild and Playwright are development-only. The parser embeds Buffer/base64/IEEE754/is-buffer polyfills; their complete applicable notices are retained too (see `licenses/PROVENANCE.md`). Build-time notice/hash checks require a fresh provenance review on parser upgrades. Built files include the full project `LICENSE`, `THIRD-PARTY-LICENSES.txt`, and `NOTICE-PROVENANCE.txt`; no dependency is loaded from a CDN. The source, fixtures, and UI are MIT as part of this repository.

This browser trial was written with AI assistance. It is an implementation/validation experiment, not evidence of adoption or conversion performance.
