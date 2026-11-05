from io import BytesIO
from struct import pack
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile
import zlib


def make_epub():
    files = {
        'META-INF/container.xml': '''<?xml version="1.0"?>
            <container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                <rootfiles><rootfile full-path="book.opf" media-type="application/oebps-package+xml"/></rootfiles>
            </container>''',
        'book.opf': '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
            <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:identifier id="id">urn:boko-python:test</dc:identifier>
                <dc:title>A book &amp; كتاب</dc:title><dc:creator>Test Author</dc:creator><dc:language>en</dc:language>
                <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
            </metadata>
            <manifest>
                <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
                <item id="first" href="first.xhtml" media-type="application/xhtml+xml"/>
                <item id="second" href="second.xhtml" media-type="application/xhtml+xml"/>
            </manifest>
            <spine><itemref idref="first"/><itemref idref="second"/></spine>
        </package>''',
        'nav.xhtml': '''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
            <head><title>Contents</title></head><body><nav epub:type="toc"><ol>
                <li><a href="first.xhtml">First</a><ol><li><a href="first.xhtml#detail">Details</a></li></ol></li>
                <li><a href="second.xhtml">Second</a></li>
            </ol></nav></body></html>''',
        'first.xhtml': '''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>First</title></head><body>
            <h1>First chapter</h1><p>Hello from Boko. مرحبا بالعالم.</p>
            <h2 id="detail">Details</h2><p>More text.</p></body></html>''',
        'second.xhtml': '''<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Second</title></head><body>
            <h1>Second chapter</h1><p>The end.</p></body></html>''',
    }
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('mimetype', 'application/epub+zip', compress_type=ZIP_STORED)
        for name, text in files.items():
            archive.writestr(name, text.encode())
    return output.getvalue()


def make_png():
    def chunk(kind, data):
        return pack('>I', len(data)) + kind + data + pack('>I', zlib.crc32(kind + data))

    rows = b''.join(b'\0' + bytes(value for x in range(128) for value in (x, y, (x + y) % 256)) for y in range(128))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', pack('>IIBBBBB', 128, 128, 8, 2, 0, 0, 0)) + chunk(
        b'IDAT', zlib.compress(rows, level=0)
    ) + chunk(b'IEND', b'')


def make_rich_epub():
    with ZipFile(BytesIO(make_epub())) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    opf = files['book.opf'].decode().replace('<dc:title>', '<dc:title id="title">').replace(
        '<dc:creator>', '<dc:creator id="author">'
    ).replace('<dc:language>en</dc:language>', '<dc:language>ar</dc:language>')
    opf = opf.replace('</metadata>', '''
        <dc:publisher>Test Publisher</dc:publisher><dc:description>A description</dc:description>
        <dc:subject>Testing</dc:subject><dc:date>2026-01-01</dc:date><dc:rights>Public domain</dc:rights>
        <dc:contributor id="translator">Translator</dc:contributor>
        <meta refines="#translator" property="role" scheme="marc:relators">trl</meta>
        <meta refines="#translator" property="file-as">Translator, Test</meta>
        <meta refines="#title" property="file-as">Book, A</meta>
        <meta refines="#author" property="file-as">Author, Test</meta>
        <meta property="belongs-to-collection" id="series">Test Series</meta>
        <meta refines="#series" property="collection-type">series</meta>
        <meta refines="#series" property="group-position">2.5</meta>
        </metadata>''').replace('</manifest>', '''
        <item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>
        <item id="css" href="style.css" media-type="text/css"/>
        <item id="font" href="fonts/test.otf" media-type="font/otf"/>
        </manifest>''').replace('<spine>', '<spine page-progression-direction="rtl">')
    files['book.opf'] = opf.encode()
    first = files['first.xhtml'].decode().replace('<html ', '<html xmlns:epub="http://www.idpf.org/2007/ops" ').replace(
        '</head>', '<link rel="stylesheet" href="style.css"/></head>'
    ).replace('</body>', '''
        <p class="red"><a href="second.xhtml#end">Internal target</a>
            <a href="second.xhtml">Chapter target</a>
            <a href="https://example.com">External target</a>
            <a href="missing.xhtml#lost">Broken target</a>
            <a epub:type="noteref" href="#note">Footnote reference</a></p>
        <aside epub:type="footnote" id="note"><p>Unique footnote body.</p></aside>
        <blockquote><p>A quotation.</p></blockquote>
        <ul><li>First item</li><li>Second item</li></ul>
        <dl><dt>Term</dt><dd>Meaning</dd><dt>Second term</dt><dd>Description</dd></dl>
        <table><thead><tr><th>Header</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody></table>
        <pre><code class="language-python">  print('hello')\n  print('world')</code></pre>
        <img src="cover.png" alt="Test cover"/><hr/>
        </body>''')
    files['first.xhtml'] = first.encode()
    files['second.xhtml'] = files['second.xhtml'].replace(b'<h1>', b'<h1 id="end">')
    files['nav.xhtml'] = files['nav.xhtml'].replace(b'</body>', b'''<nav epub:type="landmarks"><ol>
        <li><a epub:type="bodymatter" href="first.xhtml">Start</a></li>
        <li><a epub:type="cover" href="cover.png">Cover</a></li>
        </ol></nav></body>''')
    files['cover.png'] = make_png()
    files['style.css'] = b'@font-face { font-family: TestFont; src: url("fonts/test.otf"); font-weight: 700; font-style: italic; } .red { color: red; } pre, code { white-space: pre; }'
    files['fonts/test.otf'] = b'opaque test font asset'
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data, compress_type=ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED)
    return output.getvalue()


def make_mobi(*, encrypted=False):
    # A minimal uncompressed PalmDoc: PDB header, two record offsets, record 0, HTML.
    text = b'<html><body><h1>Synthetic MOBI</h1><p>Hello from MOBI.</p></body></html>'
    header = bytearray(78)
    header[:14] = b'Synthetic MOBI'
    header[60:68] = b'TEXtREAd'
    header[76:78] = pack('>H', 2)
    records = pack('>IIII', 96, 0, 112, 1) + b'\0\0'
    record_zero = pack('>HHIHHHH', 1, 0, len(text), 1, 4096, int(encrypted), 0)
    return bytes(header) + records + record_zero + text
