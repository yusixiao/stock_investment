import importlib.util
import inspect
from pathlib import Path

from strategies.base import Strategy


def load_strategy_from_file(filepath: Path) -> list[type]:
    filepath = Path(filepath)
    if not str(filepath) or str(filepath) == "." or not filepath.is_file():
        raise FileNotFoundError(f"Strategy file not found: {filepath}")

    spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from: {filepath}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    strategies = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, Strategy)
            and obj is not Strategy
            and obj.__module__ == module.__name__
        ):
            strategies.append(obj)
    return strategies


def scan_strategies(directory: Path) -> list[dict]:
    directory = Path(directory)
    results = []
    for filepath in sorted(directory.rglob("*.py")):
        if filepath.name.startswith("_"):
            continue
        try:
            classes = load_strategy_from_file(filepath)
        except Exception:
            continue
        for cls in classes:
            info = {
                "name": cls.name,
                "description": cls.description,
                "strategy_type": cls.strategy_type,
                "params": cls.params,
                "filepath": str(filepath),
                "class_name": cls.__name__,
                "frequency_overridable": getattr(cls, "frequency_overridable", False),
            }
            if hasattr(cls, "frequency"):
                info["frequency"] = cls.frequency
            results.append(info)
    return results
