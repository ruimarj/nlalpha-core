"""Family capability contract. Single source of truth for prompts, templates, validators, and auto-fix rules."""

from dataclasses import dataclass, field

from nlalpha.core.capabilities.registry import CapabilityEntry


@dataclass
class FamilyContract:
    """Complete capability contract for a strategy family.

    Single source of truth: helper lists in prompts, template docstrings,
    validator whitelists, and auto-fix constraints are all derived from this contract.
    """

    family: str
    base_class: str
    base_import: str
    lifecycle_methods: list[str]
    callback_methods: list[str] = field(default_factory=list)
    market_inputs: list[str] = field(default_factory=list)
    helpers: list[CapabilityEntry] = field(default_factory=list)
    readonly_props: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    profile: str = "minimal"
    builtin_names: set[str] = field(default_factory=set)
    engine: str = "nautilus"  # 回测引擎：nautilus 或默认引擎

    def helper_by_domain(self, domain: str) -> list[CapabilityEntry]:
        """Filter helpers by domain."""
        return [h for h in self.helpers if h.domain == domain]

    def function_helpers(self) -> list[CapabilityEntry]:
        """Return all callable functions."""
        return [h for h in self.helpers if h.category == "function"]

    def property_helpers(self) -> list[CapabilityEntry]:
        """Return all properties."""
        return [h for h in self.helpers if h.category == "property"]

    def readonly_props_display(self) -> list[str]:
        return [f"self.{p}" for p in self.readonly_props]

    def to_spec_schema(self) -> dict:
        """Derive the strategy schema from its accepted lifecycle entry points."""
        method_names = " or ".join(signature.split("(", 1)[0].strip() for signature in self.lifecycle_methods)
        callbacks = ", ".join(signature.split("(", 1)[0].strip() for signature in self.callback_methods)
        callback_hint = f"; optional callbacks: {callbacks}" if callbacks else ""
        return {
            "parameters": [{"name": "parameter_name", "type": "int|float|str|bool", "default": "default_value"}],
            "code": f"Complete Python class code inheriting {self.base_class} and implementing at least one lifecycle entry point: {method_names}{callback_hint}",
        }

    def to_code_fix_constraints(self) -> str:
        """Derive auto-fix constraints from rules and readonly_props."""
        lines = list(self.rules)
        readonly = self.readonly_props
        if readonly:
            if len(readonly) == 1:
                lines.append(f"self.{readonly[0]} is read-only; assignment is forbidden")
            else:
                props_str = ", ".join(f"self.{p}" for p in readonly)
                lines.append(f"{props_str} are read-only; assignment is forbidden")
        if not lines:
            return ""
        return "\n".join(f"{i + 2}. {line}" for i, line in enumerate(lines)) + "\n"

    def to_prompt(self) -> str:
        """Derive family code guidance from lifecycle, rules, and output schema."""
        # base_import 可能包含类名，需要拆分为模块路径
        if "." in self.base_import:
            parts = self.base_import.rsplit(".", 1)
            module_path = parts[0] if parts[1] == self.base_class else self.base_import
        else:
            module_path = self.base_import

        lines = [
            f"## {self.family.upper()} strategy family",
            "",
            f"Base class: `{self.base_class}`",
            f"Import: `from {module_path} import {self.base_class}`",
            "Lifecycle entry points (implement at least one): " + " or ".join(
                f"`def {signature}`" for signature in self.lifecycle_methods
            ),
        ]
        if self.callback_methods:
            lines.append("Optional callbacks: " + ", ".join(
                f"`def {signature}`" for signature in self.callback_methods
            ))
        lines.extend([f"Market inputs: `{' / '.join(self.market_inputs)}`", "", "### Code constraints"])
        for i, rule in enumerate(self.rules, 1):
            lines.append(f"{i}. {rule}")

        if self.readonly_props:
            lines.extend(["", "### Read-only properties (assignment forbidden)"])
            lines.append(f"`{'`, `'.join(f'self.{p}' for p in self.readonly_props)}`")

        schema = self.to_spec_schema()
        lines.extend([
            "",
            "### Output format",
            f"- `parameters`: {schema['parameters']}",
            f"- `code`: {schema['code']}",
        ])

        return "\n".join(lines)
