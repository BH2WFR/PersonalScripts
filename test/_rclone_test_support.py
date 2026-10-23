"""Load the private rclone package once for focused regression tests."""

import importlib
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rclone_sync_test_target", ROOT / "tools/network/rclone-sync.py")
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)
runner.load_app()
models = importlib.import_module("personal_rclone_sync.models")
schema_ops = importlib.import_module("personal_rclone_sync.schema")
endpoint_ops = importlib.import_module("personal_rclone_sync.endpoints")
backend = importlib.import_module("personal_rclone_sync.rclone")
terminal = importlib.import_module("personal_rclone_sync.ui")
execution = importlib.import_module("personal_rclone_sync.execution")
app = importlib.import_module("personal_rclone_sync.app")
import utils as utility
