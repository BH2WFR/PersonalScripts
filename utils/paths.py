"""Path placeholder and environment-variable resolution helpers."""

import os
import re


class Paths:
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
