from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree
from zipfile import ZipFile
import unittest

import boko

from fixtures import make_epub, make_mobi, make_png, make_rich_epub


class BookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.basic = make_epub()
        cls.rich = make_rich_epub()

    def test_open_paths_formats_and_close(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'كتاب.epub'
            path.write_bytes(self.basic)
            with boko.Book.open(path) as book:
                self.assertFalse(book.closed)
                self.assertEqual(book.metadata['title'], 'A book & كتاب')
                chapter = book.chapter(book.spine[0]['id'])
                links = book.resolve_links()
            self.assertTrue(book.closed)
            path.unlink()
            self.assertIn('مرحبا بالعالم', chapter.text)
            self.assertIsInstance(links.links, list)
            book.close()
            path = Path(directory) / 'unknown.bin'
            path.write_bytes(self.basic)
            with self.assertRaises(ValueError):
                boko.Book.open(path)
            with boko.Book.open(str(path), format='epub') as book:
                self.assertEqual(len(book.spine), 2)
            with self.assertRaises(FileNotFoundError):
                boko.Book.open(Path(directory) / 'missing.epub')

    def test_constructor_validation_and_drm(self):
        for format in ('pdf', 'md'):
            with self.subTest(format=format), self.assertRaises(ValueError):
                boko.Book.from_bytes(b'', format)
        with self.assertRaises(ValueError):
            boko.Book.from_bytes(b'not a book', 'epub')
        with self.assertRaises(TypeError):
            boko.Book.from_bytes('not bytes', 'epub')
        with self.assertRaises(PermissionError):
            boko.Book.from_bytes(make_mobi(encrypted=True), 'mobi')

    def test_identified_but_missing_cover_is_an_error(self):
        output = BytesIO()
        with ZipFile(BytesIO(self.rich)) as source, ZipFile(output, 'w') as destination:
            for item in source.infolist():
                if item.filename != 'cover.png':
                    destination.writestr(item, source.read(item.filename))
        with boko.Book.from_bytes(output.getvalue(), 'epub') as book:
            self.assertEqual(book.metadata['cover_image'], 'cover.png')
            with self.assertRaises(KeyError):
                book.cover()

    def test_missing_spine_resource_has_consistent_errors(self):
        output = BytesIO()
        with ZipFile(BytesIO(self.basic)) as source, ZipFile(output, 'w') as destination:
            for item in source.infolist():
                if item.filename != 'second.xhtml':
                    destination.writestr(item, source.read(item.filename))
        with boko.Book.from_bytes(output.getvalue(), 'epub') as book:
            with self.assertRaises(KeyError):
                book.chapter(1)
            with self.assertRaises(KeyError):
                book.sections()

    def test_definition_lists_have_text_boundaries(self):
        with boko.Book.from_bytes(self.rich, 'epub') as book:
            self.assertIn('Term\nMeaning\nSecond term\nDescription\n', book.chapter(0).text)

    def test_text_preserves_empty_table_cells(self):
        rows = '<tr><td></td><td>B</td><td>C</td></tr><tr><td>A</td><td></td><td>C</td></tr>'
        rows += '<tr><td>A</td><td>B</td><td></td></tr><tr><td></td><td></td><td></td></tr>'
        output = BytesIO()
        with ZipFile(BytesIO(self.basic)) as source, ZipFile(output, 'w') as destination:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == 'first.xhtml':
                    data = data.replace(b'</body>', f'<table>{rows}</table></body>'.encode())
                destination.writestr(item, data)
        with boko.Book.from_bytes(output.getvalue(), 'epub') as book:
            chapter = book.chapter(0)
            self.assertTrue(chapter.text.endswith('\tB\tC\t\nA\t\tC\t\nA\tB\t\t\n\t\t\t\n'), repr(chapter.text))
            self.assertEqual(chapter.node_text(0), chapter.text)

    def test_context_manager_propagates_exceptions(self):
        book = boko.Book.from_bytes(self.basic, 'epub')
        with self.assertRaisesRegex(RuntimeError, 'sentinel'):
            with book:
                raise RuntimeError('sentinel')
        self.assertTrue(book.closed)

    def test_closed_book_rejects_operations(self):
        book = boko.Book.from_bytes(self.basic, 'epub')
        book.close()
        operations = [
            lambda: book.metadata, lambda: book.toc, lambda: book.landmarks, lambda: book.spine,
            lambda: book.assets, lambda: book.font_faces, lambda: book.requires_normalized_export,
            lambda: book.cover(), lambda: book.load_asset('cover.png'), lambda: book.chapter(0),
            lambda: book.chapters(), lambda: book.sections(), lambda: book.resolve_links(),
            lambda: book.clear_cache(), lambda: book.optimize(), lambda: book.export('epub'),
            lambda: book.__enter__(),
        ]
        for operation in operations:
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, 'closed'):
                operation()

    def test_full_metadata_and_navigation(self):
        with boko.Book.from_bytes(self.rich, 'epub') as book:
            meta = book.metadata
            self.assertEqual(meta, {
                'title': 'A book & كتاب', 'authors': ['Test Author'], 'language': 'ar',
                'identifier': 'urn:boko-python:test', 'publisher': 'Test Publisher',
                'description': 'A description', 'subjects': ['Testing'], 'date': '2026-01-01',
                'rights': 'Public domain', 'cover_image': 'cover.png', 'modified_date': '2026-01-01T00:00:00Z',
                'contributors': [{'name': 'Translator', 'file_as': 'Translator, Test', 'role': 'trl'}],
                'title_sort': 'Book, A', 'author_sort': 'Author, Test',
                'collection': {'name': 'Test Series', 'collection_type': 'series', 'position': 2.5},
                'page_progression_direction': 'rtl', 'is_rtl': True,
            })
            self.assertEqual(len(book.spine), 2)
            self.assertEqual(book.spine[0]['source_path'], 'first.xhtml')
            self.assertGreater(book.spine[0]['size_estimate'], 0)
            self.assertEqual(book.toc[0]['children'][0]['title'], 'Details')
            self.assertIsNone(book.toc[0]['target'])
            self.assertEqual({entry['type'] for entry in book.landmarks}, {'body_matter', 'cover'})
            meta['authors'].append('not an edit')
            self.assertEqual(book.metadata['authors'], ['Test Author'])
            toc = book.toc
            toc[0]['children'].clear()
            self.assertEqual(len(book.toc[0]['children']), 1)

    def test_missing_optional_metadata(self):
        with boko.Book.from_bytes(self.basic, 'epub') as book:
            meta = book.metadata
            self.assertIsNone(meta['publisher'])
            self.assertIsNone(meta['collection'])
            self.assertEqual(meta['contributors'], [])
            self.assertFalse(meta['is_rtl'])
            self.assertIsNone(book.cover())

    def test_covers_assets_and_fonts(self):
        with boko.Book.from_bytes(self.rich, 'epub') as book:
            self.assertIn('cover.png', book.assets)
            self.assertIn('fonts/test.otf', book.assets)
            self.assertEqual(book.cover(), make_png())
            self.assertEqual(book.load_asset('fonts/test.otf'), b'opaque test font asset')
            self.assertEqual(book.font_faces, [{
                'font_family': 'TestFont', 'font_weight': 700, 'font_style': 'italic', 'src': 'fonts/test.otf',
            }])
            with self.assertRaises(KeyError):
                book.load_asset('missing.png')
            assets = book.assets
            assets.clear()
            self.assertIn('cover.png', book.assets)

    def test_chapters_text_xhtml_and_cache(self):
        book = boko.Book.from_bytes(self.rich, 'epub')
        chapter = book.chapter(0)
        self.assertIsInstance(chapter, boko.Chapter)
        self.assertEqual(chapter.id, 0)
        self.assertEqual(chapter.source_path, 'first.xhtml')
        self.assertIsInstance(chapter.raw, bytes)
        self.assertIn(b'<html', chapter.raw)
        self.assertIn('مرحبا بالعالم', chapter.text)
        self.assertIn('Unique footnote body.', chapter.text)
        self.assertIn("  print('hello')\n  print('world')", chapter.text)
        self.assertIn('Header', chapter.text)
        self.assertIn('Cell', chapter.text)
        root = ElementTree.fromstring(chapter.xhtml)
        self.assertEqual(root.tag, '{http://www.w3.org/1999/xhtml}html')
        self.assertIn('chapter.css', chapter.xhtml)
        css = chapter.css
        self.assertIn('color:', css)
        for node in root.iter():
            for class_name in node.get('class', '').split():
                self.assertIn(f'.{class_name} {{', css)
        self.assertEqual(chapter.node_text(0), chapter.text)
        with self.assertRaises(KeyError):
            chapter.node_text(999999)
        self.assertEqual([item.id for item in book.chapters()], [0, 1])
        chapters = book.chapters([1, 0, 1])
        self.assertEqual([item.id for item in chapters], [1, 0, 1])
        for item in chapters:
            expected = book.chapter(item.id)
            self.assertEqual(item.raw, expected.raw)
            self.assertEqual(item.text, expected.text)
        self.assertEqual(book.chapters([]), [])
        self.assertEqual(book.chapter(0).text, chapter.text)
        book.clear_cache()
        self.assertEqual(book.chapter(0).text, chapter.text)
        with self.assertRaises(KeyError):
            book.chapter(999999)
        with self.assertRaises(KeyError):
            book.chapters([0, 999999])
        book.close()
        self.assertIn('Unique footnote body.', chapter.text)
        self.assertIn('<html', chapter.xhtml)
        with self.assertRaises(AttributeError):
            chapter.id = 123

    def test_sections_are_structured_snapshots(self):
        with boko.Book.from_bytes(self.rich, 'epub') as book:
            tree = book.sections()
            self.assertEqual(tree['title'], 'A book & كتاب')
            self.assertEqual(tree['language'], 'ar')
            self.assertIsInstance(tree['preamble'], list)
            self.assertEqual(tree['sections'][0]['title'], 'First chapter')
            self.assertEqual(tree['sections'][0]['children'][0]['title'], 'Details')
            pending = list(tree['sections'])
            blocks = []
            while pending:
                section = pending.pop()
                blocks.extend(section['content'])
                pending.extend(section['children'])
            self.assertTrue({'paragraph', 'block_quote', 'list', 'table', 'code_block', 'image', 'rule'} <= {
                block['type'] for block in blocks
            })
            code = next(block for block in blocks if block['type'] == 'code_block')
            self.assertIn("  print('hello')", code['code'])
            table = next(block for block in blocks if block['type'] == 'table')
            self.assertEqual(table['headers'], ['Header'])
            self.assertEqual(table['rows'], [['Cell']])
        self.assertEqual(tree['authors'], ['Test Author'])

    def test_resolved_links_and_backlinks(self):
        book = boko.Book.from_bytes(self.rich, 'epub')
        resolved = book.resolve_links()
        self.assertIsInstance(resolved, boko.ResolvedLinks)
        self.assertEqual(len(resolved), len(resolved.links))
        self.assertEqual({item['target']['kind'] for item in resolved.links}, {'internal', 'chapter', 'external'})
        self.assertEqual([item['href'] for item in resolved.broken_links], ['missing.xhtml#lost'])
        self.assertIsNone(resolved.get(12345, 12345))
        self.assertEqual(resolved.links_to(12345), [])
        for link in resolved.links:
            source = link['source']
            target = link['target']
            self.assertEqual(resolved.get(**source), target)
            self.assertTrue(book.chapter(source['chapter_id']).node_text(source['node_id']))
            if target['kind'] == 'internal':
                self.assertIn(source, resolved.links_to(target['chapter_id'], target['node_id']))
                self.assertTrue(book.chapter(target['chapter_id']).node_text(target['node_id']))
            elif target['kind'] == 'chapter':
                self.assertIn(source, resolved.links_to(target['chapter_id']))
            else:
                self.assertEqual(target['url'], 'https://example.com')
        self.assertEqual(book.toc[0]['target']['kind'], 'chapter')
        self.assertEqual(book.toc[0]['children'][0]['target']['kind'], 'internal')
        snapshot = resolved.links
        snapshot.clear()
        self.assertGreater(len(resolved.links), 0)
        book.close()
        self.assertEqual(len(resolved.broken_links), 1)

    def test_book_api_for_all_formats(self):
        books = {'epub': self.basic, 'mobi': make_mobi()}
        for format in ('azw3', 'kfx'):
            books[format] = boko.convert(self.basic, 'epub', format)
        for format, data in books.items():
            with self.subTest(format=format), boko.Book.from_bytes(data, format) as book:
                self.assertGreater(len(book.spine), 0)
                self.assertEqual(book.requires_normalized_export, format == 'kfx')
                self.assertIn('Hello from', book.chapter(book.spine[0]['id']).text)
                self.assertIn('html', book.chapter(book.spine[0]['id']).xhtml)
                self.assertTrue(book.sections()['sections'])
                epub = book.export('epub')
                with boko.Book.from_bytes(epub, 'epub') as imported:
                    self.assertGreater(len(imported.spine), 0)

    def test_export_options(self):
        with boko.Book.from_bytes(self.rich, 'epub') as book:
            for normalize in (False, True):
                for level in (1, 9):
                    output = book.export('epub', normalize=normalize, compression_level=level)
                    with ZipFile(BytesIO(output)) as archive:
                        self.assertEqual(archive.read('mimetype'), b'application/epub+zip')
                    with boko.Book.from_bytes(output, 'epub') as imported:
                        self.assertEqual(imported.metadata['title'], 'A book & كتاب')
                        self.assertTrue(imported.metadata['is_rtl'])
            for format in ('epub', 'azw3'):
                data = book.export(format, normalize=True)
                with boko.Book.from_bytes(data, format) as imported:
                    self.assertEqual(imported.metadata['title'], 'A book & كتاب')
            for format, kwargs in (
                ('epub', {'compression_level': 0}), ('epub', {'compression_level': 10}), ('azw3', {'compression_level': 1}),
                ('kfx', {'normalize': True}), ('md', {'normalize': False}), ('md', {'compression_level': 1}),
            ):
                with self.subTest(format=format, kwargs=kwargs), self.assertRaises(ValueError):
                    book.export(format, **kwargs)
            for format in ('mobi', 'pdf'):
                with self.assertRaises(ValueError):
                    book.export(format)

    def test_optimize_without_images_reports_no_changes(self):
        with boko.Book.from_bytes(self.basic, 'epub') as book:
            report = book.optimize()
            self.assertEqual(report['assets_changed'], 0)
            self.assertEqual(report['bytes_saved'], 0)
            with boko.Book.from_bytes(book.export('epub'), 'epub') as imported:
                self.assertEqual(imported.metadata['title'], 'A book & كتاب')

    def test_optimize_preserves_snapshots_links_and_exports(self):
        with boko.Book.from_bytes(self.rich, 'epub') as book:
            before = book.chapter(0)
            links = book.resolve_links()
            cover = book.cover()
            report = book.optimize()
            self.assertGreater(report['assets_changed'], 0)
            self.assertGreater(report['bytes_saved'], 0)
            self.assertEqual(report['passes'][0]['pass'], 'images')
            self.assertEqual(report['assets_changed'], sum(item['assets_changed'] for item in report['passes']))
            self.assertLess(len(book.cover()), len(cover))
            self.assertTrue(book.cover().startswith(b'\xff\xd8\xff'))
            self.assertEqual(before.text, book.chapter(0).text)
            self.assertIn(b'cover.png', before.raw)
            self.assertIn('cover.jpg', book.chapter(0).xhtml)
            self.assertEqual(book.chapter(0).raw, before.raw)
            self.assertTrue(book.requires_normalized_export)
            self.assertEqual(book.resolve_links().links, links.links)
            self.assertEqual(book.resolve_links().broken_links, links.broken_links)
            self.assertEqual(book.toc[0]['children'][0]['target']['kind'], 'internal')
            with boko.Book.from_bytes(book.export('epub'), 'epub') as imported:
                self.assertEqual(imported.cover(), book.cover())
                self.assertIn('cover.jpg', imported.metadata['cover_image'])
                broken = imported.resolve_links().broken_links
                self.assertEqual(len(broken), 1)
                self.assertTrue(broken[0]['href'].endswith('missing.xhtml#lost'))

    def test_shared_book_read_operations_are_thread_safe(self):
        with boko.Book.from_bytes(self.basic, 'epub') as book:
            with ThreadPoolExecutor(max_workers=3) as executor:
                outputs = list(executor.map(lambda _: book.export('md'), range(6)))
            self.assertTrue(all(output == outputs[0] for output in outputs))


if __name__ == '__main__':
    unittest.main()
