# boko-python

Independent Python bindings for [Boko](https://github.com/zacharydenton/boko),
the native Rust ebook converter. This project depends on the published `boko`
Rust crate; it does not fork or patch the converter and is not maintained
by the upstream Boko project.

The Python distribution is **boko-ebook**, imported as **boko**. The first release
is not published yet; build locally using the instructions below. The unrelated
PyPI distribution `boko` uses the same import name: do not install both together.

> [!CAUTION]
> This project was developed with use of AI assistance.

## Usage

```python
from pathlib import Path
import boko

boko.convert_file(Path('input.epub'), Path('output.kfx'))

# Use bytes when the input is already in memory.
source = Path('input.epub').read_bytes()
output = boko.convert(source, 'epub', 'kfx')
```

```python
convert(data: bytes, from_format: str, to_format: str) -> bytes
convert_file(input_path: str | PathLike[str], output_path: str | PathLike[str]) -> None
```

| Format | Input | Output |
| --- | --- | --- |
| EPUB 2/3 (`epub`) | yes | yes |
| AZW3 (`azw3`) | yes | yes |
| MOBI (`mobi`, `azw`) | yes | no |
| KFX (`kfx`) | yes | yes |
| Markdown (`markdown`, `md`) | no | yes |

Format names are case-insensitive. `convert` returns bytes (UTF-8 for Markdown).

`convert()` buffers input and output in memory. `convert_file()` infers formats from
case-insensitive file extensions and writes directly to a same-filesystem temporary file,
without buffering the entire output in the binding. It replaces an existing destination
only after export and file synchronization succeed. The same input/output file, including
symlink and hardlink aliases, raises `ValueError`. Output extensions are `.epub`, `.azw3`,
`.kfx`, `.md`, and `.markdown`. POSIX outputs use private file permissions (`0600`).

For inspection, repeated reads, or export options, use the `Book` API below. Parsing,
conversion, chapter loading/rendering, link resolution, and optimization release the GIL.
The core uses parallel chapter compilation and image optimization without its CLI dependencies.

- Invalid/unsupported formats and malformed books raise `ValueError`.
- DRM-protected books raise `PermissionError`; no decryption is provided.
- Missing resources raise `KeyError`; genuine I/O failures raise `OSError`.
- Unrecognized future core errors fall back to `RuntimeError`.
- Rust panics during detached native operations raise `RuntimeError`. After a panic,
  close and discard the affected book; continued use is not supported. Allocation aborts
  and OS process kills cannot be caught this way, so untrusted books still need worker limits.

Regular CPython 3.11+ is supported. Wheels use `abi3-py311` and do not require Rust
to install. Free-threaded Python, PyPy, and GraalPy wheels are not currently built.
The wrapper has its own version (initially 0.1.0), independent of the core crate.

## Untrusted books

Parsing is not a sandbox. Input, decompressed chapters, parsed content, image processing,
and exports can consume much more memory than the uploaded file. The core's 512 MiB
limit per decompressed EPUB entry is not a whole-book memory budget; neither compressed
file size nor `spine` size estimates provide that budget.

Process each untrusted book in a disposable worker process or container with an OS-enforced
memory limit and a parent-enforced wall-clock timeout. Limit concurrent workers too.
On Linux, `resource.RLIMIT_AS` bounds virtual address space, including libraries and thread
stacks; choose the budget for your workload. Other platforms need their own process/container
limits. A Rust allocation failure can abort the worker rather than raise a Python exception:
treat nonzero exits and timeouts as failed jobs, not failures of the parent service.

These limits must be configured by the calling application; the library does not impose
a whole-book memory budget.

## Book API

```python
with boko.Book.open(Path('input.epub')) as book:
    print(book.metadata['identifier'], book.metadata['is_rtl'])
    print(book.toc, book.landmarks, book.spine)
    cover = book.cover()
    first = book.chapter(book.spine[0]['id'])
    print(first.text)
    sections = book.sections()
    links = book.resolve_links()
    print(links.broken_links)
    output = book.export('epub', normalize=True, compression_level=6)
```

Use `Book.from_bytes(data, format)` for in-memory inputs. `Book.open(path,
format=None)` accepts strings and `PathLike` objects, inferring formats from the
file extension unless supplied explicitly. Use a `with` statement or `close()` to
release the file and caches. `closed` reports the state; operations on a closed
book raise `ValueError`. Context managers do not suppress exceptions.

### Inspection and assets

- `metadata`: every core metadata field, including contributor roles, collection/
  series, sort names, cover path, reading direction, and inferred `is_rtl`.
- `toc`: nested entries with title, href, play order, children, and optional resolved
  target. Call `resolve_links()` to populate targets.
- `landmarks`: structural navigation entries, using snake-case `type` names.
- `spine`: reading-order entries with `id`, `source_path`, and `size_estimate`.
- `assets`: archive-relative asset names. `load_asset(path)` returns their bytes.
- `cover()`: cover bytes, or `None` when no cover is identified. An identified but
  missing resource raises `KeyError`.
- `font_faces`: family, numeric weight, style, and archive source path.
- `requires_normalized_export`: whether source content needs normalized export.

Dictionaries and lists are independent snapshots: modifying them does not edit
the book. Absent optional metadata uses `None`; absent collections use empty lists.
`boko.pyi` describes these dictionaries; they are not runtime model classes.

### Chapters and sections

`chapter(id)` loads a read-only `Chapter` snapshot. `chapters(ids=None)` loads all
chapters in spine order, or the supplied IDs in that order, using the core's
parallel/cache support. Chapter IDs come from `spine`, not TOC indexes.

| Chapter property/method | Result |
| --- | --- |
| `id`, `source_path` | Chapter identifier and original archive path, if available |
| `raw` | Format-specific bytes; KFX raw content is binary, **not HTML** |
| `text` | Readable live-node text, including footnotes, code whitespace retained by the core, image alt text, and math fallback text |
| `xhtml` | Normalized XHTML, linking its stylesheet as `chapter.css` |
| `css` | The CSS matching the XHTML's generated class names |
| `node_text(node_id)` | Readable text of a normalized node, for link navigation |

XHTML/CSS are normalized renderings, not source-preserving edits. The generated CSS
may include unused styles from the chapter's style pool. They do not copy or embed
image/font assets: retrieve those separately with `load_asset()`.

`sections()` returns `title`, `authors`, `language`, `preamble`, and nested `sections`.
Each section contains `level`, `title`, `content`, and `children`; content blocks
are tagged by `type`: `paragraph`, `code_block`, `block_quote`, `list`, `table`,
`image`, or `rule`. This is a reading/search representation: upstream extraction
omits nodes classified as footnotes by the core and drops inline formatting.
Footnote classification varies by importer, so some EPUB notes may instead appear
as ordinary blocks. Use chapter text/XHTML when footnote content is required.

`clear_cache()` clears parsed core chapters and requires exclusive access to the book.
Existing chapter and link snapshots remain usable after cache clearing, optimization,
or closing their book, and keep their own memory alive until released.

### Links

`resolve_links()` returns a read-only `ResolvedLinks` snapshot:

- `links`: ordered `{source, target}` entries; `len(result)` counts resolved links.
- `broken_links`: ordered `{source, href}` entries.
- `get(chapter_id, node_id)`: the target of a source link, or `None`.
- `links_to(chapter_id, node_id=None)`: source nodes linking to a specific node,
  or to the chapter start when `node_id` is omitted (not all nodes in the chapter).

Sources contain `chapter_id` and `node_id`. Targets are discriminated by `kind`:
`internal` includes both IDs; `chapter` includes `chapter_id`; `external` includes
`url`. IDs refer to normalized nodes, not source-file byte offsets.

### Export and optimization

`export(format, *, normalize=None, compression_level=None)` returns bytes.
`normalize` applies only to EPUB/AZW3; `compression_level` applies only to EPUB
and must be 1–9 (the current ZIP backend rejects level 0). Incompatible options raise `ValueError`. KFX input is normalized
automatically where needed. Markdown wrapping is not exposed because the core's
`line_width` field is reserved and currently ignored.

`optimize()` explicitly mutates the book using Boko's default image pass and
returns `passes`, `assets_changed`, and `bytes_saved`. **This is lossy image
optimization:** the core may downscale and re-encode images as JPEG and rename
assets, including the cover path. JPEG quality (80), dimension limit (1236), and
minimum savings are fixed by the core. Inspect fresh metadata/assets after it runs.
Previously returned snapshots still describe the pre-optimization state.

Read-only operations may run concurrently on one book. `clear_cache()`, `close()`,
`sections()`, and `optimize()` require exclusive access: do not run them concurrently with other
operations on the same book. PyO3 rejects conflicting borrows rather than waiting.
File-like/streaming adapters, CLI scripts, metadata editing, mutable IR, and unstable
KFX tooling are not part of this API.

## Development

Requires CPython 3.11+, Rust 1.91+, and platform native build tools.
Development uses Python 3.11, the oldest supported minor version.
Rust, Python, and uv versions are pinned in `mise.toml`. With
[mise](https://mise.jdx.dev/) activated in your shell:

```sh
mise run dev                                        # uv sync: editable install
uv run python -m unittest discover -s tests -v       # run tests
mise run build                                      # uv build: wheel + source archive
```

uv manages `.venv` and invokes maturin through `pyproject.toml`; no manual
activation or maturin installation is needed. Rust sources and Cargo files are
included in uv's cache keys, so subsequent `uv sync` or `uv run` rebuilds changed
code. `uv.lock` records the Python project resolution.

The tests generate their own EPUB and MOBI inputs, covering every supported
format, nested navigation, Unicode, DRM, malformed inputs, and concurrent calls.
They need no upstream checkout or test-time downloads.

Additional Rust checks: `cargo fmt --check`,
`cargo clippy --locked --all-targets -- -D warnings`, and `cargo test --locked --lib`.
For Rust's embedded-interpreter test, relocatable Python installations may need
`PYTHONHOME` set to Python's base prefix. On Linux, also add `$PYTHONHOME/lib` to
`LD_LIBRARY_PATH` so the test executable can load the Python shared library.
Importing the extension does not require these settings.

Release artifacts go to `dist/`, with the wheel built from the source archive.
Use release builds when measuring performance.

Local Linux wheels are not necessarily portable: use manylinux containers or
maturin's compatible Zig support for release builds.

## Release setup

The workflow in `.github/workflows/python.yml` checks Rust, builds wheels for
Linux x86_64/ARM64, macOS x86_64/ARM64, and Windows x86_64, tests each wheel on
Python 3.11 and 3.15, and rebuilds/tests the source distribution.

Publishing requires a pushed `v<version>` tag matching `Cargo.toml` and successful
checks/builds. Pull requests, branch pushes, and manual runs do not publish.
Before the first release:

1. Confirm that `boko-ebook` is available; the name is not reserved by this repo.
2. Configure the PyPI pending/trusted publisher for this repository, workflow
   `python.yml`, and GitHub environment `pypi`.
3. Create a protected `pypi` environment with required reviewers and tag restrictions.
4. Validate all platform builds and rehearse on TestPyPI before approving production.
   TestPyPI requires its own publisher or externally configured credentials:
   `uv publish --publish-url https://test.pypi.org/legacy/ dist/*`.

OIDC publishing requires no long-lived PyPI token. The version in `Cargo.toml` is
the single source for Python metadata; keep `Cargo.lock` committed for release builds.

## License

GPL-3.0-or-later, matching the linked Boko core. See [LICENSE](LICENSE).
Boko's Rust implementation and original authorship remain with the
[upstream project](https://github.com/zacharydenton/boko).
