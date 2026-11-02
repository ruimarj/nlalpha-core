# Backtest execution

Skill ID: backtest-execution  
Revision: 1  
Language: en

## Purpose

Run or review only the backtest work the user requested. Read the `principles` section from any service `about` description for shared evidence, authorization, and result boundaries. Reuse it while its description revision is unchanged; after a revision changes, read the current section. Then read current strategy, data, and backtest service descriptions as needed. Reuse complete descriptions while their revision is unchanged; request only needed sections when supported.

## Discover the available path

Distinguish a new historical run from checking, cancelling, retrieving, or reviewing an existing job. For a new run, discover the current strategy family, engines, validators, event or batch tools, and data providers. Use only tools that the live catalog exposes as available. Read the selected family's, engine's, provider's, and validator's current contracts when relevant. Event and batch routes are conditional capabilities; do not treat both as required.

## Prepare and validate

Preserve the user's strategy, symbols, dates, timing, account behavior, sizing, costs, and risk choices. Confirm the chosen family and engine can express them. In particular, retain dynamic sizing from currently available cash when requested; do not approximate it with static initial capital.

Check data coverage, quality, price-source evidence, timestamps, timezone, units, and calendar for the requested range. Load only the data required by the task and preserve immutable references with their source and scope. Validate required fields using the selected event or batch object's current contract, not an example or remembered schema. Run the applicable static check and path-specific mock validation before submitting a historical run.

## Run and inspect

Submit only after prerequisites pass and the user authorized a new run. Observe the existing job until its actual terminal state. If status is unknown or work is still running, do not submit a duplicate. For an existing job, perform only the requested status, cancellation, result, or review operation.

Retrieve result and report sections only as needed for the requested conclusion. Check that status is a clean successful result, the data and strategy match the request, and the reports cover the conclusion's scope. Treat missing, unrecorded, truncated, or unavailable fields as unknown, not zero. A finished job or successful tool response alone is not a successful backtest result.

## Report the result

In the user's language, state the requested range, assumptions, actual validation, result status, evidence reviewed, risks, and limits. Static checks and mock runs do not establish historical performance. Backtest results describe the tested sample and assumptions; they do not predict future performance. Do not create extra experiments to fill a reporting gap without authorization.

## Capability routes

Discover routes from the live tool directory; names below are logical service operations, not a guarantee of installation. Common routes for a new event-driven run include `strategy.list_families`, `strategy.about`, `strategy.confess`, `data.list_data_providers`, `data.confess`, `data.check_data_coverage`, `data.get_data_quality`, `data.load_bars`, `backtest.list_engines`, `backtest.confess`, `backtest.validate_strategy`, and `backtest.run_backtest`. Batch routes such as `backtest.validate_batch_strategy` and `backtest.run_batch_backtest` are conditional on publication and availability. Status, cancellation, result, and report routes such as `backtest.get_backtest_status`, `backtest.cancel_backtest`, `backtest.get_backtest_result`, and `backtest.get_backtest_report` are used only for the corresponding requested operation.

Read a packaged skill through `strategy.load_skill(name, language)`; request one language per call. The English and Chinese files have matching sections.
