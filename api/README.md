# MC Manager API v1 - contract

`openapi.json` is the OpenAPI 3.1 description of the HTTP API served by the MC Manager
daemon. It is written before the server: the implementation has to match it, and a test
compares the two once the routes exist.

## Files

| File | Role |
|---|---|
| `src/*.json` | Sources, one per resource group (`servers`, `players`, `world`, `content`, `backups`, `tasks`, `alerts`, `system`, `events`, `remote`, `components`). Edit these. |
| `build_openapi.py` | Merges the sources into `openapi.json` (2-space indent, sorted keys). Fails on a duplicate path, component or top-level field. `--check` only compares. |
| `openapi.json` | Built contract. Never edit by hand. |
| `../Linux/tests/test_openapi.py` | Validates the contract and checks that `openapi.json` is exactly the output of the script. |

```
python3 api/build_openapi.py          # rebuild
python3 api/build_openapi.py --check  # exit 1 if openapi.json drifted
cd Linux && python3 -m unittest tests.test_openapi -v
```

A source file holds `paths` and/or `components`. `components.json` also holds the document
header (`openapi`, `info`, `servers`, `security`, `tags`) and the shared responses and parameters.

## Reading the contract

- Every path starts with `/v1`. `{server}` is a server name, its numeric id, or `active`.
- Every response body is an object `{"schema": 1, "ok": bool, "code": "...", ...}`; these are the
  shapes that `mc ... --json` already prints, with `ok` and `code` always present. `code` is a stable
  identifier, never translated. Failures use the `Error` schema
  `{ok:false, code, message, detail?}` plus the contextual fields of the failed operation.
- `x-mcm-role` (`viewer`, `operator`, `admin`) is the minimum role of the device for the operation.
  `x-mcm-source` names the Python functions the daemon calls (`mc_api.start`, `mc_content.mod_list`...).
- Long operations answer `202` with a `Job` and a `Location` header; follow it on `GET /v1/jobs/{id}`
  or through the `job` events of `GET /v1/events`.
- Operations that did the work but report a business failure in their result (a failing backup
  destination test, an alert delivery) answer `200` with `ok:false`.
- Secrets are write-only: they appear in requests only (`writeOnly: true`) and never in a response.
  Responses carry `secrets_set`, the names of the configured secret fields. The only token ever returned
  is the device token of `POST /v1/pair`, once.
- Streams (`/v1/events`, `GET /v1/servers/{server}/console`) are `text/event-stream`. The `data:` of
  `/v1/events` is the `Event` schema; the SSE `event:` name equals its `type`.

## Versioning

- `info.version` follows semantic versioning: `1.x` only adds fields, operations or enum values; a
  rename, a removal or a type change means `2.0` and a new `/v2` prefix.
- The `schema` field of every body is the version of the JSON shapes (`mc_api.SCHEMA_VERSION`, 1);
  clients ignore unknown fields.
- `GET /v1` (unauthenticated) returns the API and daemon versions.

## HTTP status of result codes

The operation layer returns `code`; the HTTP layer maps it as follows.

| Status | Codes |
|---|---|
| 404 | `not_found`, `no_server`, `folder_missing`, `mod_not_found`, `pack_not_found`, `task_not_found`, `backup_not_found`, `remote_not_found`, `channel_not_found`, `no_remote`, `no_channel`, `java_not_installed`, `config_key_unset` |
| 409 | `server_running`, `stop_first`, `players_online`, `already_active`, `not_sleeping`, `already_frozen`, `mod_exists`, `mod_ambiguous`, `defines_blocks`, `folder_not_empty`, `remote_exists`, `channel_exists`, `task_name_taken`, `blocked_by_maintenance`, `downgrade_refused`, `job_finished`, `console_offline` |
| 422 | `bad_*`, `invalid_*`, `missing_*`, `confirm_required`, `confirmation_required`, `eula_required`, `name_required`, `sleep_after_too_short`, `sleep_needs_rcon`, `key_not_found`, `s3_credentials_missing`, `restic_password_missing`, `overworld_protected`, `unknown_dimension`, `unknown_loader`, `not_a_jar`, `unsafe_archive`, `no_level_dat`, `java_bad_choice`, `bad_signature` |
| 503 | `rcon_failed`, `rcon_error`, `daemon_timeout`, `source_unreachable`, `check_failed`, `java_download_failed` |
| 500 | `start_failed`, `stop_failed`, `still_running`, `backup_failed`, `safety_backup_failed`, `export_failed`, `import_failed`, `update_failed` |

Any other failing code is `500` until it is classified. Successes are `200`, `201` for a created
resource, `202` for a job.

## Coverage of `Linux/mc_api.py`

Every public function of `mc_api.py` is either exposed (listed in the `x-mcm-source` of at least one
operation) or listed below with the reason. `test_openapi.py` enforces this.

### Not exposed

| Function | Reason |
|---|---|
| `mc_api.parse_duration` | Text helper of the CLI (`5m`, `2h`); the API takes seconds. |
| `mc_api.result` | Constructor of the result envelope, not an operation. |
| `mc_api.load_server` | Resolves a `{server}` segment; used by the HTTP layer, not a route. |
| `mc_api.is_frozen` | Folded into `ServerSnapshot.frozen` (`getServer`, `listServers`). |
| `mc_api.freeze_expired` | Internal to the daemon tick that thaws an expired freeze. |

Exposed through a route that does not carry their name: `rcon_exec` (`sendConsoleCommand`, console
stream), `query_players` and `parse_player_list` (`listOnlinePlayers`), `read_freeze`, `server_state`
and `server_snapshot` (`getServer`, `listServers`), `sleep_info` (`getSleepSettings`), `task_find`
(`runTask`).

Operations with no `mc_api` function yet (they call lower-level modules, listed in `x-mcm-source`):
create and unregister a server, mode and schedule, Java, configuration by key, doctor, update,
metrics, pairing, devices, jobs, audit. A daemon-side operation layer has to be added for them.

## Known gaps between the contract and the current JSON output

To harmonise before implementing the API (the contract describes the target shape):

- `mc status --json` and `mc active --json` carry no `ok`/`code`; `mc players --json`,
  `mc java list --json` and `mc sleep status --json` neither. Failures there use a nested
  `error: {code, detail}` object instead of the top-level `ok:false, code`.
- `mc config get` prints the whole `config.json`, secrets included; the API returns the
  secret-free `ServerConfig`.
- `mc alert list --json` leaves webhook `headers` unmasked; `mc backup remote list --json` returns the S3
  `access_key` and the password file path. The API returns `header_names` and `secrets_set` instead.
- `mc mod list --json` overwrites the jar `version` with the tracked version for mods installed by name.
- `server_snapshot` names the server `name` and numbers it `id`; every operation result uses `server`.
- Existing failures have no `message`; the HTTP layer builds it from the language files.
- `doctor` has no machine output yet; `metrics`, jobs, pairing and devices are new.
