# FINN: a promise ledger for investors

FINN keeps a ledger of what each company's management promised on its earnings calls
(growth, margins, capacity, orders, dates) and checks every promise against what was
actually reported. That ledger is how FINN decides what matters:

- **Push.** Results are always shown, with headline numbers checked against open
  promises. Any filing that bears on a promise comes next. After that come the filing
  categories you care about. Everything else is buried, counted and one tap away. Price
  or volume moves beyond your thresholds are paired with the filings that explain them,
  and a move with no filing behind it is shown on its own.
- **Pull.** Type any NSE symbol. FINN reads the last five earnings-call transcripts,
  lists the promises, follows each one through later calls (repeated, raised, cut,
  delivered, or quietly dropped), and checks the numeric ones against exchange-reported
  results.

Primary sources only: exchange filings, earnings-call transcripts and exchange-reported
numbers. No news, broker notes or model memory.

---

## Day 1: prove the data plumbing (do this first)

The build environment could not reach NSE, BSE, Yahoo or screener.in, so every
fetcher has been tested only against fictional fakes. Before anything else, check them
from your own machine:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-pipeline.txt
export GEMINI_API_KEY=...        # free key from https://aistudio.google.com/apikey
python -m pipeline.doctor INFY
```

On Windows (PowerShell), from the folder that contains this README:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass   # lets this window run the activate script
.\.venv\Scripts\Activate.ps1
pip install -r requirements-pipeline.txt
$env:GEMINI_API_KEY = "paste-your-key-here"
$env:PYTHONUTF8 = "1"
python -m pipeline.doctor INFY
```

Each line should say PASS. If a parser fails, the raw page is saved in `dev/samples/`.
Fix the parser against that file. The screener and BSE parsers are the most likely to
need a tweak.

Then build one company and look at it:

```bash
python -m pipeline.run --mode full --only INFY
python dev/server.py            # open http://localhost:8000 on your phone or desktop
```

Then the whole portfolio. The first run is paced to stay inside the free tier
(about 15 requests a minute), so it takes 15–25 minutes:

```bash
python -m pipeline.run --mode full
```

## Deploy

1. Push this repo to GitHub as a public repository, including `public/data` from your
   first run.
2. In the repo settings, add the Actions secret `GEMINI_API_KEY`, and under Actions set
   workflow permissions to "Read and write" so the data job can commit.
   `.github/workflows/finn-data.yml` then refreshes filings hourly during market hours
   and runs a full refresh after the close.
3. In Vercel, import the repo with framework preset "Other". Add the environment variable
   `GEMINI_API_KEY` and deploy. `vercel.json` serves `public/` and runs `api/*.py` as
   Python functions.
4. Check `https://<your-app>/api/company?t=INFY` returns JSON, then open the app on a
   phone.

If the exchanges block GitHub's servers, refresh from a laptop instead (Windows):
`powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1` runs the pipeline and
pushes the data in one step.

## How it is built

```
GitHub Action (hourly)                                    Vercel
  pipeline/run.py                                           public/  static app (no build step)
    screener.in  -> quarterly numbers, transcript links     api/company.py          any NSE ticker
    BSE / NSE    -> filings                                 api/ledger_step.py      reads one call
    Yahoo        -> end-of-day price and volume             api/ledger_finalize.py  rules + verdict
    Gemini       -> reads PDFs (cached forever)
  writes public/data/*.json  --commit-->  redeploy
```

| Step | How | Why |
|---|---|---|
| Classify filings | Rules on exchange labels and headlines; one batched model call for leftovers | Most filings need no model at all |
| Read transcripts, results, management-change filings | `gemini-3.5-flash-lite` (free tier, ~500/day) | Bulk extraction; the cheap model is enough |
| Promise verdicts and credibility read | `gemini-3.8-flash` (free tier, ~20/day), falls back to Flash-Lite | The one step that needs judgment, once per company |
| Arithmetic (QoQ, YoY, EBITDA, margins, promise checks) | Plain Python | Models extract numbers; code does the maths |
| Status of each promise | Explicit rules in `finn/ledger.py` | Explainable; the model may override only with a stated reason |

Every model output is cached by (task, document, prompt version) in `public/data/cache`,
and the API reads that cache from the deployed bundle. So no document is ever read
twice. Routes can be overridden with `FINN_MODEL_<TASK>`. Usage per run is shown in the
app under Settings.

## Tests

```bash
pytest                                   # parsers, maths, ledger rules, model routing, API, full pipeline
node --test tests/js/logic.test.mjs      # the digest's ranking and move pairing in the browser
python dev/make_fixtures.py && python dev/server.py --fake   # open /?fixtures (fictional data)
```

`dev/fakes.py` contains fictional companies, filings and a scripted model, so the real
pipeline and API run end to end offline. None of it is deployed.

## Layout

```
finn/            library: sources, Gemini client, classifier, ledger, triage, maths
api/             Vercel functions for on-demand research
pipeline/        run.py (scheduled refresh), doctor.py (day-1 checks)
public/          the app: index.html, css/, js/ (no framework, no build)
config/          portfolio and announcement categories
tests/, dev/     tests, fakes, dev server, screenshot script
```
