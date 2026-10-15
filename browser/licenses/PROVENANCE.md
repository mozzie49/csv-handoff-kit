# Runtime notice provenance

Reviewed 2026-10-15. These are license notices, not extra runtime dependencies.

- csv-parse 7.0.3: official npm package, pinned in package-lock.json; `dist/esm/sync.js` SHA-256 `be7c2e7e5769134ee9adceece0516979bb930efb81b6a8c8421ec6bb98941bc3`. Upstream gitHead `594c6469c4a7376c1048d13c47859c2f91674206`. The build refuses an unreviewed change to this embedded-polyfill bundle
- fflate 0.8.3: official npm package, pinned in package-lock.json; full package LICENSE copied by build
- csv-parse's published ESM sync bundle contains the Buffer implementation, base64 conversion, IEEE754 read/write, and is-buffer code. Its development build declares rollup-plugin-node-builtins ^2.1.2 and rollup-plugin-node-globals ^1.4.0; their declared dependencies resolve to buffer-es6 4.9.3
- buffer-es6 4.9.3: fetched as the official npm tarball `https://registry.npmjs.org/buffer-es6/-/buffer-es6-4.9.3.tgz`; SHA-256 `c7e26d1d1e720d03906dec97d00c3a79d8dbcd0128aaf511684452f0fd5c4660`. Its `base64.js`, `ieee754.js`, `index.js`, and `is-buffer.js` correspond to the published csv-parse ESM bundle. Full tarball LICENSE retained, including Feross/contributors and the original Fair Oaks Labs IEEE754 terms
- Additional base64-js notice retained from `https://raw.githubusercontent.com/beatgammit/base64-js/master/LICENSE` (Jameson Little, MIT). buffer-es6 vendors this implementation but does not state its original base64-js package version
- Additional is-buffer notice retained from `https://raw.githubusercontent.com/feross/is-buffer/master/LICENSE` (Feross Aboukhadijeh, MIT). buffer-es6's source explicitly identifies that origin; its original package version is not stated
- The project's full root LICENSE is copied to the distribution too

Development-only packages (esbuild and Playwright) are not shipped as runtime code. Their own package licenses remain in the development install. A dependency upgrade must review embedded code provenance again rather than merely updating the expected hash.
