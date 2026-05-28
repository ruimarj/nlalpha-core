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
    lifecycle_method: str
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
        """Derive spec_schema from lifecycle_method."""
        method_name = self.lifecycle_method.split("(")[0].strip()
        return {
            "parameters": [{"name": "参数名", "type": "int|float|str|bool", "default": "默认值"}],
            "code": f"完整的 Python 类代码字符串（继承 {self.base_class}，实现 {method_name}）",
        }

    def to_code_fix_constraints(self) -> str:
        """Derive auto-fix constraints from rules and readonly_props."""
        lines = list(self.rules)
        readonly = self.readonly_props
        if readonly:
            if len(readonly) == 1:
                lines.append(f"self.{readonly[0]} 是只读属性，禁止赋值")
            else:
                props_str = "、".join(f"self.{p}" for p in readonly)
                lines.append(f"{props_str} 是只读属性，禁止赋值")
        if not lines:
            return ""
        return "\n".join(f"{i + 2}. {line}" for i, line in enumerate(lines)) + "\n"

    def to_prompt(self) -> str:
        """Generate a prompt metadata fragment for the strategy family.

        Does not include helper lists (agents query those via list_family_helpers);
        only includes metadata required for code generation: base class, lifecycle method,
        constraints, and output format.
        """
        # base_import 可能包含类名，需要拆分为模块路径
        if "." in self.base_import:
            parts = self.base_import.rsplit(".", 1)
            module_path = parts[0] if parts[1] == self.base_class else self.base_import
        else:
            module_path = self.base_import

        lines = [
            f"## {self.family.upper()} 策略族",
            "",
            f"基类：`{self.base_class}`",
            f"继承方式：`from {module_path} import {self.base_class}`",
            f"生命周期方法：`def {self.lifecycle_method}`",
            f"价格数据访问：`{' / '.join(self.market_inputs)}`",
            "",
            "### 代码约束",
        ]
        for i, rule in enumerate(self.rules, 1):
            lines.append(f"{i}. {rule}")

        if self.readonly_props:
            lines.extend(["", "### 只读属性（禁止赋值）"])
            lines.append(f"`{'`、`'.join(f'self.{p}' for p in self.readonly_props)}`")

        schema = self.to_spec_schema()
        lines.extend([
            "",
            "### 输出格式",
            f"- `parameters`：{schema['parameters']}",
            f"- `code`：{schema['code']}",
        ])

        return "\n".join(lines)
