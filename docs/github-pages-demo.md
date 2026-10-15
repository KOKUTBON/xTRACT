# GitHub Pages demo

The static demo uses the existing operator portal with a browser adapter instead of
`/api/*` network requests. The normal Python server still uses the live API.
Nothing is published by building locally or by pushing: the Pages workflow runs
only when manually dispatched.

## Preview locally

From the repository root, with Python 3:

```sh
python3 scripts/build_demo.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory dist
```

Open <http://127.0.0.1:8765/demo/>. This previews the app under a subdirectory,
like a GitHub project page. Do not open `index.html` directly with `file://`, since
browser modules and fixture loading require HTTP.

The complete publishable site is `dist/demo/` (ignored by Git). Assets and modules
use relative paths, so the artifact works at `/xTRACT/`, `/metadata-leggibili/`,
or a custom domain root without changing a base URL. Upload only this generated
folder when using another static host.

## Demo behavior

- Three fictional text documents show review and registered states. A sample
  exception can be resolved. The initial workspace opens automatically.
- Search, workflow filters, field edits/confirmation, review completion/reopening,
  discard, simulated reprocessing/registration, source preview, audit history,
  and downloads work without a backend.
- The assistant gives scripted, cited responses to the suggested questions.
- UTF-8 `.txt` files up to 1 MiB can be read in the browser. Uploaded fields start
  empty for manual entry; the demo does not perform OCR or metadata extraction.
  PDF/image processing remains a feature of the local server.
- Document changes and uploads live in memory only. Reload or **Reset demo** to
  restore the sample documents. Language/theme/operator preferences use the
  portal's existing browser storage. No API token is needed.
- Downloaded files are labeled as demo data. Bulk exports include validated or
  registered documents; JSONL's OCR option adds source text.

The fixture is `apps/operator-portal/demo/fixtures.json`; the adapter is
`apps/operator-portal/modules/demo.js`. The build injects a `xtract-mode=demo`
meta tag. The source portal has no demo flag, so server mode remains the default.

## Verify

Use Node.js 22.7+ (or Node.js 24) and Python 3:

```sh
node --test tests/demo.test.mjs
python3 scripts/build_demo.py
```

Adapter tests cover validation, state changes, search, uploads, reset isolation,
source previews, assistant boundaries, and all export formats. Preview the build
at the subdirectory URL above to inspect the full UI.

## Publish later, when ready

1. Commit and push the prepared source and workflow to your chosen repository.
2. In the repository's **Settings → Pages**, choose **GitHub Actions** as the source.
3. In **Actions**, select **Publish Pages demo (manual)** and **Run workflow** on
   the branch you want to publish. This explicit action builds and deploys the demo.
4. The deployment job shows the resulting Pages URL. For a repository named
   `xTRACT` owned by `reiidoda`, it will be `https://kokutbon.github.io/xTRACT/`.

The workflow has no push or pull-request deployment trigger. It has not been run
as part of this preparation. No GitHub repository settings need changing until
publication.
