# Strategy authoring

Skill ID: strategy-authoring  
Revision: 1  
Language: en

## Purpose

Turn the user's stated trading rules into a faithful strategy specification and implementation. For common evidence and request boundaries, read the `principles` section from any service `about` description. Reuse it while its revision is unchanged; after a revision changes, read the current section. Then use the current strategy and, when execution choice affects feasibility, backtest service descriptions. Reuse complete descriptions whose revision has not changed; request only needed sections when supported.

## Discover the strategy contract

Discover installed strategy families and select only a family that is available for this request. Read that family's current `about` and complete `confess` description before implementing it. Treat its contract as authoritative for structure, lifecycle, helper bindings, inputs, and limits. Do not infer support from a package name or use helpers from another family.

When the requested behavior depends on execution semantics, discover available engines and read the relevant engine description. Check that the family and engine preserve the requested events, account feedback, order lifecycle, and timing. If no available path can preserve a material rule, explain the difference and ask how to proceed.

## Preserve the user's rules

Record entry, holding, exit, sizing, capital, cost, risk, and execution timing requirements. Keep state conditions separate from transition events: `fast > slow` is a state; a cross depends on both prior and current values. Preserve dynamic sizing from currently available cash; do not replace it with static initial capital. Clarify only choices that change research meaning, and identify any default with its source.

## Implement and validate

Build the complete specification and implementation against the selected family's current contract. Use the applicable static checker, then the mock validator for the selected execution path when available. Use the same strategy and intended configuration for validation. Correct ordinary implementation or configuration errors within the original request and repeat affected checks. Do not change user choices or the research meaning to make validation pass.

## Deliver the result

Explain the strategy rules, actual parameters, assumptions, validation performed, and unresolved choices in the user's language. State that static checks and mock runs cover only their tested behavior; they do not establish profitability, suitability for real data, or a historical result. If the user requests a real backtest, continue with data readiness and backtest execution; authoring alone does not start one.

## Capability routes

Discover routes from the live tool directory; names below are logical service operations, not a guarantee of installation. Common strategy routes are `strategy.list_families`, `strategy.about`, `strategy.confess`, and `strategy.validate_spec`. Use `backtest.list_engines`, `backtest.confess`, and `backtest.validate_strategy` conditionally when engine semantics or path-specific mock validation matter. Event and batch routes are conditional on their actual publication and availability.

Read a packaged skill through `strategy.load_skill(name, language)`; request one language per call. The English and Chinese files have matching sections.
