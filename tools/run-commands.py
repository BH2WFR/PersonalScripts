#!/usr/bin/env python3
"""Select and run YAML-defined shell commands, executables, scripts, or code.

Requirements:
    - pip: PyYAML (already in requirements.txt)
    - Only the selected task's runtime/program is required. conda-python uses
      Conda; tsx uses Node and the project's installed tsx package.

Usage:
    conda run --no-capture-output -n base python tools/run-commands.py
    conda run -n base python tools/run-commands.py --schema-file ./commands.yaml --list
    conda run -n base python tools/run-commands.py --task android/adb-devices --yes
    conda run -n base python tools/run-commands.py --schema-file ./commands.yaml --validate

Interactive startup asks for a configuration path, defaulting to --schema-file
or ZL_RUN_COMMANDS_SCHEMA_FILE. With --task or redirected stdin, one of those paths
must be supplied and is used without a path prompt. --yes skips only execution
confirmation. run-commands-schema-sample.yaml is reference documentation for
users/agents, never an automatic default or fallback configuration.
Profiles apply once per final task, parents first, with cycle detection.
Environment and interactive-inputs merge by name; later definitions overwrite.
Relative paths use the invocation directory or the task's cwd, never implicitly
the YAML directory. Command/code text and interactive values remain literal.
--dry-run builds a plan and probes runtimes but never runs the configured task.
No automatic installation, shell fallback, or abort-on-error policy is applied.
"""

import argparse
import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from utils import *  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
SCHEMA_SAMPLE = SCRIPT_DIR / "run-commands-schema-sample.yaml"
SCHEMA_ENV = "ZL_RUN_COMMANDS_SCHEMA_FILE"
MAX_PROFILE_DEPTH = 64
TEMP_SCRIPT = "<temporary-command-script>"
CONDA_PAYLOAD_ENV = "ZL_RUN_COMMANDS_INTERNAL_PAYLOAD"
CONDA_BOOTSTRAP = (
    f"import json,os,runpy,sys; p=json.loads(os.environ.pop('{CONDA_PAYLOAD_ENV}')); "
    "sys.argv=p['argv']; "
    "sys.path.__setitem__(0,p['import_path']) if not getattr(sys.flags,'safe_path',False) else None; "
    "m=type(sys)('__main__'); sys.modules['__main__']=m; "
    "exec(compile(p['code'],'<string>','exec'),m.__dict__) "
    "if p['kind']=='code' else runpy.run_path(sys.argv[0],run_name='__main__')"
)
FILTER_KEYS = frozenset({"platform", "arch", "computer-name"})
CONTEXT_KEYS = frozenset({"environment", "interactive-inputs"})
LAYER_KEYS = FILTER_KEYS | CONTEXT_KEYS | {"inherit", "default-shell-binding", "cwd", "run"}
SHELL_KINDS = frozenset({RuntimeKind.POWERSHELL, RuntimeKind.PWSH, RuntimeKind.CMD,
                         RuntimeKind.GIT_BASH, RuntimeKind.BASH, RuntimeKind.ZSH})
PYTHON_KINDS = frozenset({RuntimeKind.CONDA, RuntimeKind.PYTHON, RuntimeKind.CURRENT_PYTHON})
PLATFORM_ALIASES = {"windows": "win32", "macos": "darwin"}
ARCH_ALIASES = {"x64": "amd64", "x86_64": "amd64", "x86": "386", "i386": "386", "aarch64": "arm64"}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class RunType(StrEnum):
    """Supported payload types, each with its own required fields."""

    SHELL = "shell"
    EXEC = "exec"
    SCRIPT = "script"
    CODE = "code"


@dataclass
class Task:
    """One fully inherited leaf task, including its parent menu identity."""

    group: str
    name: str
    sub_name: str | None
    config: dict[str, object]

    @property
    def parent_id(self) -> str:
        """Return the stable group/name identifier used by --task."""
        return f"{self.group}/{self.name}"

    @property
    def label(self) -> str:
        """Return the full task/sub-task label for menus and diagnostics."""
        return f"{self.parent_id}/{self.sub_name}" if self.sub_name else self.parent_id


@dataclass
class ExecutionPlan:
    """Resolved argv, child environment, and optional literal CMD script."""

    task: Task
    argv: list[str]
    cwd: Path
    environment: dict[str, str]
    runtime_description: str
    source: str = ""
    command_script: str | None = None
    cmd_script: bool = False
    arguments: list[str] = field(default_factory=list)
    script_path: Path | None = None


def _mapping(value: object, where: str) -> dict[str, object]:
    """Require a string-keyed mapping; raise ValueError with its config path."""
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise ValueError(f"{where}: expected a mapping with string keys")
    return cast(dict[str, object], value)


def _string(value: object, where: str, *, empty: bool = False) -> str:
    """Require a NUL-free string, optionally allowing empty text."""
    if not isinstance(value, str) or "\0" in value or (not empty and not value.strip()):
        raise ValueError(f"{where}: expected {'a' if empty else 'a nonempty'} string without NUL")
    return value


def _strings(value: object, where: str) -> list[str]:
    """Validate an argument list without splitting, sorting, or deduplicating."""
    if not isinstance(value, list):
        raise ValueError(f"{where}: expected a list of strings")
    return [_string(item, where, empty=True) for item in cast(list[object], value)]


def _names(value: object, where: str) -> list[str]:
    """Normalize a profile/filter name or list, preserving first occurrence."""
    names = [value] if isinstance(value, str) else _strings(value, where)
    return list(dict.fromkeys(_string(name, where) for name in names))


def _variables(value: object, where: str) -> dict[str, str]:
    """Validate environment/prompt mappings and normalize Windows variable names."""
    result: dict[str, str] = {}
    for name, text in _mapping(value, where).items():
        if not ENV_NAME.fullmatch(name):
            raise ValueError(f"{where}: invalid variable name {name!r}")
        result[name.upper() if os.name == "nt" else name] = _string(text, f"{where}.{name}", empty=True)
    return result


def _unknown(data: Mapping[str, object], allowed: set[str] | frozenset[str], where: str) -> None:
    """Reject misspelled or unsupported keys instead of silently ignoring them."""
    extra = data.keys() - allowed
    if extra:
        raise ValueError(f"{where}: unknown fields: {', '.join(sorted(extra))}")


def _validate_run(run: dict[str, object], where: str) -> None:
    """Validate one atomic execution payload; raise ValueError on bad combinations."""
    payload = {k: v for k, v in run.items() if k not in CONTEXT_KEYS}
    if not payload:
        return
    kind = RunType(_string(run.get("type"), f"{where}.type"))
    common = {"type"} | CONTEXT_KEYS
    runtime_keys = {"runtime", "runtime-executable", "runtime-args", "conda-environment", "conda-prefix"}
    allowed = {
        RunType.SHELL: common | runtime_keys | {"command"},
        RunType.EXEC: common | {"executable", "args"},
        RunType.SCRIPT: common | runtime_keys | {"script-path", "args"},
        RunType.CODE: common | runtime_keys | {"code", "args"},
    }
    _unknown(run, allowed[kind], where)
    for key in ("args", "runtime-args"):
        if key in run:
            _strings(run[key], f"{where}.{key}")
    for key in ("executable", "script-path", "code", "runtime-executable", "conda-environment", "conda-prefix"):
        if key in run:
            _string(run[key], f"{where}.{key}")
    if kind == RunType.EXEC:
        _string(run.get("executable"), f"{where}.executable")
        return
    runtime = RuntimeKind(_string(run["runtime"], f"{where}.runtime")) if "runtime" in run else None
    if kind != RunType.SHELL and runtime is None:
        raise ValueError(f"{where}: script/code requires an explicit runtime")
    if kind == RunType.SHELL:
        if runtime is not None and runtime not in SHELL_KINDS:
            raise ValueError(f"{where}: shell requires a shell runtime")
        command = run.get("command")
        if isinstance(command, list):
            commands = _strings(command, f"{where}.command")
            if not commands or any(not c.strip() for c in commands):
                raise ValueError(f"{where}.command: expected nonempty command blocks")
        else:
            _string(command, f"{where}.command")
    if kind == RunType.CODE:
        _string(run.get("code"), f"{where}.code")
        if runtime not in PYTHON_KINDS | {RuntimeKind.NODE, RuntimeKind.BUN}:
            raise ValueError(f"{where}: code supports Python, Node, or Bun; use script for other runtimes")
    if kind == RunType.SCRIPT:
        _string(run.get("script-path"), f"{where}.script-path")
    if runtime == RuntimeKind.PYTHON and "runtime-executable" not in run:
        raise ValueError(f"{where}: python requires runtime-executable; use conda-python or python-current otherwise")
    if runtime == RuntimeKind.CURRENT_PYTHON and "runtime-executable" in run:
        raise ValueError(f"{where}: python-current always uses the current interpreter")
    if "conda-environment" in run and "conda-prefix" in run:
        raise ValueError(f"{where}: choose conda-environment or conda-prefix, not both")
    if runtime != RuntimeKind.CONDA and ("conda-environment" in run or "conda-prefix" in run):
        raise ValueError(f"{where}: conda options require conda-python")


def _validate_layer(data: dict[str, object], where: str, extra: set[str]) -> None:
    """Check a profile/task layer, including nested context and machine bindings."""
    _unknown(data, LAYER_KEYS | extra, where)
    if "inherit" in data:
        _names(data["inherit"], f"{where}.inherit")
    for key in FILTER_KEYS:
        if key in data:
            values = _names(data[key], f"{where}.{key}")
            if key == "platform" and any(v.lower() not in {"windows", "win32", "macos", "darwin", "linux"} for v in values):
                raise ValueError(f"{where}.platform: unsupported platform")
    if "cwd" in data:
        _string(data["cwd"], f"{where}.cwd")
    run = _mapping(data.get("run", {}), f"{where}.run")
    for scope in (data, run):
        for key in CONTEXT_KEYS:
            if key in scope:
                _variables(scope[key], f"{where}.{key}")
    _validate_run(run, f"{where}.run")
    bindings = data.get("default-shell-binding", [])
    if not isinstance(bindings, list):
        raise ValueError(f"{where}.default-shell-binding: expected a list")
    for item in cast(list[object], bindings):
        binding = _mapping(item, f"{where}.default-shell-binding[]")
        _unknown(binding, FILTER_KEYS | {"runtime"}, where)
        for key in FILTER_KEYS:
            if key in binding:
                choices = _names(binding[key], f"{where}.binding.{key}")
                if key == "platform" and any(v.lower() not in {"windows", "win32", "macos", "darwin", "linux"} for v in choices):
                    raise ValueError(f"{where}.binding.platform: unsupported platform")
        if RuntimeKind(_string(binding.get("runtime"), f"{where}.binding.runtime")) not in SHELL_KINDS:
            raise ValueError(f"{where}: default shell binding requires a shell runtime")


def _profile_layers(
    settings: dict[str, object], name: str, applied: set[str], stack: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    """Expand profiles parent-first with separate cycle and deduplication state."""
    chain = (*stack, name)
    if name in stack:
        raise ValueError(f"Circular profile inheritance: {' -> '.join(chain)}")
    if len(chain) > MAX_PROFILE_DEPTH:
        raise ValueError(f"Profile inheritance depth exceeds {MAX_PROFILE_DEPTH}")
    if name not in settings:
        raise ValueError(f"Unknown profile: {' -> '.join(chain)}")
    if name in applied:
        return []
    profile = _mapping(settings[name], f"settings.{name}")
    result: list[dict[str, object]] = []
    for parent in _names(profile.get("inherit", []), f"settings.{name}.inherit"):
        result.extend(_profile_layers(settings, parent, applied, chain))
    applied.add(name)
    result.append(profile)
    return result


def _resolve_layers(settings: dict[str, object], task: dict[str, object], sub: dict[str, object]) -> dict[str, object]:
    """Merge defaults, unique profiles, parent, and child without losing context."""
    applied: set[str] = set()
    layers = _profile_layers(settings, "default", applied) if "default" in settings else []
    for layer in (task, sub):
        for name in _names(layer.get("inherit", []), "inherit"):
            layers.extend(_profile_layers(settings, name, applied))
        layers.append(layer)
    result: dict[str, object] = {}
    variables: dict[str, str] = {}
    prompts: dict[str, str] = {}
    bindings: list[object] = []
    for layer in layers:
        for key in FILTER_KEYS | {"cwd"}:
            if key in layer:
                result[key] = layer[key]
        bindings.extend(cast(list[object], layer.get("default-shell-binding", [])))
        run = _mapping(layer.get("run", {}), "run")
        for scope in (layer, run):
            variables.update(_variables(scope.get("environment", {}), "environment"))
            prompts.update(_variables(scope.get("interactive-inputs", {}), "interactive-inputs"))
        payload = {k: v for k, v in run.items() if k not in CONTEXT_KEYS}
        if payload:
            result["run"] = payload
    result.update({"environment": variables, "interactive-inputs": prompts, "default-shell-binding": bindings})
    if "run" not in result:
        raise ValueError("Final task has no run payload")
    return result


def _parse_schema(value: object) -> list[Task]:
    """Validate the whole schema, including unused profiles, and resolve leaves."""
    schema = _mapping(value, "schema")
    _unknown(schema, {"schema-version", "settings", "tasks"}, "schema")
    if type(schema.get("schema-version", 1)) is not int or schema.get("schema-version", 1) != 1:
        raise ValueError("schema-version must be 1")
    settings = _mapping(schema.get("settings", {}), "settings")
    for name, profile in settings.items():
        _string(name, "profile name")
        _validate_layer(_mapping(profile, f"settings.{name}"), f"settings.{name}", set())
        _profile_layers(settings, name, set())
    groups = _mapping(schema.get("tasks"), "tasks")
    tasks: list[Task] = []
    for group, entries in groups.items():
        _check_identifier(group, "group")
        if not isinstance(entries, list):
            raise ValueError(f"tasks.{group}: expected a task list")
        names: set[str] = set()
        for entry in cast(list[object], entries):
            task = _mapping(entry, f"tasks.{group}[]")
            name = _check_identifier(task.get("name"), f"tasks.{group}.name")
            if name in names:
                raise ValueError(f"Duplicate task: {group}/{name}")
            names.add(name)
            _validate_layer(task, f"tasks.{group}.{name}", {"name", "sub-tasks"})
            # Validate even a parent's profile references shadowed by child fields.
            for profile_name in _names(task.get("inherit", []), "inherit"):
                _profile_layers(settings, profile_name, set())
            children = task.get("sub-tasks")
            if children is None and "sub-tasks" not in task:
                tasks.append(Task(group, name, None, _resolve_layers(settings, task, {})))
                continue
            if not isinstance(children, list) or not children:
                raise ValueError(f"{group}/{name}.sub-tasks: expected a nonempty list")
            sub_names: set[str] = set()
            for child in cast(list[object], children):
                sub = _mapping(child, f"{group}/{name}.sub-tasks[]")
                sub_name = _check_identifier(sub.get("name"), "sub-task.name")
                if sub_name in sub_names:
                    raise ValueError(f"Duplicate sub-task: {group}/{name}/{sub_name}")
                sub_names.add(sub_name)
                _validate_layer(sub, f"{group}/{name}/{sub_name}", {"name"})
                tasks.append(Task(group, name, sub_name, _resolve_layers(settings, task, sub)))
    if not tasks:
        raise ValueError("Schema contains no executable tasks")
    return tasks


def _check_identifier(value: object, where: str) -> str:
    """Require an unambiguous menu/CLI identifier without slash separators."""
    name = _string(value, where)
    if name != name.strip() or "/" in name or "\\" in name:
        raise ValueError(f"{where}: names cannot contain slashes or surrounding whitespace")
    return name


def _matches(config: dict[str, object]) -> bool:
    """Match effective machine filters: OR inside a list, AND between fields."""
    current = {"platform": sys.platform, "arch": System.get_arch(), "computer-name": System.get_computer_name()}
    for key in FILTER_KEYS:
        choices = _names(config.get(key, []), key)
        aliases = PLATFORM_ALIASES if key == "platform" else ARCH_ALIASES if key == "arch" else {}
        normalized = [aliases.get(v.lower(), v.lower()) for v in choices]
        if normalized and current[key].lower() not in normalized:
            return False
    return True


def _runtime(task: Task) -> RuntimeKind:
    """Select the explicit runtime, last matching binding, or platform default."""
    run = _mapping(task.config["run"], "run")
    if "runtime" in run:
        return RuntimeKind(_string(run["runtime"], "runtime"))
    selected = {"win32": RuntimeKind.POWERSHELL, "darwin": RuntimeKind.ZSH}.get(sys.platform, RuntimeKind.BASH)
    for item in cast(list[object], task.config["default-shell-binding"]):
        binding = _mapping(item, "binding")
        if _matches(binding):
            selected = RuntimeKind(_string(binding["runtime"], "binding.runtime"))
    return selected


def _input_values(task: Task, supplied: list[str], *, interactive: bool) -> dict[str, str]:
    """Collect each final prompt once; explicit NAME=VALUE entries overwrite."""
    prompts = _variables(task.config["interactive-inputs"], "interactive-inputs")
    values: dict[str, str] = {}
    for item in supplied:
        name, separator, value = item.partition("=")
        name = name.upper() if os.name == "nt" else name
        if not separator or name not in prompts:
            raise ValueError(f"--input requires a declared input NAME=VALUE: {name}")
        values[name] = _string(value, f"--input {name}", empty=True)
    for name, prompt in prompts.items():
        if name not in values:
            if not interactive:
                raise ValueError(f"Input {name} is required; provide --input {name}=VALUE")
            # input() deliberately preserves whitespace, unlike Input.prompt().
            values[name] = input(f"{FLYellow}{prompt} {CRst}")
    return values


def _build_plan(task: Task, schema_path: Path, invocation_dir: Path, inputs: dict[str, str]) -> ExecutionPlan:
    """Resolve an execution plan, probing runtimes but never executing task code.

    Relative cwd uses invocation_dir; script paths use resolved cwd. Runtime
    probes may launch short-lived processes. Raises ValueError on missing paths,
    invalid templates, missing runtimes, or unsupported command arguments.
    """
    placeholders = {"schema_dir": str(schema_path.parent), "script_dir": str(SCRIPT_DIR),
                    "current_dir": str(invocation_dir), "pathsep": os.pathsep}
    env = Paths.resolve_environment(os.environ, _variables(task.config["environment"], "environment"), inputs, placeholders)

    def expand(value: object) -> str:
        return Paths.expand_template(_string(value, "template", empty=True), env, placeholders)

    def path(value: object, base: Path, *, resolve_symlinks: bool = True) -> Path:
        return Path(Paths.resolve_path(
            expand(value), base, expand_environment=False, resolve_symlinks=resolve_symlinks,
        ))

    cwd = path(task.config["cwd"], invocation_dir) if "cwd" in task.config else invocation_dir
    if not cwd.is_dir():
        raise ValueError(f"Working directory not found: {cwd}")
    run = _mapping(task.config["run"], "run")
    kind = RunType(_string(run["type"], "run.type"))
    args = [expand(a) for a in _strings(run.get("args", []), "run.args")]
    if kind == RunType.EXEC:
        name = expand(run["executable"])
        candidate = Environment.which(name, environment=env, cwd=cwd)
        if not candidate or not Path(candidate).is_file():
            raise ValueError(f"Executable not found: {name}")
        if os.name == "nt" and Path(candidate).suffix.lower() not in {".exe", ".com"}:
            raise ValueError("exec requires a native executable; use shell/script with cmd for batch files")
        return ExecutionPlan(task, [candidate, *args], cwd, env, "direct executable", arguments=args)

    runtime = _runtime(task)
    override = str(path(run["runtime-executable"], cwd, resolve_symlinks=False)) if "runtime-executable" in run else None
    executable, version = Environment.resolve_runtime(runtime, executable=override, environment=env, cwd=cwd)
    options = [expand(a) for a in _strings(run.get("runtime-args", []), "runtime-args")]
    script = path(run["script-path"], cwd) if kind == RunType.SCRIPT else None
    if script is not None and not script.is_file():
        raise ValueError(f"Script not found: {script}")
    source = ""
    if kind == RunType.SHELL:
        command = run["command"]
        source = "\n".join(_strings(command, "command")) if isinstance(command, list) else _string(command, "command")
    elif kind == RunType.CODE:
        source = _string(run["code"], "code")
    argv = [executable]
    command_script: str | None = None
    if runtime in {RuntimeKind.PWSH, RuntimeKind.POWERSHELL}:
        argv.extend(["-NoLogo", "-NoProfile", *options])
        if script is not None:
            argv.extend(["-File", str(script), *args])
        else:
            argv.extend(["-EncodedCommand", base64.b64encode(source.encode("utf-16-le")).decode("ascii")])
    elif runtime == RuntimeKind.CMD:
        if options:
            raise ValueError("cmd does not support runtime-args; place options inside command")
        if script is not None:
            argv.extend(["/d", "/s", "/c", str(script), *args])
        else:
            command_script = f"@echo off\n{source}\n"
            argv.extend(["/d", "/s", "/c", TEMP_SCRIPT])
        if any(any(c in arg for c in '\"%!\r\n') for arg in argv[4:]):
            raise ValueError('cmd script paths/args cannot contain quotes, %, !, or newlines; use a literal shell command instead')
    elif runtime in {RuntimeKind.BASH, RuntimeKind.GIT_BASH, RuntimeKind.ZSH}:
        argv.extend(["-f"] if runtime == RuntimeKind.ZSH else ["--noprofile", "--norc"])
        argv.extend(options)
        argv.extend([str(script).replace("\\", "/"), *args] if script is not None else ["-c", source])
    elif runtime in PYTHON_KINDS:
        if runtime == RuntimeKind.CONDA:
            selector = ["-p", str(path(run["conda-prefix"], cwd))] if "conda-prefix" in run else ["-n", expand(run.get("conda-environment", "base"))]
            argv.extend(["run", "--no-capture-output", *selector, "python"])
            _probe_dependency(
                [*argv, "-c", "import os,sys; sys.exit(0 if os.path.normcase(sys.prefix) == os.path.normcase(os.environ.get('CONDA_PREFIX', '')) else 1)"],
                cwd, env, "Conda environment must exist and contain its own Python",
            )
        argv.extend(options)
        if runtime == RuntimeKind.CONDA:
            # Conda's Windows batch wrapper cannot preserve multiline or quoted
            # argv reliably. Only a fixed single-line bootstrap crosses it.
            env[CONDA_PAYLOAD_ENV] = json.dumps({
                "kind": kind.value, "code": source,
                "argv": [str(script) if script is not None else "-c", *args],
                "import_path": str(script.parent) if script is not None else "",
            }, ensure_ascii=True)
            argv.extend(["-c", CONDA_BOOTSTRAP])
        else:
            argv.extend([str(script), *args] if script is not None else ["-c", source, *args])
    elif runtime == RuntimeKind.DENO:
        argv.extend(["run", *options, str(script), *args])
    else:
        argv.extend(options)
        if runtime == RuntimeKind.TSX:
            _probe_dependency(
                [executable, "--input-type=module", "-e", "import.meta.resolve('tsx')"],
                cwd, env, "tsx must already be installed in the target Node project",
            )
            argv.extend(["--import=tsx"])
        argv.extend([str(script), *args] if script is not None else ["-e", source, "--", *args])
    return ExecutionPlan(task, argv, cwd, env, f"{runtime.value}: {version}", source, command_script, runtime == RuntimeKind.CMD, args, script)


def _probe_dependency(argv: list[str], cwd: Path, environment: dict[str, str], message: str) -> None:
    """Check an environment/package without executing the configured task.

    Starts a bounded read-only probe; raises ValueError if unavailable. Probe
    output is not echoed because it may include inherited environment details.
    """
    try:
        result = subprocess.run(argv, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"{message}: {type(exc).__name__}") from exc
    if result.returncode:
        raise ValueError(message)


def _execute(plan: ExecutionPlan) -> int:
    """Run a plan with inherited terminal streams and return the child exit code.

    Creates a temporary .cmd only for inline CMD code and removes it on exit.
    Ctrl+C interrupts the process group, then escalates cleanup if necessary;
    detached background services are outside the runner's process lifetime.
    """
    with tempfile.TemporaryDirectory(prefix="run-commands-") as directory:
        argv = list(plan.argv)
        if plan.command_script is not None:
            script = Path(directory) / "command.cmd"
            # CMD reads the active console code page, not UTF-8 unconditionally.
            encoding = "utf-8"
            if os.name == "nt":
                encoding = f"cp{ctypes.windll.kernel32.GetConsoleCP() or 65001}"
            script.write_text(plan.command_script, encoding=encoding, newline="\r\n")
            argv = [str(script) if arg == TEMP_SCRIPT else arg for arg in argv]
        command: list[str] | str = argv
        if plan.cmd_script:
            quoted = " ".join(f'"{arg}"' for arg in argv[4:])
            command = f'"{argv[0]}" /d /s /c "{quoted}"'
        proc = subprocess.Popen(
            command, cwd=plan.cwd, env=plan.environment,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        try:
            return proc.wait()
        except KeyboardInterrupt:
            try:
                if os.name == "nt":
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(proc.pid, signal.SIGINT)
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                if os.name == "nt":
                    taskkill = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/taskkill.exe"
                    subprocess.run([str(taskkill), "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=5)
                else:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
            raise


def _select_task(tasks: list[Task], task_id: str | None, sub_name: str | None) -> Task | None:
    """Select one machine-matched task without silently picking ambiguous leaves."""
    parents = list(dict.fromkeys(t.parent_id for t in tasks))
    if task_id is None:
        if not Console.has_interactive_input():
            raise ValueError("Non-interactive execution requires --task")
        choice: object = Menu.select(
            [MenuOption([str(i)], name, name) for i, name in enumerate(parents, 1)] + [MenuOption(["Q"], "Exit", None)],
            prompt="Task", required=True,
        )
        if choice is None:
            return None
        task_id = _string(choice, "selected task")
    matches = [t for t in tasks if t.parent_id == task_id]
    if sub_name is not None:
        matches = [t for t in matches if t.sub_name == sub_name]
    if not matches:
        raise ValueError(f"No matching task on this machine: {task_id}{f'/{sub_name}' if sub_name else ''}")
    if len(matches) == 1:
        return matches[0]
    if not Console.has_interactive_input():
        raise ValueError(f"Multiple sub-tasks match {task_id}; specify --sub-task")
    selected: object = Menu.select(
        [MenuOption([str(i)], task.label, i - 1) for i, task in enumerate(matches, 1)] + [MenuOption(["Q"], "Cancel", None)],
        prompt="Sub-task", required=True,
    )
    return matches[selected] if isinstance(selected, int) else None


def _parser() -> argparse.ArgumentParser:
    """Build the colored command-line interface, including dependency help."""
    parser = argparse.ArgumentParser(
        description=f"{FLYellow}{'RUN COMMANDS':^60}{CRst}\n\nSelect and execute a YAML task on the current machine.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""Requirements:
  PyYAML; only the selected task's runtime/program must be installed.
  conda-python: Conda. tsx: Node and the project's installed tsx package.
  No automatic downloads, installation, or cross-runtime fallback.

Configuration:
  Interactive startup prompts for the YAML path; its default comes from
  --schema-file or {SCHEMA_ENV}. Without either, enter a path.
  With --task or redirected stdin, --schema-file or {SCHEMA_ENV}
  is required and used directly; --schema-file takes precedence.
  {SCHEMA_SAMPLE.name} is documentation, never an automatic default.
  Relative paths use invocation cwd (or task cwd), not the schema directory.
  --dry-run/--doctor probe runtimes; --validate/--list do not start tasks.
  Inputs are literal child environment values, never command substitution.
  --yes skips confirmation, not required input prompts.

Examples:
  conda run --no-capture-output -n base python tools/run-commands.py
  conda run -n base python tools/run-commands.py --schema-file ./commands.yaml --list
  conda run -n base python tools/run-commands.py --task android/adb-devices --yes
  conda run -n base python tools/run-commands.py --schema-file ./commands.yaml --validate
""",
    )
    parser.add_argument("--schema-file", help="YAML path; prompt default interactively, direct selection with --task or redirected stdin")
    parser.add_argument("--task", help="Exact GROUP/NAME task identifier")
    parser.add_argument("--sub-task", help="Exact child name (requires --task)")
    parser.add_argument("--input", action="append", default=[], metavar="NAME=VALUE", help="Supply an interactive input; repeatable, last value wins")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--list", action="store_true", help="List machine-matched leaf tasks")
    modes.add_argument("--validate", action="store_true", help="Validate all profiles and tasks without runtime probes")
    modes.add_argument("--doctor", action="store_true", help="Resolve plans for matching tasks (supply required inputs)")
    modes.add_argument("--dry-run", action="store_true", help="Resolve and display the selected plan without execution")
    parser.add_argument("--yes", action="store_true", help="Skip execution confirmation")
    return parser


def _select_schema_path(cli_path: str | None, *, interactive: bool, invocation_dir: Path) -> Path:
    """Select a real configuration using the shared interactive path prompt.

    Args:
        cli_path: Optional explicit path; takes precedence over SCHEMA_ENV.
        interactive: Prompt even when a default exists. False uses the chosen
            path directly and rejects a missing configuration.
        invocation_dir: Base directory for direct relative configuration paths.

    Returns:
        Absolute selected path. The sample is never selected automatically.

    Raises:
        ValueError: A direct path is absent, empty, or has undefined variables.
        EOFError: The user closes stdin while selecting a path.
        SystemExit: The shared path prompt's Exit action is selected.

    Side effects:
        Prints hints and prompts only in interactive mode; checks paths through
        Input.resolve_input_path, matching the rclone-sync selection workflow.
    """
    default = cli_path if cli_path is not None else os.environ.get(SCHEMA_ENV, "")
    if interactive:
        if not default:
            print(f"{FGray}Tip: set {FLCyan}{SCHEMA_ENV}{FGray} to your YAML configuration path.{CRst}")
            print(f"{FGray}Reference sample (not a default): {SCHEMA_SAMPLE}{CRst}")
        # The shared prompt normalizes/expands the selected path itself. Do not
        # template-expand its result a second time.
        return Path(Input.resolve_input_path(default, prompt="Path to YAML schema file", path_type="file"))
    if not default:
        raise ValueError(f"No configuration path supplied; use --schema-file or set {SCHEMA_ENV}")
    expanded = Paths.expand_template(_string(default, "schema path"), os.environ, {
        "current_dir": str(invocation_dir), "script_dir": str(SCRIPT_DIR),
    })
    return Path(Paths.resolve_path(expanded, invocation_dir, expand_environment=False))


def main() -> int:
    """Load configuration, select a task, and return its execution exit code.

    Prints menus and plans; may prompt and start child processes. Configuration
    and launch failures return 2. KeyboardInterrupt propagates to the entrypoint.
    """
    parsed = _parser().parse_args()
    Console.print_banner("RUN COMMANDS")
    try:
        import yaml
    except ImportError:
        print(f"{FLRed}Missing dependency: PyYAML. Install with: conda run -n base python -m pip install PyYAML{CRst}")
        return 2
    try:
        if parsed.sub_task and not parsed.task:
            raise ValueError("--sub-task requires --task")
        invocation_dir = Path.cwd()
        try:
            schema_path = _select_schema_path(
                parsed.schema_file,
                interactive=parsed.task is None and Console.has_interactive_input(),
                invocation_dir=invocation_dir,
            )
        except EOFError:
            print(f"\n{FGray}Configuration selection cancelled.{CRst}")
            return 0
        with schema_path.open(encoding="utf-8") as handle:
            raw: object = yaml.safe_load(handle)
        tasks = _parse_schema(raw)
        if parsed.validate:
            print(f"{FLGreen}Valid schema: {len(tasks)} leaf task(s).{CRst}")
            return 0
        available = [task for task in tasks if _matches(task.config)]
        if parsed.list:
            for task in available:
                print(task.label)
            return 0
        if not available:
            raise ValueError("No tasks match this machine")
        if parsed.doctor:
            targets = [task for task in available if (not parsed.task or task.parent_id == parsed.task) and (not parsed.sub_task or task.sub_name == parsed.sub_task)]
            if not targets:
                raise ValueError("No matching task for --doctor")
            failed = False
            for task in targets:
                try:
                    prompts = _variables(task.config["interactive-inputs"], "interactive-inputs")
                    supplied = [item for item in parsed.input if (item.partition("=")[0].upper() if os.name == "nt" else item.partition("=")[0]) in prompts]
                    inputs = _input_values(task, supplied, interactive=False)
                    plan = _build_plan(task, schema_path, invocation_dir, inputs)
                    print(f"{FLGreen}{task.label}{CRst}: {plan.runtime_description}\n  {plan.argv[0]}")
                except (ValueError, OSError) as exc:
                    failed = True
                    print(f"{FLYellow}{task.label}{CRst}: {exc}")
            return 2 if failed else 0
        task = _select_task(available, parsed.task, parsed.sub_task)
        if task is None:
            return 0
        inputs = _input_values(task, parsed.input, interactive=Console.has_interactive_input())
        plan = _build_plan(task, schema_path, invocation_dir, inputs)
        print(f"{FLCyan}Task:{CRst} {task.label}\n{FGray}Runtime: {plan.runtime_description}\nExecutable: {plan.argv[0]}\nWorking directory: {plan.cwd}{CRst}")
        if plan.source:
            print(f"{FGray}Source (literal):{CRst}\n{plan.source}")
        if plan.script_path is not None:
            print(f"{FGray}Script:{CRst} {plan.script_path}")
        if plan.arguments:
            print(f"{FGray}Arguments:{CRst} {json.dumps(plan.arguments, ensure_ascii=False)}")
        if inputs:
            print(f"{FGray}Input variables: {', '.join(inputs)} (values not displayed){CRst}")
        if parsed.dry_run:
            print(f"{FLGreen}Dry run: task was not executed.{CRst}")
            return 0
        if not parsed.yes:
            if not Console.has_interactive_input():
                raise ValueError("Non-interactive execution requires --yes")
            if Input.prompt(f"{FLYellow}Execute? [y/N] {CRst}").lower() != "y":
                return 0
        Console.print_separator()
        sys.stdout.flush()
        code = _execute(plan)
        print(f"{FLGreen if code == 0 else FLRed}Process exited with code {code}.{CRst}")
        return code
    except (ValueError, OSError, EOFError, yaml.YAMLError) as exc:
        print(f"{FLRed}Error: {exc}{CRst}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{FLYellow}[Exit by Ctrl+C]{CRst}")
        sys.exit(130)
