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

## Use

Requires Python 3 and PowerShell 7. Close Photon first.

```powershell
.\photon-mod.ps1 apply      # back up stock app.asar (once per version), write patched archive
.\photon-mod.ps1 verify     # OK / MISS per patch, exit 1 on any MISS
.\photon-mod.ps1 restore    # stock app.asar of the installed version back
.\photon-mod.ps1 update     # latest official build, silent install, re-apply
.\photon-mod.ps1 update -Installer .\Photon-Studio-x.y.z-win-x64.exe   # offline update
```

Stock backups live in `%LOCALAPPDATA%\photon-mod\backup` (last two versions kept). If an update
changes code so that an anchor no longer matches, `apply` aborts and leaves the app untouched.

## Tests

```powershell
python tests\test_asar.py
```

Uses the installed `app.asar` (or the newest stock backup) as a read-only fixture.
