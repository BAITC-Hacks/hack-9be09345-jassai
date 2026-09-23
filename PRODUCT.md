# Career Quest

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Employees choose a career goal and voluntary development activities. HR reviews team skill gaps, imports data and creates employee access. User is participant C; A owns backend and B AI/launcher.

## Product Purpose

Connect each next activity to a career goal with explainable recommendations and deterministic skill changes. Preserve the full goal → recommendation → start → complete → progress → HR flow.

## Operating Context

Local FastAPI/SQLite application, static JavaScript frontend, Russian interface, Windows hackathon delivery. AI calls require an external provider; ordinary profile and calculation views run locally. Date comes from the dataset snapshot.

## Capabilities and Constraints

Backend owns eligibility, persisted skill levels and access control. Forecasts are previews, never saved progress. Completed activities change levels according to dataset rules, not independent competence verification. Coverage is not a promise of promotion. No public staff ranking or rewards for mandatory activities. OpenAI/NVIDIA settings UI depends on B's implementation.

## Brand Commitments

User-provided Halyk_Career_Quest_UIUX_TZ.md: light Halyk-style enterprise interface, white cards, green primary actions, skill progress, before/after changes; no cartoon RPG style. Retain authentic content and current routes while expanding functional detail views.

## Evidence on Hand

app/, frontend/, docs/API_CONTRACT.md, docs/FRONTEND_TEST_RESULTS.md and provided design specification. Preview fixtures must be explicitly synthetic. No real billing balances, notifications, assessment results or locale support may be invented.

## Product Principles

- Every action has a visible result and useful recovery state.
- Explain numerical changes with actual profile and catalog data.
- Employee and HR permissions remain enforced by the backend.
- Show unavailable integrations honestly.
- Keep the local application usable without downloading fonts or scripts at runtime.
