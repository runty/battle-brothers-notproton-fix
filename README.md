# Battle Brothers fix for NotProton

Run the Windows Steam version of **Battle Brothers** through **NotProton on macOS**, with an optional fix for a transparent title bar that cannot be dragged.

The OpenGL compatibility facade is by [MantasMikal](https://gist.github.com/MantasMikal/6845c01c8f1365791879991204eacdc7). This project adapts the Wine driver patch to the newer CrossOver build used by NotProton and adds a Battle Brothers-only native title-bar workaround.

## Verified configuration

| Component | Verified version |
| --- | --- |
| Game | Battle Brothers 1.5.2.3, Steam app ID `365360` |
| Mac | Apple silicon, macOS 27.2.1 |
| NotProton compatibility tool | **CrossOver 2026 11 11-ARM64 - Rosetta** |
| Internal runner | `crossover-27.0.0.41303-fex` |
| Wine driver | x86_64 `winemac.so`, SHA-256 `0c76b4f4f0a6b33dfacd1ee5bfba41dfe2e894b68901ff933f3310e3aa3eb2eb` |

Launching, rendering the main menu, and dragging the repaired title bar were confirmed on this setup. Full campaign stability has not been established. FEX execution and other Wine/CrossOver builds are unsupported; the installer refuses an unknown driver instead of guessing patch offsets.

Despite `-fex` in the runner folder name, select the **Rosetta** compatibility tool in Steam.

## Install

You need [NotProton](https://github.com/NotProtonNot/NotProton), its supported CrossOver runner, an installed Windows copy of Battle Brothers in Steam, Python 3.9 or later, and Apple's command-line build tools (`clang` and `codesign`). If the build tools are missing, run `xcode-select --install`.

1. In Steam → Battle Brothers → Properties → Compatibility, select **CrossOver 2026 11 11-ARM64 - Rosetta**.
2. Try launching the game once so NotProton creates its private runner, then quit the game completely. Failure to start at this point is expected.
3. Download this repository or clone it:

   ```sh
   git clone https://github.com/runty/battle-brothers-notproton-fix.git
   cd battle-brothers-notproton-fix
   ```

4. Check compatibility and compile the fix:

   ```sh
   python3 fix.py --check --titlebar
   ```

5. Install both fixes:

   ```sh
   python3 fix.py --install --titlebar
   ```

6. Launch Battle Brothers normally from Steam. No wrapper, Windows Steam installation, or special launch option is required for the fix.

The first check downloads a pinned revision of the upstream gist over HTTPS and verifies its SHA-256. It extracts and compiles the embedded C facade; it never executes the upstream shell script. The downloaded source is cached in `~/Library/Caches/battle-brothers-notproton-fix/`. It is not bundled in this repository; see [NOTICE.md](NOTICE.md).

`--check` leaves the installed driver and facade unchanged. It may create the source cache and installer lock file.

## Restore or change options

Quit the game before installing or restoring.

Remove the title-bar workaround while keeping the OpenGL fix:

```sh
python3 fix.py --install
```

Restore the original driver:

```sh
python3 fix.py --restore
```

Restore keeps the pristine backup and removes the per-user facade only when it still matches the recorded installation. Files changed by another tool are not silently overwritten. If you used the earlier local prototype, its old `/Users/Shared/bb_np_gl.dylib` may remain; this installer does not delete that legacy shared file.

## What changes

Only Battle Brothers' private runner driver is patched:

```text
~/Library/Application Support/notproton/launchers/365360/runner/lib/wine/x86_64-unix/winemac.so
```

The original is kept alongside it as `winemac.so.bbnp-backup`. The installer compiles a universal x86_64/arm64 facade at `/Users/Shared/bbnp-<your numeric user ID>.dylib`, redirects this driver's OpenGL lookup to it, and signs both files ad hoc. Installation metadata lives in `~/Library/Application Support/notproton/launchers/365360/.bbnp-fix.json`.

The patch forces a core OpenGL profile and removes `RTLD_NOLOAD` from the facade lookup. MantasMikal's facade bridges the legacy OpenGL behavior the game expects. The optional Objective-C add-on requests an opaque, movable native title bar for titled `WineWindow` windows whose names start with `Battle Brothers`; fullscreen windows are excluded. No game binaries, save files, Steam settings, base NotProton runners, or `/Applications/CrossOver…` files are changed.

The installer checks the complete original driver hash and each patch location, verifies signatures, refuses installation while the game is running, serializes its own installers, and rolls back file replacements if installation fails. Existing patched drivers must match this fix apart from signature layout; unrelated modifications are rejected.

## Troubleshooting

- **Unsupported checksum:** this exact CrossOver build is required. Do not edit the checksum to force a different driver through. A new build needs its code inspected and patch locations verified.
- **The game stopped starting after a NotProton update:** NotProton can regenerate the per-game runner and remove the fix. Select the supported Rosetta tool and rerun `--check --titlebar`, then install again if it passes.
- **Interface scaling looks wrong:** try `NOTPROTON_RETINA=0 %command%` in Steam's Launch Options, preserving any other options you need. The upstream author recommends disabling Wine Retina mode for scaling problems; it is not required to apply this patch.
- **Transparent title bar remains:** install with `--titlebar`, then quit and relaunch. The Wine log should contain `[bb-titlebar] window decoration workaround loaded` and `[bb-titlebar] applied opaque native title bar to Battle Brothers`.
- **Diagnostic log:** `~/Library/Application Support/notproton/launchers/365360/notproton-wine.log`.

A preliminary experiment with Wine's `AllowImmovableWindows` and `CursorClippingLocksWindows` registry settings did not fix the transparent title bar. This installer does not apply those settings. On the original test machine they were still disabled when the title-bar add-on was confirmed working; that combination has not yet been retested with the registry defaults restored.

## Development

Run the portable safety tests with:

```sh
python3 -m unittest discover -s tests -v
```

On macOS, `--check --titlebar` also compiles and verifies the real facade and patched driver without installing them. A private, temporary copy of the reviewed driver was used to verify install, reinstall, and restore; proprietary driver binaries are not distributed here.

Contributions for another runner should include its original driver hash, the reason for each instruction change, and actual launch results. This project was developed with AI assistance and is an independent community workaround, not an official NotProton, CodeWeavers, Apple, or game update.

## Credits and license

- [MantasMikal's original Battle Brothers OpenGL facade and CrossOver fix](https://gist.github.com/MantasMikal/6845c01c8f1365791879991204eacdc7).
- [NotProton](https://github.com/NotProtonNot/NotProton), which makes the macOS Steam integration possible.
- [Wine's macOS window implementation](https://github.com/wine-mirror/wine/blob/master/dlls/winemac.drv/cocoa_window.m), consulted when diagnosing the title bar.

This repository's original installer, title-bar add-on, tests, and documentation are MIT licensed. The separately fetched upstream gist retains its author's rights; no license for it is inferred or granted by this repository. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
