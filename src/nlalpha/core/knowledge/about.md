# NLAlpha shared principles

Revision: 1

## Purpose

NLAlpha provides domain capabilities that natural-language agents can use to prepare market data, author strategies, and run or review backtests. Work through capabilities that are actually available in the current environment. Package names, examples, and prior sessions do not establish that a provider, family, engine, validator, or tool is installed and usable.

## Discover and scope capabilities

Use the current service and object descriptions to understand available work, supported inputs, assumptions, and limitations. Treat available catalogs as the source of selectable capabilities and diagnostics as the source of installed-but-unavailable or failed capabilities. An optional capability that is absent is not a defect; a requested capability that is unavailable is a concrete blocker. Never replace it silently with another source, strategy family, engine, or execution mode.

Read descriptions by need. Reuse a complete description while its revision is unchanged; request only the missing sections when the consumer supports section reads. A revision change requires checking the changed guidance before relying on it. Descriptions explain behavior and limits; structured contracts and schemas remain authoritative for machine-readable fields.

Read a task skill by its stable skill ID and request one language per read, for example `strategy.load_skill(name, language="en")`. A `zh` resource is a semantically equivalent translation of its English counterpart. Do not load both versions for one task unless translation comparison is specifically needed.

## Preserve research meaning

Keep the user's stated rules and scope intact. Distinguish a state from a transition: `fast > slow` is a state, while a cross is a change between prior and current observations. Preserve event timing, account feedback, order lifecycle, position sizing, costs, and risk choices. Dynamic sizing from currently available cash cannot be approximated by a fixed fraction of initial capital. If an available path cannot preserve a material requirement, explain the difference and ask how to proceed before changing it.

Do not expand a request. A data check does not authorize a backtest; a strategy validation does not authorize a historical run; inspecting a result does not authorize a new experiment. Use only references and data within the current caller's authorized scope. Keep immutable references and their source/scope metadata bound to the request that produced them.

## Use evidence and report unknowns

Prefer source declarations, timestamps, calendars, adjustment evidence, and observed records over inference from names, counts, date ranges, or successful loading. Preserve unknown values as unknown. Exact missing-session counts require observed dates compared with the applicable calendar. A `data_ref` proves that a payload can be referenced under its scope; it does not by itself prove coverage, quality, or correctness.

Static checks and mock runs establish only the conditions they actually exercise. They do not prove historical performance, real-data suitability, complete causal behavior, code safety, or future results. Report the tested scope and limitations. Distinguish tool success, job termination, and a clean successful backtest result; use the result and report contracts for business conclusions.

## Fail clearly without changing meaning

When required evidence, permission, or a selected capability is missing, state the exact gap and stop work that depends on it. Handle ordinary input and configuration errors by correcting them within the original request. Do not suppress failures by changing a provider, weakening validation, inventing data, retrying a side-effecting job as a new run, or substituting a different interpretation.

## Communicate with the user

Use the user's language and explain the business rules, assumptions, evidence, and limits in plain language. English service descriptions and machine identifiers do not require an English conversation. Do not present a partial check as a broader conclusion or a backtest as a prediction.
