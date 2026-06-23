import importlib
import pkgutil
import inspect
import logging
from typing import Dict, Type
from mt_quant_system.core.strategy import BaseStrategy

logger = logging.getLogger(__name__)

def load_strategies() -> Dict[str, Type[BaseStrategy]]:
    """
    Dynamically discovers and loads all strategy classes in the current package.
    Returns a dictionary mapping 'StrategyName' -> StrategyClass.
    """
    strategies = {}
    package_name = __name__
    package_path = __path__

    for _, module_name, _ in pkgutil.iter_modules(package_path):
        full_module_name = f"{package_name}.{module_name}"
        try:
            module = importlib.import_module(full_module_name)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                # Ensure it inherits from BaseStrategy, is not BaseStrategy itself, and is defined in this module
                if issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    strategies[obj.__name__] = obj
                    # Also map simpler lower case name if preferred, but CaseSensitive is standard for classes
        except Exception as e:
            logger.error(f"Failed to load module {full_module_name}: {e}")

    return strategies
