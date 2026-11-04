"""Import side effect: makes scripts/ importable so tests can load pure helper modules."""
import sys

from helpers import PLUGIN_ROOT

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
