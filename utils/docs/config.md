# Configuration

[Utility index](../README.md)

Implementation: [config.py](../config.py).

## API reference

| Need | Use |
| --- | --- |
| User configuration directory/files | `ConfigStore.directory()`, `ConfigStore(name=GENERAL_CONFIG).path`; application filenames belong to their modules; `initialize()` creates only the general config |
| Read/update user configuration | `store.load()` returns {} for missing/empty files; reads/writes acquire a nonblocking per-file process/thread lock and raise `ConfigBusyError` (`status='busy'`) immediately on contention; `store.update(changes)` rereads/deep-merges and atomically replaces; `store.edit(callback)` supports removal; `ensure(initial=None)` creates only absent files; malformed YAML is never silently overwritten |
| Encrypted configuration strings | `EncryptedValue.encrypt(text, module_key)` creates opaque ciphertext; `.decrypt(module_key)` returns plaintext; `EncryptedValue.decrypt_tree(data, module_key)` decodes a module-owned nested schema/section. YAML `!encrypted` and unrelated writes preserve ciphertext without knowing its key; repr is redacted. Keys belong to each consuming module, never config.py |
| External YAML and redirects | `ConfigStore.parse(stream)` rejects duplicate explicit keys while permitting merge overrides; `read_file(path)` locks briefly and requires a string-keyed mapping; `resolve_file(path)` follows redirect-only mappings relative to each file, rejects missing/cyclic/mixed/overlong chains, returns final schema path |

## Configuration ownership

Use ConfigStore for project user settings. Resolve the directory through
`ConfigStore.directory()`; only `APP_DIRECTORY_NAME` in config.py defines its
name. Application filenames and encrypted-value keys belong to the consuming
module. Fixed keys provide obfuscation, not a security boundary; never log
decrypted values or commit user configuration.

Keep configuration keys and native environment-variable support documented in
[Environmental_Variables.md](../../Environmental_Variables.md). Missing/empty
configuration is distinct from malformed YAML; callers must not overwrite a
parse failure or retry a busy store in a loop.
