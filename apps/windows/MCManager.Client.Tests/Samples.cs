namespace MCManager.Client.Tests;

internal static class Samples
{
    public const string Snapshot = """
    {"active": true, "cgroup": "/system.slice/mc_manager.service", "error": null, "frozen": false, "frozen_expires_ts": null, "frozen_since_ts": null, "id": 1, "loader": "Fabric", "maintenance": false, "mode": "always-on", "name": "survie", "path": "/home/mc/Servers/survie", "pid": 4821, "port": 25565, "port_holder": null, "rcon_port": 25575, "rss_kb": 6291456, "server": "survie", "sleep": {"after_s": 7200, "allow": ["Steve"], "enabled": true, "freeze": false, "hold_timeout_s": 120, "internal_port": null, "join_mode": "kick", "proxy_protocol": null}, "state": "running", "stop_reason": null, "suspended": false, "swap_kb": 0, "uptime_s": 7312, "version": "1.21.1"}
    """;

    public const string ServerList = """
    {"active": "survie", "code": "status", "ok": true, "schema": 1, "servers": [
    {"active": true, "error": null, "frozen": false, "id": 1, "loader": "Fabric", "maintenance": false, "mode": "always-on", "name": "survie", "path": "/home/mc/Servers/survie", "pid": 4821, "port": 25565, "rss_kb": 6291456, "server": "survie", "state": "running", "stop_reason": null, "uptime_s": 7312, "version": "1.21.1"}]}
    """;

    public const string Players = """
    {"code": "players", "max": 20, "ok": true, "online": 2, "players": ["Steve", "Alex"], "schema": 1, "server": "survie", "state": "running"}
    """;

    public const string Whitelist = """
    {"code": "whitelist_list", "enabled": true, "entries": [{"name": "Notch", "uuid": "069a79f4-44e9-4726-a5be-fca90e38aaf5"}], "ok": true, "schema": 1, "server": "survie"}
    """;

    public const string BanAdded = """
    {"changed": true, "code": "ban_added", "ok": true, "schema": 1, "server": "survie", "subject": "Notch", "via": "rcon"}
    """;

    public const string BanRemoved = """
    {"changed": true, "code": "ban_removed", "ok": true, "schema": 1, "server": "survie", "subject": "Notch", "via": "file"}
    """;

    public const string Started = """
    {"code": "started", "message": null, "ok": true, "outside_service": false, "schema": 1, "server": "survie"}
    """;

    public const string Stopped = """
    {"code": "stopped", "message": null, "ok": true, "reason": "maintenance", "schema": 1, "server": "survie"}
    """;

    public const string Resumed = """
    {"code": "resumed", "mode": "always-on", "ok": true, "running": false, "schema": 1, "server": "survie", "start": null, "was_crashed": false}
    """;

    public const string RestartJob = """
    {"code": null, "created_at": "2026-10-08T10:00:00Z", "id": "j_restartserve", "kind": "restartServer", "progress": 0, "result": null, "server": null, "state": "running", "updated_at": "2026-10-08T10:00:00Z"}
    """;

    public const string Backups = """
    {"backups": [{"created": "2026-10-08T12:00:03", "created_ts": 1791460803, "encrypted": false, "file": "survie_midi_2026-10-08_12-00.zip", "id": "survie_midi_2026-10-08_12-00", "path": "/home/mc/Backup/survie_midi_2026-10-08_12-00.zip", "size": 1288490188, "type": "midi"}], "code": "backup_list", "count": 1, "keep": 3, "ok": true, "remotes": ["offsite"], "retention_days": 0, "schema": 1, "server": "survie"}
    """;

    public const string BackupJob = """
    {"code": null, "created_at": "2026-10-08T10:00:00Z", "id": "j_createbackup", "kind": "createBackup", "progress": 0, "result": null, "server": null, "state": "running", "updated_at": "2026-10-08T10:00:00Z"}
    """;

    public const string Jobs = """
    {"code": "jobs", "jobs": [{"code": null, "created_at": "2026-10-08T10:00:00Z", "id": "j_01", "kind": "createBackup", "progress": 40, "result": null, "server": "survie", "state": "running", "updated_at": "2026-10-08T10:00:05Z"}], "ok": true, "schema": 1}
    """;

    public const string ConsoleReply = """
    {"code": "console_reply", "ok": true, "output": "There are 2 of a max of 20 players online: Steve, Alex", "schema": 1, "server": "survie"}
    """;

    public const string Kicked = """
    {"code": "kicked", "ok": true, "schema": 1, "server": "survie", "subject": "Steve"}
    """;

    public const string Unauthorized = """
    {"code": "unauthorized", "message": "Device token missing or revoked.", "ok": false}
    """;
}
