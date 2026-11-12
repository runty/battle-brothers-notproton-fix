import tempfile
from pathlib import Path
import subprocess
import unittest
from unittest import mock

import fix


class PatchTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(0x49000)
        for offset, value in [(0x3419a, '41f6461001'), (0x342b9, '41f6461001'),
                              (0x311be, 'be15000000e8')]:
            value = bytes.fromhex(value)
            data[offset:offset+len(value)] = value
        data[0x47e7d:0x47e7d+len(fix.OPENGL_PATH)] = fix.OPENGL_PATH
        self.original = bytes(data)

    def test_unknown_binary_is_rejected(self):
        with self.assertRaises(fix.FixError):
            fix.patch(self.original, Path('/tmp/test.dylib'))

    def test_exact_edits_and_size_preservation(self):
        result = fix.patch(self.original, Path('/tmp/test.dylib'), fix.sha(self.original))
        self.assertEqual(len(result), len(self.original))
        self.assertEqual(result[0x3419a:0x3419f], bytes.fromhex('41804e1001'))
        self.assertEqual(result[0x342b9:0x342be], bytes.fromhex('41804e1001'))
        self.assertEqual(result[0x311be:0x311c4], bytes.fromhex('be05000000e8'))
        expected_changes = {0x3419b, 0x3419c, 0x342ba, 0x342bb, 0x311bf}
        actual_changes = {i for i, (a, b) in enumerate(zip(self.original, result)) if a != b}
        self.assertEqual(actual_changes - set(range(0x47e7d, 0x47e7d+len(fix.OPENGL_PATH))), expected_changes)

    def test_oversized_path_rejected(self):
        with self.assertRaises(fix.FixError):
            fix.patch(self.original, Path('/'+('a'*100)), fix.sha(self.original))

    def test_changed_instructions_rejected_even_with_matching_digest(self):
        data = bytearray(self.original)
        data[0x3419a] = 0
        with self.assertRaises(fix.FixError):
            fix.patch(bytes(data), Path('/tmp/test.dylib'), fix.sha(data))


class FileSafetyTests(unittest.TestCase):
    def test_transaction_rolls_back_existing_and_new_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            old, new, last = folder/'old', folder/'new', folder/'last'
            old.write_bytes(b'original')
            actual = fix.atomic_write
            def fail_last(path, data, mode):
                if path == last:
                    raise OSError('simulated failed commit')
                actual(path, data, mode)
            with mock.patch.object(fix, 'atomic_write', side_effect=fail_last):
                with self.assertRaises(OSError):
                    fix.transact([(old, b'changed', 0o600), (new, b'new', 0o600), (last, b'last', 0o600)])
            self.assertEqual(old.read_bytes(), b'original')
            self.assertFalse(new.exists())
            self.assertFalse(last.exists())

    def test_symlink_destination_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            target, link = Path(folder)/'target', Path(folder)/'link'
            target.write_bytes(b'original')
            link.symlink_to(target)
            with self.assertRaises(fix.FixError):
                fix.atomic_write(link, b'changed')
            self.assertEqual(target.read_bytes(), b'original')

    def test_corrupt_cached_source_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'upstream-patch.sh').write_bytes(b'not the pinned source')
            with mock.patch.object(fix.urllib.request, 'urlopen') as network:
                with self.assertRaises(fix.FixError):
                    fix.facade_source(Path(folder))
                network.assert_not_called()

    def test_running_game_or_failed_process_check_blocks_mutation(self):
        for status in (0, 2):
            with self.subTest(status=status), mock.patch.object(fix.subprocess, 'run', return_value=subprocess.CompletedProcess([], status)):
                with self.assertRaises(fix.FixError):
                    fix.require_game_closed()
        with mock.patch.object(fix.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            fix.require_game_closed()


if __name__ == '__main__':
    unittest.main()
