"""ai_engine.tools — compact, token-cheap analysis tools for strategy research.

BaseTool holds the common machinery; each tool is a subclass that reports facts
(never decides trades). See README.md.

    from ai_engine.tools import Indicators
    Indicators().analyze(symbol="NIFTY", tf="5m", at="2022-01-03 09:45", indicators=["rsi:14"])
"""
from ai_engine.tools.ai_tools import (
    BaseTool, Indicators, Patterns, Statistics, MTF,
)

__all__ = ["BaseTool", "Indicators", "Patterns", "Statistics", "MTF"]
