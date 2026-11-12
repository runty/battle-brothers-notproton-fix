#!/usr/bin/env python3
"""Battle Brothers OpenGL and title-bar fixes for NotProton on macOS.

Requires the reviewed CrossOver 27.0.0.41303 Rosetta runner.
Original OpenGL facade: MantasMikal's gist (see NOTICE.md).
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import struct
import subprocess
import sys
import tempfile
import urllib.request

BUILD = '27.0.0.41303-fex'
PRISTINE_SHA = '0c76b4f4f0a6b33dfacd1ee5bfba41dfe2e894b68901ff933f3310e3aa3eb2eb'
UPSTREAM_REVISION = '1d3225fbb40c11b2b616b5a6ce7e5f5780a0c5d3'
UPSTREAM_URL = ('https://gist.githubusercontent.com/MantasMikal/'
                '6845c01c8f1365791879991204eacdc7/raw/' + UPSTREAM_REVISION +
                '/patch-battle-brothers-macos.sh')
UPSTREAM_SHA = '39d5bf11454606c66464db20e8867b8462375b30766afc1f2447df451b02ecca'
OPENGL_PATH = b'/System/Library/Frameworks/OpenGL.framework/OpenGL'
LEGACY_LIB = Path('/Users/Shared/bb_np_gl.dylib')
ROOT = Path.home() / 'Library/Application Support/notproton'
DRIVER_REL = Path('lib/wine/x86_64-unix/winemac.so')


class FixError(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise FixError(message)


def run(*args):
    subprocess.run(args, check=True)


def require_digest(data, expected, label):
    actual = sha(data)
    require(actual == expected, f'{label}: unsupported checksum {actual}; expected {expected}.')


def patch(original, library, expected_sha=PRISTINE_SHA):
    """Only patch a complete, checksum-matched 41303 x86_64 Mach-O."""
    require_digest(original, expected_sha, 'Original winemac.so')
    result = bytearray(original)
    # macdrv_context_create: OR CORE_PROFILE_BIT into attrs.profile before
    # each branch which emits CGLPFAOpenGLProfile. Instruction lengths match.
    edits = [(0x3419a, '41f6461001', '41804e1001'),
             (0x342b9, '41f6461001', '41804e1001'),
             # macdrv OpenGL init: dlopen flags 0x15 -> 0x05 (remove NOLOAD).
             (0x311be, 'be15000000e8', 'be05000000e8')]
    for offset, before, after in edits:
        before, after = bytes.fromhex(before), bytes.fromhex(after)
        require(result[offset:offset + len(before)] == before,
                f'Unexpected instructions at file offset {offset:#x}; refusing patch.')
        result[offset:offset + len(before)] = after
    destination = os.fsencode(library)
    require(len(destination) <= len(OPENGL_PATH), 'Facade path exceeds the OpenGL string slot.')
    require(result.count(OPENGL_PATH) == 1, 'Expected exactly one OpenGL dlopen path.')
    offset = result.index(OPENGL_PATH)
    result[offset:offset + len(OPENGL_PATH)] = destination.ljust(len(OPENGL_PATH), b'\0')
    return bytes(result)


def owned_regular(path):
    """Refuse symlinks, special files and paths owned by another account."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(),
            f'Refusing to replace non-regular or unowned file: {path}')
    return True


def atomic_write(path, data, mode=0o755):
    owned_regular(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.bbnp-', delete=False) as file:
        stage = Path(file.name)
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            os.fchmod(file.fileno(), mode)
            file.close()
            os.replace(stage, path)
        finally:
            stage.unlink(missing_ok=True)


def transact(changes):
    """Roll back earlier replacements if any later file write fails."""
    previous = []
    try:
        for path, data, mode in changes:
            exists = owned_regular(path)
            old = path.read_bytes() if exists else None
            old_mode = stat.S_IMODE(path.stat().st_mode) if exists else mode
            previous.append((path, old, old_mode))
            atomic_write(path, data, mode)
    except Exception:
        for path, old, mode in reversed(previous):
            if old is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, old, mode)
        raise


@contextmanager
def lock_game(folder):
    path = folder / '.bbnp-install.lock'
    # O_NOFOLLOW prevents following a pre-existing symlink at this lock path.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise FixError('Another copy of this installer is running.') from error
        yield


def require_game_closed():
    result = subprocess.run(['/usr/bin/pgrep', '-if', '[B]attleBrothers[.]exe'],
                            stdout=subprocess.DEVNULL)
    require(result.returncode == 1, 'Quit Battle Brothers completely before installing or restoring.')


def facade_source(cache):
    path = cache / 'upstream-patch.sh'
    if owned_regular(path):
        content = path.read_bytes()
    else:
        print('Downloading the pinned OpenGL facade from MantasMikal\'s gist...')
        with urllib.request.urlopen(UPSTREAM_URL, timeout=30) as response:
            content = response.read(2_000_000)
        require_digest(content, UPSTREAM_SHA, 'Downloaded upstream source')
        cache.mkdir(parents=True, exist_ok=True)
        atomic_write(path, content, 0o600)
    require_digest(content, UPSTREAM_SHA, 'Cached upstream source')
    start, end = b"<<'RGTC_GL_SOURCE_EOF'\n", b'\nRGTC_GL_SOURCE_EOF'
    require(content.count(start) == 1 and content.count(end) == 1, 'Unexpected upstream source structure.')
    return content.split(start, 1)[1].split(end, 1)[0]


def unsigned(data, directory, name):
    path = directory / name
    path.write_bytes(data)
    subprocess.run(['/usr/bin/codesign', '--remove-signature', str(path)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = bytearray(path.read_bytes())
    require(result[:4] == bytes.fromhex('cffaedfe'), 'Expected a thin 64-bit little-endian Mach-O.')
    offset = 32
    for _ in range(struct.unpack_from('<I', result, 16)[0]):
        command, size = struct.unpack_from('<II', result, offset)
        require(size >= 8 and offset + size <= len(result), 'Invalid Mach-O load command.')
        if command == 0x19 and result[offset+8:offset+24].rstrip(b'\0') == b'__LINKEDIT':
            # codesign can resize this allocation even after the signature is
            # removed. All executable bytes and other load fields must match.
            struct.pack_into('<Q', result, offset + 32, 0)
        offset += size
    return bytes(result)


def original_for(current, backup, library, directory):
    if sha(current) == PRISTINE_SHA:
        return current
    require(owned_regular(backup), 'Patched driver has no original backup; refusing to overwrite it.')
    original = backup.read_bytes()
    require_digest(original, PRISTINE_SHA, 'Backup winemac.so')
    current_unsigned = unsigned(current, directory, 'current.so')
    # Accept our earlier local prototype as well as this public installer.
    for index, path in enumerate((library, LEGACY_LIB)):
        expected = unsigned(patch(original, path), directory, f'expected-{index}.so')
        if current_unsigned == expected:
            return original
    raise FixError('Driver contains unrecognized changes; refusing to overwrite them.')


def compile_facade(source, directory, library, titlebar):
    path = directory / 'facade.c'
    path.write_bytes(source)
    output = directory / 'facade.dylib'
    extra = ['-framework', 'Cocoa', str(Path(__file__).with_name('titlebar-fix.m'))] if titlebar else []
    run('/usr/bin/clang', '-O2', '-Wall', '-Wno-deprecated-declarations',
        '-arch', 'x86_64', '-arch', 'arm64', '-dynamiclib',
        '-install_name', str(library), '-Wl,-reexport_framework,OpenGL',
        '-o', str(output), str(path), *extra)
    run('/usr/bin/codesign', '--force', '--sign', '-', str(output))
    run('/usr/bin/codesign', '--verify', '--strict', str(output))
    return output.read_bytes()


def signed_driver(data, directory):
    path = directory / 'winemac.so'
    path.write_bytes(data)
    run('/usr/bin/codesign', '--remove-signature', str(path))
    run('/usr/bin/codesign', '--force', '--sign', '-', str(path))
    run('/usr/bin/codesign', '--verify', '--strict', str(path))
    return path.read_bytes()


def library_path():
    return Path(f'/Users/Shared/bbnp-{os.getuid()}.dylib')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='compile and validate; leave installed files unchanged')
    group.add_argument('--install', action='store_true', help='back up and patch the private Battle Brothers runner')
    group.add_argument('--restore', action='store_true', help='restore the original driver')
    parser.add_argument('--titlebar', action='store_true', help='also fix the transparent, undraggable title bar')
    args = parser.parse_args()
    require(sys.platform == 'darwin', 'This installer requires macOS.')
    require(not (args.titlebar and args.restore), 'Use --install without --titlebar to remove only the title-bar fix.')
    folder = ROOT / 'launchers/365360'
    driver = folder / 'runner' / DRIVER_REL
    backup = driver.with_name('winemac.so.bbnp-backup')
    metadata = folder / '.bbnp-fix.json'
    library = library_path()
    require(owned_regular(driver), 'Runner missing. Launch Battle Brothers once with the 41303 Rosetta tool, then quit.')
    with lock_game(folder), tempfile.TemporaryDirectory(prefix='bb-notproton-') as tmp:
        tmp = Path(tmp)
        if not args.check:
            require_game_closed()
        current = driver.read_bytes()
        original = original_for(current, backup, library, tmp)
        if args.restore:
            require(owned_regular(backup), 'No original backup found; nothing restored.')
            require_digest(backup.read_bytes(), PRISTINE_SHA, 'Backup winemac.so')
            require(driver.read_bytes() == current, 'Driver changed during validation; retry after closing the game.')
            atomic_write(driver, original)
            # Only remove a facade this installer recorded and whose contents still match.
            if owned_regular(metadata):
                saved = json.loads(metadata.read_text())
                if saved.get('library') == str(library) and owned_regular(library):
                    if sha(library.read_bytes()) == saved.get('library_sha256'):
                        library.unlink()
                    else:
                        print('Facade has changed; left it in place.')
                metadata.unlink()
            print('Restored the original Battle Brothers driver. The backup was kept.')
            return
        base = ROOT / 'runners' / f'crossover-{BUILD}' / 'CrossOver' / DRIVER_REL
        require(owned_regular(base), f'Required base runner is missing: crossover-{BUILD}')
        require_digest(base.read_bytes(), PRISTINE_SHA, 'Base winemac.so')
        source = facade_source(Path.home() / 'Library/Caches/battle-brothers-notproton-fix')
        facade = compile_facade(source, tmp, library, args.titlebar)
        prepared = signed_driver(patch(original, library), tmp)
        print('PASS: supported driver, source checksum, compilation and signatures.')
        if args.check:
            print('Check only: installed driver and facade unchanged. Upstream source may be cached.')
            return
        require_game_closed()
        require(driver.read_bytes() == current, 'Driver changed during the build; no patch installed.')
        if owned_regular(backup):
            require_digest(backup.read_bytes(), PRISTINE_SHA, 'Existing backup')
        else:
            # Exclusive creation: never overwrite the only pristine backup.
            with backup.open('xb') as file:
                file.write(original)
        # A pre-existing per-user facade must belong to an installation we recognize.
        if owned_regular(library):
            require(owned_regular(metadata), f'Untracked facade already exists: {library}')
            saved = json.loads(metadata.read_text())
            require(saved.get('library') == str(library) and
                    saved.get('library_sha256') == sha(library.read_bytes()),
                    'Existing facade differs from the recorded installation; refusing overwrite.')
        state = json.dumps({'build': BUILD, 'library': str(library),
                            'library_sha256': sha(facade), 'driver_sha256': sha(prepared),
                            'titlebar': args.titlebar, 'upstream_revision': UPSTREAM_REVISION}, indent=2).encode() + b'\n'
        transact([(library, facade, 0o755), (driver, prepared, 0o755), (metadata, state, 0o600)])
        print('Installed for Battle Brothers only. Select CrossOver 2026 11 11-ARM64 - Rosetta in Steam.')
        if args.titlebar:
            print('Included the opaque, movable native title bar workaround.')
        print('Launch normally from Steam.')
        print('Undo: python3', shlex.quote(str(Path(__file__).resolve())), '--restore')


if __name__ == '__main__':
    try:
        main()
    except (FixError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        sys.exit(1)
