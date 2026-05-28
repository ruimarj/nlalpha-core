"""Lightweight configuration loader for the ecosystem.

No external dependencies beyond stdlib (dotenv is optional).
Each tool can extend this with its own env-var reads.

Note: OpenTelemetry configuration is managed by telemetry.py directly.
"""

from __future__ import annotations

import os

# 可选 dotenv 支持，未安装时优雅降级
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass  # dotenv 未安装或 .env 缺失

# 工作区与运行时配置
ENV: str = os.getenv("NLALPHA_ENV", "prod").lower()
WORKSPACE_ROOT: str = os.getenv("NLALPHA_WORKSPACE", "workspace")
