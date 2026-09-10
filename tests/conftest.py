"""Makes decision.py / garmin.py / schedule_store.py importable for plain
pytest, without requiring a full Home Assistant install.

custom_components/tado_schedule/__init__.py imports homeassistant.*, which
isn't installed in a bare dev environment - so instead of importing the real
package, we register a stand-in package module pointing at the same
directory before importing the individual (HA-free) submodules we test.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = ROOT / "custom_components" / "tado_schedule"

if "custom_components" not in sys.modules:
    pkg = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("custom_components", loader=None, is_package=True)
    )
    pkg.__path__ = [str(ROOT / "custom_components")]
    sys.modules["custom_components"] = pkg

if "custom_components.tado_schedule" not in sys.modules:
    stub = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("custom_components.tado_schedule", loader=None, is_package=True)
    )
    stub.__path__ = [str(COMPONENT_DIR)]
    sys.modules["custom_components.tado_schedule"] = stub
