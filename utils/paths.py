"""Path placeholder and environment-variable resolution helpers."""

import os
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path


class Paths:
    @staticmethod
    def resolve_path(
        path: str, base_dir: str | os.PathLike[str], *,
        expand_environment: bool = True, resolve_symlinks: bool = False,
    ) -> str:
        """Resolve a path relative to an explicit base directory.

        Args:
            path: Absolute or relative path, optionally containing ~ or variables.
            base_dir: Base for relative paths; never changes process cwd.
            expand_environment: Expand native os.path.expandvars syntax before
                ~ expansion. Undefined variables remain literal. Set False when
                a caller already used expand_template or literal input values.
            resolve_symlinks: Follow links using Path.resolve when True; otherwise
                normalize lexically with abspath, preserving launcher semantics.

        Returns:
            Absolute path without requiring the target to exist.

        Raises:
            OSError: Symlink resolution fails when resolve_symlinks is enabled.
        """
        expanded = os.path.expandvars(path) if expand_environment else path
        expanded = os.path.expanduser(expanded)
        if not os.path.isabs(expanded):
            expanded = os.path.join(base_dir, expanded)
        return str(Path(expanded).resolve()) if resolve_symlinks else os.path.abspath(expanded)

    @staticmethod
    def resolve_directories(
        paths: Iterable[str], base_dir: str | os.PathLike[str], *,
        on_missing: Callable[[str], None] | None = None,
    ) -> tuple[str, ...]:
        """Resolve existing directories, deduplicating in first-occurrence order.

        Args:
            paths: Directory paths using native variable and ~ expansion.
            base_dir: Base for relative entries.
            on_missing: Optional callback receiving each distinct missing path
                once. None silently discards missing entries. Files count as
                missing directories; input strings are not stripped or split.

        Returns:
            Existing absolute directory paths, deduplicated using normcase.

        Side effects:
            Inspects the filesystem and invokes on_missing when supplied.
        """
        result: list[str] = []
        seen: set[str] = set()
        for path in paths:
            directory = Paths.resolve_path(path, base_dir)
            key = os.path.normcase(directory)
            if key in seen:
                continue
            seen.add(key)
            if os.path.isdir(directory):
                result.append(directory)
            elif on_missing is not None:
                on_missing(directory)
        return tuple(result)

    @staticmethod
    def expand_template(
        text: str, environment: Mapping[str, str], placeholders: Mapping[str, str],
    ) -> str:
        """Expand a template once, without interpreting substituted values.

        Args:
            text: Text containing ${VAR}, $VAR, %VAR%, $ENV:VAR,
                ${ENV:VAR}, or {{placeholder}} references.
            environment: Explicit variable source, case-insensitive on Windows.
            placeholders: Named literal substitutions such as current_dir.

        Returns:
            Expanded text. Values containing template syntax stay literal.

        Raises:
            ValueError: A referenced variable or placeholder is undefined.
        """
        pattern = re.compile(
            r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}|"
            r"\$\{(?:ENV:)?([A-Za-z_][A-Za-z0-9_]*)\}|"
            r"\$(?:ENV:)?([A-Za-z_][A-Za-z0-9_]*)|"
            r"%([A-Za-z_][A-Za-z0-9_]*)%"
        )
        values = {k.upper() if os.name == "nt" else k: v for k, v in environment.items()}

        def replace(match: re.Match[str]) -> str:
            """Resolve one reference without recursively expanding its value."""
            if match[1]:
                if match[1] not in placeholders:
                    raise ValueError(f"Unknown placeholder: {match[1]}")
                return placeholders[match[1]]
            name = next(g for g in match.groups()[1:] if g is not None)
            key = name.upper() if os.name == "nt" else name
            if key not in values:
                raise ValueError(f"Undefined environment variable: {name}")
            return values[key]

        return pattern.sub(replace, text)

    @staticmethod
    def resolve_environment(
        inherited: Mapping[str, str], overrides: Mapping[str, str],
        literals: Mapping[str, str], placeholders: Mapping[str, str],
    ) -> dict[str, str]:
        """Resolve dependent environment overrides without mutating os.environ.

        Args:
            inherited: Parent process environment.
            overrides: Templates, including references to other overrides.
            literals: Raw input values; these override templates without expansion.
            placeholders: Literal {{name}} substitutions.

        Returns:
            Complete child environment. Self-references read the parent value.

        Raises:
            ValueError: A variable is undefined or references form a cycle.
        """
        def normalize(values: Mapping[str, str]) -> dict[str, str]:
            return {k.upper() if os.name == "nt" else k: v for k, v in values.items()}

        parent = normalize(inherited)
        pending = normalize(overrides)
        resolved = normalize(literals)
        stack: list[str] = []
        variable_pattern = re.compile(
            r"\$\{(?:ENV:)?([A-Za-z_][A-Za-z0-9_]*)\}|"
            r"\$(?:ENV:)?([A-Za-z_][A-Za-z0-9_]*)|%([A-Za-z_][A-Za-z0-9_]*)%"
        )

        def resolve(name: str) -> str:
            """Resolve one override with a recursion-stack cycle check."""
            key = name.upper() if os.name == "nt" else name
            if key in resolved:
                return resolved[key]
            if key in stack:
                raise ValueError(f"Circular environment reference: {' -> '.join([*stack, key])}")
            if key not in pending:
                if key not in parent:
                    raise ValueError(f"Undefined environment variable: {name}")
                return parent[key]
            if len(stack) >= 64:
                raise ValueError("Environment reference depth exceeds 64")
            stack.append(key)
            dependencies: dict[str, str] = {}
            for match in variable_pattern.finditer(pending[key]):
                reference = next(g for g in match.groups() if g is not None)
                reference_key = reference.upper() if os.name == "nt" else reference
                if reference_key == key:
                    if key not in parent:
                        raise ValueError(f"Self-reference has no inherited value: {name}")
                    dependencies[reference_key] = parent[key]
                else:
                    dependencies[reference_key] = resolve(reference_key)
            resolved[key] = Paths.expand_template(pending[key], dependencies, placeholders)
            stack.pop()
            return resolved[key]

        for name in pending:
            resolve(name)
        return {**parent, **resolved}

    @staticmethod
    def resolve_vars(path: str, schema_dir: str = "", script_dir: str = "") -> str:
        """Resolve variables in a path string.

        Supported placeholders:
          ``${VAR}`` / ``%VAR%`` — environment variable
          ``$ENV:VAR`` / ``${ENV:VAR}`` — PowerShell-style environment variable
          ``{{schema_dir}}``    — directory of the YAML schema file
          ``{{script_dir}}``    — directory of the script
          ``{{current_dir}}``   — current working directory
        """
        p = path
        if schema_dir:
            p = p.replace("{{schema_dir}}", schema_dir)
        if script_dir:
            p = p.replace("{{script_dir}}", script_dir)
        p = p.replace("{{current_dir}}", os.getcwd())

        p = os.path.expanduser(p)
        try:
            p = re.sub(r"\$\{ENV:([^}]+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), p)
            p = re.sub(r"\$ENV:([A-Za-z_][A-Za-z0-9_]*)", lambda m: os.environ.get(m.group(1), m.group(0)), p)
        except Exception:
            pass
        p = os.path.expandvars(p)
        return p
