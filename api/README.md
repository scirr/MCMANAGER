# MC Manager API v1 - contract

Describes MC Manager 2.11.0: 76 paths, 96 operations (`info.version` 1.0.0).

`openapi.json` is the OpenAPI 3.1 description of the HTTP API served by the MC Manager
daemon. It is written before the server: the implementation has to match it, and a test
compares the two once the routes exist.

## Files

| File | Role |
|---|---|
| `src/*.json` | Sources, one per resource group (`lifecycle`, `players`, `world`, `content`, `backups`, `tasks`, `alerts`, `system`, `router`, `events`, `remote`, `components`). Edit these. |
| `build_openapi.py` | Merges the sources into `openapi.json` (2-space indent, sorted keys). Fails on a duplicate path, component or top-level field. `--check` only compares. |
| `openapi.json` | Built contract. Never edit by hand. |
| `../core/tests/test_openapi.py` | Validates the contract, checks that `openapi.json` is exactly the output of the script, that no response schema names a secret, and that real `mc ... --json` runs (throw-away data folder, no server) fit their response schema. |

```
python3 api/build_openapi.py          # rebuild
python3 api/build_openapi.py --check  # exit 1 if openapi.json drifted
cd core && python3 -m unittest tests.test_openapi -v
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
| 404 | `not_found`, `no_server`, `folder_missing`, `mod_not_found`, `pack_not_found`, `task_not_found`, `backup_not_found`, `remote_not_found`, `channel_not_found`, `no_remote`, `no_channel`, `java_not_installed`, `config_key_unset`, `no_active_server`, `no_server`, `no_log_file`, `job_not_found` |
| 409 | `server_running`, `stop_first`, `players_online`, `already_active`, `not_sleeping`, `already_frozen`, `mod_exists`, `mod_ambiguous`, `defines_blocks`, `router_port_conflict`, `folder_not_empty`, `remote_exists`, `channel_exists`, `task_name_taken`, `blocked_by_maintenance`, `downgrade_refused`, `job_finished`, `console_offline`, `server_offline`, `config_conflict` |
| 422 | `bad_*`, `invalid_*`, `missing_*`, `confirm_required`, `confirmation_required`, `eula_required`, `name_required`, `sleep_after_too_short`, `sleep_needs_rcon`, `sleep_setting_refused`, `sleep_hold_timeout_range`, `command_required`, `command_not_allowed`, `warn_not_allowed`, `unsupported_on_windows`, `encrypt_key_missing`, `key_not_found`, `s3_credentials_missing`, `restic_password_missing`, `overworld_protected`, `unknown_dimension`, `unknown_loader`, `not_a_jar`, `unsafe_archive`, `no_level_dat`, `java_bad_choice`, `bad_signature`, `router_usage`, `status_page_interval_too_short` |
| 429 | `too_many_streams` |
| 501 | `not_implemented` |
| 503 | `rcon_failed`, `rcon_error`, `daemon_timeout`, `source_unreachable`, `check_failed`, `java_download_failed`, `announce_failed` |
| 500 | `start_failed`, `stop_failed`, `still_running`, `backup_failed`, `safety_backup_failed`, `export_failed`, `import_failed`, `update_failed`, `router_error`, `status_page_unwritable` |

Any other failing code is `500` until it is classified. Successes are `200`, `201` for a created
resource, `202` for a job.

## Coverage of `core/mc_api.py`

Every public function of `mc_api.py` is either exposed (listed in the `x-mcm-source` of at least one
operation) or listed below with the reason. `test_openapi.py` enforces this.

### Not exposed

| Function | Reason |
|---|---|
| `mc_api.parse_duration` | Text helper of the CLI (`5m`, `2h`); the API takes seconds. |
| `mc_api.render` | Text of a result code for the CLI; the API sends the code and a `message`. |
| `mc_api.wire` | Adds `schema` and a `message` on failures to a result; used by the HTTP layer for every body. |
| `mc_api.result` | Constructor of the result envelope, not an operation. |
| `mc_api.load_server` | Resolves a `{server}` segment; used by the HTTP layer, not a route. |
| `mc_api.is_frozen` | Folded into `ServerSnapshot.frozen` (`getServer`, `listServers`). |
| `mc_api.freeze_expired` | Internal to the daemon tick that thaws an expired freeze. |
| `mc_api.suspend` | Sleep freeze (SIGSTOP) driven by the daemon sleep loop; the setting is `freeze` of `setSleepSettings`. |
| `mc_api.restart_pending` | Feeds `pending_restart` of the router answers. |
| `mc_api.metrics_serve` | Foreground Prometheus listener of `mc metrics serve` (`metrics_bind`, `metrics_allow_remote`); it is its own endpoint, not an API route. `GET /v1/metrics` is the JSON view. |

Exposed through a route that does not carry their name: `rcon_exec` (`sendConsoleCommand`, console
stream), `query_players` and `parse_player_list` (`listOnlinePlayers`), `read_freeze`, `server_state`
and `server_snapshot` (`getServer`, `listServers`), `sleep_info` (`getSleepSettings`), `task_find`
(`runTask`).

Operations with no `mc_api` function yet (they call lower-level modules, listed in `x-mcm-source`):
create a server, schedule, Java, configuration by key, update, metrics, pairing, devices, jobs, audit. A daemon-side operation layer has to be added for them.

## Known gaps between the contract and the current JSON output

The `--json` outputs match the contract; `test_openapi.py` runs them and compares. What still differs:

- Failures of `mc status`, `mc players` and `mc active` still carry a nested `error: {code, detail}` next
  to the top-level `code` and `message`. It is deprecated (`Error.error`) and will go away in a later
  major version; read `code`, `message` and `detail`.
- `mc players --json` on a stopped server is a failure (`ok:false`, `code: server_offline`, exit 1).
- `mc config get --json` answers `{ok, code:"config", server, config, secrets_set}` and
  `mc config get <key> --json` answers `{ok, code:"config_value", key, value | write_only}`; without
  `--json` the previous output is unchanged.
- `mc backup` as a CLI command answers synchronously with `BackupCreated`; through the API it is a job whose
  `result` is that object.

## Local implementation (3.0 beta)

The daemon serves the contract on a local listener only: `run/api.sock` (0600) on Linux, `127.0.0.1:<port>`
with a bearer token in `run/api.token` on Windows. `mc api status|enable|disable` shows or switches it
(`api_local` in `api.json`, enabled by default). The remote operations (`remote` tag) exist and answer
`501 not_implemented`. `test_httpapi.py` fails when an operation has no handler or a handler is not in the contract.

Additions made while implementing: `404` on `GET`/`DELETE /v1/jobs/{job}`, `501` on the `remote` operations,
`message` in `DoctorReport` when the report is not ok, and the codes above (`config_set` failures
`key_not_found`, `invalid_value`, `config_conflict`; `too_many_streams`; `job_not_found`; `announce_failed`).
