"""
========================================
tools/trace/__init__.py — trace 工具入口
========================================

trace 是「我修正/更新某条记忆」。整个 trace 没有真正多分支，所以
只放一个 core.py 实现。这里仅做 dispatch 转发。

对外暴露：dispatch(...) → str（参数与 server.py 中的 trace tool 同名）
========================================
"""

from .core import trace_core as dispatch  # noqa: F401
