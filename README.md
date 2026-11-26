# Glint

Glint sifts every US-listed company that files with the SEC. You can see why each one passed,
how close the near misses came, and where every number came from.

*Educational tool. Not investment advice.*

## Quickstart: real data

Needs [uv](https://docs.astral.sh/uv/), Node 22+, about 8 GB of free disk and a few hours for the
first download. Timings are from an Apple M3 with 8 GB of RAM on 2026-10-31 and leave out download time,
which depends on your connection.

```bash
git clone <repo-url> glint && cd glint
cp .env.example .env            # set GLINT_SEC_USER_AGENT to your name and email (SEC requires it)
                                # optional: MASSIVE_API_KEY for prices (else yfinance, labelled)
make setup                      # uv sync + npm ci                                   ~1 min
cd engine
uv run glint ingest sec         # SEC bulk files (~5.8 GB on disk) + extract          ~5 min + download
uv run glint ingest prices --backfill 300
                                # 300 sessions of daily bars; one call per session, so ~60 min
                                # on the free Massive plan (5 calls/min)
uv run glint refresh            # build-then-swap: financials, metrics, flags, publish  ~10 min
cd ..
make dev                        # API on GLINT_API_PORT, UI on PORT (8000 / 3000 by default)
```

Open <http://localhost:3000>. The line under the header shows the SEC bulk file and the price
close the build used. One Ctrl-C stops both servers.

Check the build:

```bash
cd engine
uv run glint smoke              # every preset, the Appendix D companies, search; exit 1 on failure
uv run glint smoke --perf       # also times the §5.10 API budgets
uv run glint audit              # outliers and null rates to review
```

Later refreshes: `uv run glint refresh` downloads only what changed, then rebuilds.
`uv run glint refresh --no-download` rebuilds from the files already on disk. Saved screens and
watchlists live outside the builds, so a refresh never touches them.

### Notes

- **Ports:** `make dev` reads `GLINT_API_PORT` and `PORT` from your shell, then from `.env`, and
  points the UI at that API port itself. `NEXT_PUBLIC_GLINT_API_URL` in `.env` is only for
  `make dev-web` on its own.
- **Raw files** go to `GLINT_RAW_DIR` (`~/GlintData/raw`), shared by every checkout. **Builds** go
  to `GLINT_DB_DIR` (`./data`), one per checkout.
- **Run glint from `engine/`** with `uv run`, so it uses this checkout's `engine/.venv`. If your
  editor exports `VIRTUAL_ENV` for another checkout, `unset VIRTUAL_ENV` first. Otherwise
  relative paths resolve into that checkout (see `docs/decisions/WT-09.md`).

## Quickstart: synthetic data (no downloads)

```bash
cp .env.example .env
make setup
make synthetic                  # a synthetic build + web mocks
make dev                        # the UI shows a SYNTHETIC DATA banner
```

Or run the UI with no API at all: `NEXT_PUBLIC_GLINT_MOCK=1 make dev-web`.

## Tests

```bash
make check                      # lint, typecheck and tests (engine + web)
make e2e                        # Playwright, mock mode
cd web && npx playwright test -c e2e/real   # Playwright on your real build (local only)
```

`e2e/real` reuses a running `make dev`, or starts one. The UI timings in `e2e/real/perf.spec.ts`
are opt-in (`GLINT_E2E_PERF=1`) and need a production build, because `next dev` is several times
slower. Run `uv run glint serve --no-reload` in `engine/`. Then, in `web/`, run `npm run build &&
npm run start` with `NEXT_PUBLIC_GLINT_MOCK=0` and `NEXT_PUBLIC_GLINT_API_URL` set, and finally
`GLINT_E2E_PERF=1 npx playwright test -c e2e/real`.

## Keyboard

Press `?` in the app for the same list. Single-letter keys do nothing while you type in a field.

| Key | What it does |
|---|---|
| `/` or `⌘ K` (`Ctrl K`) | Search companies, presets, filters and actions |
| `f` | Add a filter |
| `j` / `k` | Next / previous result (also inside the drawer) |
| `↑` / `↓` | Next / previous result when a row has focus |
| `Home` / `End` | First / last result |
| `Enter` | Open the drawer for the focused row |
| `o` | Open the full company page for the focused row |
| `x` | Pin or unpin the focused row or the open company for comparison (up to 3) |
| `c` | Compare the pinned companies |
| `Esc` | Close the drawer, palette, picker, menu or sheet |
| `?` | Show the shortcut list |

On a histogram's threshold handle: `←` / `→` (or `↓` / `↑`) step one bin, with `Shift` ten bins;
`Home` / `End` jump to the lowest / highest value.

## Layout

- `engine/`: Python package `glint` (CLI: `uv run glint --help`)
- `web/`: Next.js UI
- `config/`: metric registry, XBRL concepts, sectors, thresholds, presets
- `contracts/`: generated OpenAPI + Screen JSON Schema (`make contracts`)
- `docs/`: spec, design, worktree briefs, status, decisions

Start with `CLAUDE.md`, then `docs/SPEC.md` and `docs/worktrees/README.md`.
