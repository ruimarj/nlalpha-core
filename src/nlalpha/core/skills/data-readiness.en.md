# Data readiness

Skill ID: data-readiness  
Revision: 1  
Language: en

## Purpose

Check whether the requested market data is available and suitable for the stated task, or prepare data when a reference is requested. Read the `principles` section from any service `about` description for shared evidence and scope principles. Reuse it while its description revision is unchanged; after a revision changes, read the current section. Then read the data service description and the relevant provider description. Reuse complete descriptions while their revision is unchanged; request only needed sections when supported.

## Set the request scope

Identify the requested symbols, interval, date range, and purpose: coverage check, quality check, calendar or time review, missing-session analysis, or data preparation. A data check alone does not authorize a backtest. Do not prepare additional data or start a run unless the request needs it.

## Select and assess the source

Discover available providers. Use an explicitly requested provider when supplied; otherwise follow the configured default or the service's single-available-provider rule. If multiple sources are available and no default is configured, ask for a selection or report the resulting blocker. Do not switch sources silently. Before using provider-specific capabilities, read the selected provider's manifest capabilities and the relevant `confess` sections; do not infer support from tool names or package identity.

Check coverage and quality for the exact symbols, interval, and range. Establish source evidence for price adjustment when it matters. Adjustment reference and anchor are defined by the selected provider's guidance; do not assume the same anchor across providers. Confirm timestamp meaning, timezone, interval, and the applicable instrument calendar before making time-based claims. A date range, row count, successful load, or calendar sessions alone do not establish observed coverage. An exact missing-session count requires actual observed dates compared with the applicable calendar; if either is unavailable, report the count as unknown.

## Load data when needed

Load only when the task requires a data reference, a load-contract check, or later authorized research. Preserve the returned immutable `data_ref`, source metadata, time contract, units, and scope together. A reference identifies a payload under its scope; it does not prove data quality or complete coverage. Reuse existing data only after checking that its source, schema, scope, and time semantics fit this request.

## Report the findings

Explain what was checked, the observed coverage and quality, confirmed source and time evidence, and material unknowns in the user's language. Do not infer missing dates, adjustment, timezone, calendar, or units. If the required evidence or provider is unavailable, state that limitation rather than filling it with an assumption.

## Capability routes

Discover routes from the live tool directory; names below are logical service operations, not a guarantee of installation. Common data routes are `data.list_data_providers`, `data.confess`, `data.check_data_coverage`, and `data.get_data_quality`. Use `data.load_bars` only when a reference or load-contract check is needed. Calendar routes such as `data.list_trading_calendars`, `data.get_trading_days`, and `data.is_trading_day` are conditional on calendar evidence being required.

Read a packaged skill through `strategy.load_skill(name, language)`; request one language per call. The English and Chinese files have matching sections.
