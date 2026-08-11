# AGENTS.md

Before working in this repository, read the project-level Claude prompt:
`./CLAUDE.md`

The `CLAUDE.md` file in this same directory is authoritative for project
conventions, environment setup, utility APIs, coding style, and workflow rules.

## Python dependency declarations

- When new code imports a third-party Python library, first decide whether the
  library is a hard runtime dependency, an optional integration, or only a
  development/build dependency. Standard-library modules are not dependencies.
- Add hard dependencies used by the launcher or ordinary tools to
  `requirements.txt`. Do not add a library merely because it might be useful.
- Put dependencies used only by scripts under `tools/research/` in
  `requirements-research.txt`. Do not duplicate them in `requirements.txt`
  unless non-research code also requires them.
- Put optional platform integrations, test-only libraries, and standalone
  executable builders in `requirements-optional.txt`.
- Prefer unpinned requirements or a justified compatible version range. Do not
  use exact `==` pins by default. Keep the relevant README, module docstring,
  and `--help` dependency descriptions consistent with these files.
