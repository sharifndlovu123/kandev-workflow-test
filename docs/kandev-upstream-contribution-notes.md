# Notes for contributing `workflow-diagram.py` upstream to kdlbs/kandev

Pinned reference, fetched 2026-09-10 from `github.com/kdlbs/kandev`
(`CONTRIBUTING.md`, `docs/public/extending-kandev.md`). Summarized here so the
contribution decision doesn't need to be re-researched — re-fetch before
acting if this gets stale, since upstream can change its own rules.

## The rule that matters most for this tool

> **Before opening a PR.** Discuss a large architectural change in an issue
> before implementation or PR creation. A large change includes a new
> subsystem [...] Describe the problem, proposed direction, affected
> boundaries, alternatives, and migration or compatibility risks in the
> issue. Wait until maintainers have discussed the direction before opening
> the PR. **If an agent is preparing the change, it must stop and report
> missing discussion instead of opening the PR.**

`workflow-diagram.py` is a new subsystem by their own definition — a
standalone HTTP server, a new visualization surface, reading their sqlite DB
directly from outside their Go backend's own data-access layer. **This needs
a GitHub issue opened first, with maintainer buy-in on direction, before any
PR** — not a PR straight away. This document, the screenshots, and the
companion guide (`docs/live-workflow-diagram-guide.md`) are prepared as the
concrete material for that issue, not as a PR in themselves.

## Why "add the file to their repo" isn't the natural shape here

Kandev's own codebase is Go (`apps/backend`) + TypeScript
(`apps/web`) — `make fmt`/`make typecheck`/`make test`/`make lint` all
target that stack. `docs/public/extending-kandev.md` describes how real
features get added — as one of six defined "extension seams" (Agent,
Executor, Provider, Workflow/MCP, Plugin, Settings/workbench), each owning
its behavior at a specific point in their Go backend or web frontend, with
its own completion checklist (discovery/config, durable state, runtime
behavior, recovery, security, tests, packaging, public docs).

`workflow-diagram.py` fits none of those seams — it's a read-only, stdlib-
only, out-of-process Python script that happens to query the same sqlite
file Kandev writes to. That's a deliberate design choice on our side (zero
dependencies, zero risk of touching their runtime), but it means dropping
the file into their repo as-is wouldn't match how any other feature in that
codebase is built, tested, or maintained. A maintainer reading a PR that
adds a foreign-language, foreign-testing-stack file would reasonably ask
"why isn't this a Go handler + web page, like everything else here?" —
exactly the kind of direction question the issue-first rule exists to
resolve before code gets written.

**Sharif's position (2026-09-10):** open to porting the tool's language to
match their stack if that eases adoption — it's a small companion program
that assists the platform from beside it, not something touching their
core code, so a Go/TS port stays architecturally the same shape (a
standalone, read-only, out-of-process service) regardless of language. This
doesn't remove the issue-first requirement — the *decision to add a new
subsystem at all* still needs discussion — but it does mean the language
objection in option 1 below isn't a real blocker if maintainers prefer it
written in Go.

## What the issue should propose (options, not a decision made here)

1. **Port it as a real feature** — a Go endpoint serving the same read-only
   query + a React page under `apps/web`, following the Workflow/MCP or
   Settings/workbench extension seam, with Playwright e2e tests
   (`apps/web/e2e/`) per their UI-change rule. Highest integration quality,
   highest effort, and the maintainers may already have their own plans for
   a feature like this — worth asking before duplicating work.
2. **Ship it as a companion script**, documented from their repo (a
   `docs/public` page or a `tools/`-style directory) but not touching their
   build/test/lint pipeline, closer to what it already is. Lowest effort,
   but maintainers may not want a second language/runtime in the repo for
   something with no tests in their own suite.
3. **Publish it as a community tool** referenced from their docs/Discord
   rather than merged into the repo at all — check `docs/public/plugins.md`
   / `plugins-marketplace.md` for whether a non-plugin companion tool has a
   home there.

## Other rules that apply once a direction is picked

- **Keep PRs small and focused** — one logical change per PR.
- **Update public docs in the same PR** if user-facing behavior changes —
  `docs/public/**`, following `docs/public/README.md` for navigation/page
  conventions.
- **Screenshots/recordings required** for anything with a UI component —
  already prepared, see `docs/live-workflow-diagram-guide.md`.
- **AGPL-3.0** — contributions are licensed under the repo's existing
  license by contributing.
- English for all issue/PR/doc/code-comment text.

## Recommendation

Don't open a PR directly. Open a GitHub issue on `kdlbs/kandev` proposing
the tool, linking the guide and screenshots, and naming the three options
above without picking one — let the maintainers weigh in on fit before any
code gets written in their preferred shape. This is a judgment call for
Sharif to make (posting to a public repo is externally visible), not
something to do automatically.
