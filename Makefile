SHELL := /bin/bash
ENGINE := cd engine &&
WEB := cd web &&

# One value from the root .env (not sourced: it isn't shell syntax). The shell env wins, as in
# the engine's settings. Like python-dotenv: optional `export ` and quotes, CRLF, last one wins.
dotenv = $(shell cat .env 2>/dev/null | tr -d '\r' | \
	sed -n "s/^\(export \)\{0,1\}$(1)=[\"']\{0,1\}\([^ \#\"']*\).*/\2/p" | tail -n 1)
DEV_API_PORT := $(or $(GLINT_API_PORT),$(call dotenv,GLINT_API_PORT),8000)
DEV_WEB_PORT := $(or $(PORT),$(call dotenv,PORT),3000)

.PHONY: setup check test perf e2e contracts docs dev dev-api dev-web fixtures synthetic \
	schedule-install schedule-remove

setup:  ## uv sync + npm ci
	$(ENGINE) uv sync
	$(WEB) npm ci

check:  ## lint, typecheck and tests for engine + web
	$(ENGINE) uv run ruff check .
	$(ENGINE) uv run ruff format --check .
	$(ENGINE) uv run pyright
	$(ENGINE) uv run pytest -m "not live and not perf" -q
	$(WEB) npx tsc --noEmit
	$(WEB) npx eslint .
	$(WEB) npx vitest run

test:  ## tests only
	$(ENGINE) uv run pytest -m "not live and not perf" -q
	$(WEB) npx vitest run

perf:  ## timing budgets (CI runs these; locally, run on a quiet machine)
	$(ENGINE) uv run pytest -m perf -q
	cd web && GLINT_PERF=1 npx playwright test --grep @perf --workers 1

e2e:  ## Playwright against mock mode (needs `npx playwright install chromium` once)
	$(WEB) npx playwright test

contracts:  ## export OpenAPI + Screen JSON Schema, then regenerate TS types
	$(ENGINE) uv run python scripts/export_openapi.py
	$(WEB) npm run gen:types

docs:  ## generate docs/metrics.md from config/metrics.yaml
	$(ENGINE) uv run python scripts/gen_metrics_doc.py

dev:  ## API + web (real mode) on GLINT_API_PORT / PORT; one Ctrl-C stops both, as does either exiting
	@trap 'exit' INT TERM; trap 'kill $$api $$web 2>/dev/null; wait' EXIT; \
	(cd engine && exec uv run glint serve --port $(DEV_API_PORT)) & api=$$!; \
	(cd web && PORT=$(DEV_WEB_PORT) NEXT_PUBLIC_GLINT_MOCK=0 \
		NEXT_PUBLIC_GLINT_API_URL=http://localhost:$(DEV_API_PORT) exec npm run dev) & web=$$!; \
	echo "glint dev: API http://localhost:$(DEV_API_PORT) · web http://localhost:$(DEV_WEB_PORT)"; \
	while kill -0 $$api 2>/dev/null && kill -0 $$web 2>/dev/null; do sleep 1; done; \
	echo "glint dev: a server exited; stopping the other" >&2; exit 1

dev-api:  ## API on $${GLINT_API_PORT:-8000}
	$(ENGINE) uv run uvicorn glint.api.app:create_app --factory --reload --port $${GLINT_API_PORT:-8000}

dev-web:  ## UI on $${PORT:-3000}
	$(WEB) PORT=$${PORT:-3000} npm run dev

fixtures:  ## rebuild real SEC fixtures (network; needs GLINT_SEC_USER_AGENT in .env)
	$(ENGINE) uv run glint fixtures sec

synthetic:  ## rebuild the synthetic build + web mocks
	$(ENGINE) uv run glint fixtures synthetic

SCHEDULE_LABEL := com.glint.refresh
SCHEDULE_PLIST := $(HOME)/Library/LaunchAgents/$(SCHEDULE_LABEL).plist

schedule-install:  ## launchd: `glint refresh` daily at 09:15 London (optional; scripts/launchd)
	@[[ "$$(readlink /etc/localtime)" == *Europe/London ]] || \
		echo "warning: this Mac's time zone isn't Europe/London; 09:15 is local time"
	@mkdir -p "$(HOME)/GlintData/logs" "$(HOME)/Library/LaunchAgents"
	sed -e "s|__REPO__|$(CURDIR)|g" -e "s|__UV__|$$(command -v uv)|g" -e "s|__HOME__|$(HOME)|g" \
		scripts/launchd/$(SCHEDULE_LABEL).plist.template > "$(SCHEDULE_PLIST)"
	plutil -lint "$(SCHEDULE_PLIST)"
	-launchctl bootout gui/$$(id -u) "$(SCHEDULE_PLIST)" 2>/dev/null
	launchctl bootstrap gui/$$(id -u) "$(SCHEDULE_PLIST)"
	@echo "installed: glint refresh at 09:15 daily from $(CURDIR); logs in ~/GlintData/logs"

schedule-remove:  ## remove the launchd job
	-launchctl bootout gui/$$(id -u) "$(SCHEDULE_PLIST)"
	rm -f "$(SCHEDULE_PLIST)"
