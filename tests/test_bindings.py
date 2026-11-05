from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from zipfile import ZipFile
import unittest

import boko

from fixtures import make_epub, make_mobi


class BindingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.epub = make_epub()
        cls.books = {'epub': cls.epub, 'mobi': make_mobi()}
        for format in ('azw3', 'kfx'):
            cls.books[format] = boko.convert(cls.epub, 'epub', format)

    def test_public_api(self):
        self.assertTrue(callable(boko.convert))
        self.assertTrue(callable(boko.convert_file))
        self.assertFalse(hasattr(boko, 'book_info'))

    def test_every_input_format(self):
        for format, data in self.books.items():
            with self.subTest(format=format), boko.Book.from_bytes(data, format) as book:
                info = book.metadata
                self.assertGreater(len(book.spine), 0)
                if format == 'mobi':
                    self.assertEqual(info['title'], 'Synthetic MOBI')
                else:
                    self.assertEqual(info['title'], 'A book & كتاب')
                    self.assertEqual(info['authors'], ['Test Author'])
                markdown = boko.convert(data, format, 'markdown')
                self.assertIsInstance(markdown, bytes)
                self.assertIn('Hello from', markdown.decode())

    def test_conversion_roundtrip_for_every_output_format(self):
        for format in ('epub', 'azw3', 'kfx'):
            with self.subTest(format=format):
                converted = boko.convert(self.epub, 'epub', format)
                self.assertIsInstance(converted, bytes)
                epub = boko.convert(converted, format, 'epub')
                with boko.Book.from_bytes(epub, 'epub') as book:
                    self.assertEqual(book.metadata['title'], 'A book & كتاب')
                self.assertIn('مرحبا بالعالم', boko.convert(epub, 'epub', 'md').decode())
                with ZipFile(BytesIO(epub)) as archive:
                    self.assertEqual(archive.read('mimetype'), b'application/epub+zip')

    def test_format_aliases(self):
        markdown = boko.convert(self.epub, from_format='EPUB', to_format='markdown')
        self.assertEqual(markdown, boko.convert(self.epub, 'epub', 'md'))
        with boko.Book.from_bytes(self.books['mobi'], 'azw') as azw, boko.Book.from_bytes(self.books['mobi'], 'mobi') as mobi:
            self.assertEqual(azw.metadata, mobi.metadata)

    def test_invalid_formats_are_value_errors(self):
        for from_format, to_format in (('pdf', 'epub'), ('epub', 'pdf'), ('md', 'epub'), ('epub', 'mobi')):
            with self.subTest(from_format=from_format, to_format=to_format), self.assertRaises(ValueError):
                boko.convert(b'', from_format, to_format)

    def test_malformed_input_is_a_value_error(self):
        for format in ('epub', 'azw3', 'mobi', 'kfx'):
            for data in (b'', b'not an ebook', bytes(100)):
                with self.subTest(format=format, data=data):
                    with self.assertRaises(ValueError):
                        boko.Book.from_bytes(data, format)
                    with self.assertRaises(ValueError):
                        boko.convert(data, format, 'epub')

    def test_drm_is_a_permission_error(self):
        with self.assertRaises(PermissionError):
            boko.convert(make_mobi(encrypted=True), 'mobi', 'epub')

    def test_input_must_be_bytes(self):
        with self.assertRaises(TypeError):
            boko.convert('not bytes', 'epub', 'kfx')

    def test_concurrent_conversion(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: boko.convert(self.epub, 'epub', 'md'), range(4)))
        self.assertTrue(results[0])
        self.assertTrue(all(result == results[0] for result in results))


if __name__ == '__main__':
    unittest.main()
