# TrialBox public website

Static site (plain HTML/CSS and a small vanilla JS file). No server, no external requests, no CDN: the charts are HTML
and inline SVG rendered at build time, so the pages work offline, on GitHub Pages and on Netlify. Every link is
relative, so the site works under `https://zandis.github.io/Auto-GPT/` as well as at a domain root.

```sh
cd trialbox
python3 tools/build_site.py                 # refresh data that is available locally, render to build/site/
python3 tools/build_site.py --no-refresh    # render only from site/data (what CI / Netlify run)
.venv/bin/python tools/build_site.py --refresh-demo   # also re-run the stub cascade for the demo data + PDF
python3 -m http.server -d build/site 8000   # preview at http://127.0.0.1:8000/
```

The build only uses the Python standard library (`--refresh-demo` needs the project venv). It refuses to publish if
any generated file matches an API-key, private-key or private-IP pattern.

## Layout

| Path | What |
| --- | --- |
| `templates/layout.html` | page shell: banner, nav, language switch, footer |
| `pages/*.html` | page bodies with `{{ slot }}` placeholders filled by `tools/build_site.py` |
| `pages/index.{en,ja,zh-TW}.html` | landing page in English, Japanese, Traditional Chinese → `index.html`, `ja/`, `zh-tw/` |
| `assets/` | `style.css`, `app.js`, favicon, `screens/*.png` (console tour), `downloads/DL1_GZQO.pdf` |
| `i18n/criteria_ja.json` | Japanese chart labels for criterion labels (falls back to English) |
| `i18n/site_text.json` | pipeline diagram text (en/ja/zh-TW), screenshot captions, banner text |
| `data/*.json` | the data the pages render (below); copied to `build/site/data/` for download |

The demo, screenshot and report pages carry an **EN / 日本語** toggle: chart titles, axis notes, criterion labels and
headings switch to Japanese (`html[data-lang]`, remembered per browser; `?lang=ja` selects it from a link).

## Data files

All public, synthetic or open data. Nothing hospital-internal, no credentials.

### `data/demo_gzqo_site_a.json` (schema `trialbox.site.demo@1`)

Written by `--refresh-demo` from `tools.cascade_e2e --source tests/fixtures/synthetic_patients/site-a --trial GZQO`
(stub model, no network). Only the **released** D1 object of the DL-1 pack (`dl1/DL1_GZQO.json`, disclosure profile
`dc.sponsor`, k = 11, rounded to 5) and the run's pass/fail checks are kept. Not copied: `DL1_*_INTERNAL_exact.json`,
D3 stage counts, tiers, final list, traces, ledgers. Recall-certificate stratum counts and known-positive `r` are
additionally suppressed below 11 on the site. The PDF is copied without its INTERNAL released-vs-exact appendix page.

### `data/open_data_mimic.json` (schema `trialbox.site.open_data@1`)

Released funnels for EMPULSE and STARRT-AKI on the MIMIC-IV Clinical Database Demo on FHIR (ODbL), from
`.cache/open_data/report.json` (`make eval-public`). The `raw` blocks are dropped.

### `data/bakeoff.json` (schema `trialbox.site.bakeoff@1`)

Normalised from the newest `eval/bakeoff/results/<YYYY-MM-DD>/`:

* `summary.json` if it exists → `status: "final"`;
* else `metrics_*.json` + `cascade_*.json` → `status: "preliminary"`;
* nothing found → `status: "pending"` (the report page says "results pending").

**Expected `summary.json` fields.** Either `{"models": [ ... ]}` / `{"builds": [ ... ]}` (list, as
`tools/bakeoff_live.py` writes it) or `{"models": {build_id: {...}}}` (or the build map at the top level). An entry with
a `variant` (e.g. `trialgpt`: TrialGPT's prompt on a subset) becomes its own row `<build_id>__<variant>` and is left
out of the headline tiles; a top-level `cascade` list is matched to rows by `build_id`. Each model entry is read like a `metrics_<build>.json` file:

| Field | Type | Used for |
| --- | --- | --- |
| `build_id` (or `id`) | string | key, matching `cascade_<build_id>.json` |
| `model_name` | string | label (a trailing "(hosted)" is dropped) |
| `provider_pin.provider`, `provider_pin.model` (or `provider`, `model`) | string | provider column |
| `by_lang.<lang>` with `lang` in `en`, `zh-TW`, `ja`, `mixed` (or a flat block + `lang`) | object | metrics per note language |
| … `n`, `accuracy`, `macro_f1`, `false_block_rate`, `false_block_upper95`, `block_recall`, `agreement_with_gpt4`, `invalid_rate`, `cost_per_1k_usd`, `latency_p50_s`, `latency_p95_s` (also `lenient_accuracy`, `evidence_f1`, `cost_usd`, `latency_mean_s`) | number (rates 0–1) | charts and tables |
| … `gpt4_reference_same_items` | metric block | "TrialGPT GPT-4 (recorded label)" reference bar |
| `cascade` (optional; else `cascade_<build_id>.json`) with `passed`, `certificate_status`, `calls`, `schema_valid`, `cost_usd`, `latency_ms_mean`, `failed_checks`, `gateway_refusals` | object | end-to-end table |

Top-level `recommendation`, `winner`, `ranking`, `verdict`, `notes`, `weights` are carried over when present. A build
id or name containing `reference` is drawn grey as a reference system. Cascade funnels and stage counts (D3) are not
copied.

### `data/trialgpt_comparison.json` (schema `trialbox.trialgpt_comparison@1`)

The slot the TrialGPT comparison team fills by hand (the build creates the empty template if missing and never
overwrites it). With `systems` empty the report page shows "comparison pending".

```json
{
  "schema": "trialbox.trialgpt_comparison@1",
  "status": "final",                       // "pending" | "draft" | "final"
  "updated": "2026-11-01",
  "owner": "comparison team",
  "notes": "free text shown under the table",
  "dataset": {"name": "TrialGPT-Criterion-Annotations (NCBI)", "url": "https://huggingface.co/datasets/ncbi/TrialGPT-Criterion-Annotations",
              "split": "SIGIR", "n_items": 1015, "licence": "see dataset card"},
  "systems": [
    {
      "id": "trialgpt-gpt4",
      "label": "TrialGPT (GPT-4, paper)", "label_ja": "TrialGPT（GPT-4、論文）",
      "kind": "trialgpt",                  // "trialgpt" | "trialbox" | "reference"
      "model": "gpt-4",
      "source": "where the numbers come from (paper table, run id, commit)",
      "metrics": {"accuracy": 0.0, "macro_f1": 0.0, "false_block_rate": 0.0, "block_recall": 0.0,
                  "cost_per_1k_usd": null, "latency_p50_s": null}
    }
  ],
  "tasks": [                               // optional: other tasks, e.g. trial ranking
    {"task": "trial ranking (TREC 2021)", "metric": "NDCG@10", "values": {"trialgpt-gpt4": 0.0, "trialbox-gemma": 0.0}}
  ]
}
```

(Placeholder values; comments are for the reader, the file is plain JSON.) Rates are fractions 0–1; unknown values are `null`.

## Hosting

**Netlify.** `trialbox/netlify.toml` sets everything: in the Netlify UI choose the repository, set *Base directory* to
`trialbox` (the toml then gives build command `python3 tools/build_site.py --no-refresh` and publish directory
`build/site`). No environment variables are needed.

**GitHub Pages.** Pages cannot run the build itself, so use an Actions workflow (Settings → Pages → Source: *GitHub
Actions*) and add `.github/workflows/trialbox-site.yml`:

```yaml
name: trialbox-site
on:
  push:
    branches: [master]
    paths: ["trialbox/site/**", "trialbox/tools/build_site.py"]
  workflow_dispatch:
permissions: {contents: read, pages: write, id-token: write}
concurrency: {group: pages, cancel-in-progress: true}
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: {name: github-pages, url: "${{ steps.deployment.outputs.page_url }}"}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: python trialbox/tools/build_site.py --no-refresh
      - uses: actions/upload-pages-artifact@v3
        with: {path: trialbox/build/site}
      - id: deployment
        uses: actions/deploy-pages@v4
```

The site is then at `https://zandis.github.io/Auto-GPT/`. The build writes `.nojekyll` and a `404.html`.
Commit `site/data/*.json`, `site/assets/screens/` and `site/assets/downloads/` so CI renders the same data.
