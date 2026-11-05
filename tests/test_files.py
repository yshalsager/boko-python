from concurrent.futures import ThreadPoolExecutor
from contextlib import chdir
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile
import os
import unittest

import boko

from fixtures import make_epub, make_mobi


class FileConversionTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'كتاب.epub'
        self.data = make_epub()
        self.source.write_bytes(self.data)

    def test_output_formats_and_atomic_replacement(self):
        for format in ('epub', 'azw3', 'kfx', 'md', 'markdown'):
            with self.subTest(format=format):
                output = self.root / f'output.{format.upper()}'
                output.write_bytes(b'previous output')
                self.assertIsNone(boko.convert_file(self.source, output))
                if os.name == 'posix':
                    self.assertEqual(output.stat().st_mode & 0o077, 0)
                if format in ('md', 'markdown'):
                    self.assertEqual(output.read_bytes(), boko.convert(self.data, 'epub', 'md'))
                else:
                    with boko.Book.open(output) as book:
                        self.assertEqual(book.metadata['title'], 'A book & كتاب')
                        self.assertIn('مرحبا بالعالم', book.chapter(0).text)
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(len(list(self.root.iterdir())), 6)

    def test_input_formats_and_string_paths(self):
        books = {'epub': self.data, 'mobi': make_mobi(), 'azw': make_mobi()}
        for format in ('azw3', 'kfx'):
            books[format] = boko.convert(self.data, 'epub', format)
        for format, data in books.items():
            with self.subTest(format=format):
                source = self.root / f'input.{format}'
                source.write_bytes(data)
                output = self.root / f'{format}.md'
                boko.convert_file(str(source), str(output))
                self.assertIn('Hello from', output.read_text(encoding='utf-8'))

    def test_relative_paths(self):
        with chdir(self.root):
            boko.convert_file(self.source.name, 'output.md')
        self.assertIn('مرحبا بالعالم', (self.root / 'output.md').read_text(encoding='utf-8'))

    def test_same_path_and_hardlink_are_rejected(self):
        alias = self.root / 'alias.epub'
        alias.hardlink_to(self.source)
        for output in (self.source, alias):
            with self.subTest(output=output), self.assertRaises(ValueError):
                boko.convert_file(self.source, output)
            self.assertEqual(output.read_bytes(), self.data)
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_symlink_to_input_is_rejected(self):
        alias = self.root / 'alias.epub'
        try:
            alias.symlink_to(self.source)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows symlink creation requires additional privileges')
            raise
        with self.assertRaises(ValueError):
            boko.convert_file(self.source, alias)
        self.assertTrue(alias.is_symlink())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_invalid_output_formats_preserve_destination(self):
        for name in ('output.mobi', 'output.pdf', 'without_extension'):
            with self.subTest(name=name):
                output = self.root / name
                output.write_bytes(b'previous output')
                with self.assertRaises(ValueError):
                    boko.convert_file(self.source, output)
                self.assertEqual(output.read_bytes(), b'previous output')

    def test_input_errors_preserve_destination(self):
        malformed = self.root / 'malformed.epub'
        malformed.write_bytes(b'not an ebook')
        encrypted = self.root / 'encrypted.mobi'
        encrypted.write_bytes(make_mobi(encrypted=True))
        unsupported = self.root / 'input.pdf'
        unsupported.write_bytes(self.data)
        output = self.root / 'output.kfx'
        for source, error in (
            (malformed, ValueError), (encrypted, PermissionError),
            (unsupported, ValueError), (self.root / 'missing.epub', FileNotFoundError),
        ):
            with self.subTest(source=source):
                output.write_bytes(b'previous output')
                with self.assertRaises(error):
                    boko.convert_file(source, output)
                self.assertEqual(output.read_bytes(), b'previous output')
        with self.assertRaises(TypeError):
            boko.convert_file(123, output)

    def test_partial_export_failure_preserves_destination_and_cleans_up(self):
        broken = BytesIO()
        with ZipFile(BytesIO(self.data)) as source, ZipFile(broken, 'w') as destination:
            for item in source.infolist():
                if item.filename != 'second.xhtml':
                    destination.writestr(item, source.read(item.filename))
        self.source.write_bytes(broken.getvalue())
        output = self.root / 'output.epub'
        for previous in (None, b'previous output'):
            with self.subTest(previous=previous):
                if previous is not None:
                    output.write_bytes(previous)
                with self.assertRaises(KeyError):
                    boko.convert_file(self.source, output)
                if previous is None:
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(output.read_bytes(), previous)
                self.assertEqual(set(self.root.iterdir()), {self.source} | ({output} if previous is not None else set()))

    def test_filesystem_errors_clean_up(self):
        with self.assertRaises(FileNotFoundError):
            boko.convert_file(self.source, self.root / 'missing' / 'output.kfx')
        output = self.root / 'directory.kfx'
        output.mkdir()
        marker = output / 'keep'
        marker.write_bytes(b'keep')
        with self.assertRaises(OSError):
            boko.convert_file(self.source, output)
        self.assertEqual(marker.read_bytes(), b'keep')
        self.assertEqual(set(self.root.iterdir()), {self.source, output})
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_concurrent_file_conversion(self):
        outputs = [self.root / f'output-{index}.md' for index in range(6)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda output: boko.convert_file(self.source, output), outputs))
        self.assertEqual(results, [None] * len(outputs))
        expected = boko.convert(self.data, 'epub', 'md')
        self.assertTrue(all(output.read_bytes() == expected for output in outputs))
        self.assertEqual(set(self.root.iterdir()), {self.source, *outputs})


if __name__ == '__main__':
    unittest.main()
