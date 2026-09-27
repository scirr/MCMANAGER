# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub: **Security → Report a vulnerability** on
[scirr/MCMANAGER](https://github.com/scirr/MCMANAGER/security/advisories/new).
Include what you found, how to reproduce it, and the MC Manager version
(`mc version`).

You will get an acknowledgement within 7 days. A fix is released as soon as
it is ready, and the report is credited in the release notes unless you
prefer otherwise. Please give us a reasonable time to fix the problem before
disclosing it.

## Supported versions

Only the latest release receives security fixes. Update with `mc update`.

## Scope

In scope:

- the `mc` command, the service (daemon) and the installers;
- the update mechanism: signature and hash verification, rollback;
- the sleep-mode listener exposed on the game port;
- files MC Manager writes (permissions, secrets such as the RCON password
  and the Discord webhook URL).

Out of scope: vulnerabilities in Minecraft itself, in server software
(Paper, Fabric, Forge, NeoForge), in mods, or in Java.

## How releases are protected

- Releases are built and published by GitHub Actions, never from a personal
  computer, with a build provenance attestation.
- `SHA256SUMS` lists the hashes of both packages and is signed with Ed25519
  (`SHA256SUMS.sig`). The private key exists only as a GitHub Actions secret;
  the public key is built into MC Manager.
- `mc update` installs nothing unless the signature and the hash both match,
  and keeps the previous version for `mc update --rollback`.

Verify a release by hand:

```bash
sha256sum -c --ignore-missing SHA256SUMS
gh attestation verify MCManager-Linux.zip --repo scirr/MCMANAGER
```
