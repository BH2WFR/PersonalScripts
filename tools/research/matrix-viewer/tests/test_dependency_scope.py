"""Regression checks for MatrixViewer's packaging allowlist."""

from importlib import metadata
from pathlib import Path
import sys
from unittest import TestCase
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))
import dependency_scope as scope
sys.path.pop(0)


class DependencyScopeTests(TestCase):
    def test_resolves_required_extras_and_skips_unrequested_integrations(self) -> None:
        records = {
            "viewer": ["shared", "bridge", "other-os; sys_platform == 'nonexistent'"],
            "bridge": ["shared[render]>=1"],
            "shared": ["backend; extra == 'render'", "unrelated; extra == 'cloud'"],
            "backend": ["viewer"],
        }

        installed = {name: Mock(spec=metadata.Distribution, version="1.0", requires=deps)
                     for name, deps in records.items()}
        with patch.object(metadata, "distribution", side_effect=installed.__getitem__):
            self.assertEqual(set(scope.runtime_distributions(("viewer",))), set(records))
            with self.assertRaisesRegex(ValueError, "requires shared>=2"):
                scope.runtime_distributions(("shared>=2",))

    def test_unrelated_distributions_are_blocked_but_shared_names_are_preserved(self) -> None:
        owners = {"shared": ["Allowed_Pkg", "Other"], "added_later": ["Other"], "json": ["Other"]}
        with patch.object(metadata, "packages_distributions", return_value=owners):
            allowed = {"allowed-pkg": Mock(spec=metadata.Distribution)}
            self.assertEqual(scope.unrelated_modules(allowed), ["added_later"])
