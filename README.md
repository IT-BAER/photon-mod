# photon-mod

Personal patches for [Photon Studio](https://tenzen.studio/photon/) (Windows, per-user install) that
survive official updates. Contains no Photon files; patches are anchor/replacement pairs applied to
your own installed copy.

## Patches

| File | Effect |
|---|---|
| `10-no-announcements.json` | No install-ID ping, no announcement tracking, no pushed HTML |
| `11-no-update-check.json` | No in-app release check or electron-updater feed |
| `12-no-feedback.json` | Feedback dialog does not POST to tenzen.studio |

## Electron fuses

`fuses.json` is written into `Photon Studio.exe` on every `apply` (stock 0.1.21 wire `101100011`,
hardened `010001001`):

| Fuse | Value | Why |
|---|---|---|
| RunAsNode | off | exe can no longer be abused as a Node runtime via `ELECTRON_RUN_AS_NODE` |
| EnableNodeOptionsEnvironmentVariable | off | `NODE_OPTIONS` ignored |
| EnableNodeCliInspectArguments | off | no `--inspect` debugger attach |
| OnlyLoadAppFromAsar | on | a planted `resources\app` folder is not loaded |
| GrantFileProtocolExtraPrivileges | off | UI loads from Photon's own scheme, not `file://` |
| EnableCookieEncryption | on | cookie store encrypted with DPAPI |
| EnableEmbeddedAsarIntegrityValidation | off | must stay off, the patched app.asar has no embedded hash |

## Use

Requires Python 3 and PowerShell 7. Close Photon first.

```powershell
.\photon-mod.ps1 apply      # back up stock app.asar (once per version), write patched archive
.\photon-mod.ps1 verify     # OK / MISS per patch, exit 1 on any MISS
.\photon-mod.ps1 restore    # stock app.asar of the installed version back
.\photon-mod.ps1 update     # latest official build, silent install, re-apply
.\photon-mod.ps1 update -Installer .\Photon-Studio-x.y.z-win-x64.exe   # offline update
```

Stock `app.asar` and exe backups live in `%LOCALAPPDATA%\photon-mod\backup` (last two versions kept). If an update
changes code so that an anchor no longer matches, `apply` aborts and leaves the app untouched.

## Tests

```powershell
python tests\test_asar.py
python tests\test_fuses.py
```

Both use the newest stock backup (or the installed files) as a read-only fixture.
