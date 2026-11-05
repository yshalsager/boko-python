from collections.abc import Sequence
from os import PathLike
from types import TracebackType
from typing import Literal, TypedDict

class _Contributor(TypedDict):
    name: str
    file_as: str | None
    role: str | None

class _Collection(TypedDict):
    name: str
    collection_type: str | None
    position: float | None

class _Metadata(TypedDict):
    title: str
    authors: list[str]
    language: str
    identifier: str
    publisher: str | None
    description: str | None
    subjects: list[str]
    date: str | None
    rights: str | None
    cover_image: str | None
    modified_date: str | None
    contributors: list[_Contributor]
    title_sort: str | None
    author_sort: str | None
    collection: _Collection | None
    page_progression_direction: str | None
    is_rtl: bool

class _NodeId(TypedDict):
    chapter_id: int
    node_id: int

class _InternalTarget(_NodeId):
    kind: Literal['internal']

class _ChapterTarget(TypedDict):
    kind: Literal['chapter']
    chapter_id: int

class _ExternalTarget(TypedDict):
    kind: Literal['external']
    url: str

_Target = _InternalTarget | _ChapterTarget | _ExternalTarget

class _TocEntry(TypedDict):
    title: str
    href: str
    children: list[_TocEntry]
    play_order: int | None
    target: _Target | None

class _Landmark(TypedDict):
    type: str
    href: str
    label: str

class _SpineEntry(TypedDict):
    id: int
    source_path: str | None
    size_estimate: int

class _FontFace(TypedDict):
    font_family: str
    font_weight: int
    font_style: str
    src: str

class _Paragraph(TypedDict):
    type: Literal['paragraph']
    text: str

class _CodeBlock(TypedDict):
    type: Literal['code_block']
    language: str | None
    code: str

class _BlockQuote(TypedDict):
    type: Literal['block_quote']
    text: str

class _List(TypedDict):
    type: Literal['list']
    ordered: bool
    items: list[str]

class _Table(TypedDict):
    type: Literal['table']
    headers: list[str]
    rows: list[list[str]]

class _Image(TypedDict):
    type: Literal['image']
    src: str
    alt: str

class _Rule(TypedDict):
    type: Literal['rule']

_ContentBlock = _Paragraph | _CodeBlock | _BlockQuote | _List | _Table | _Image | _Rule

class _Section(TypedDict):
    level: int
    title: str
    content: list[_ContentBlock]
    children: list[_Section]

class _SectionTree(TypedDict):
    title: str
    authors: list[str]
    language: str
    preamble: list[_ContentBlock]
    sections: list[_Section]

class _Link(TypedDict):
    source: _NodeId
    target: _Target

class _BrokenLink(TypedDict):
    source: _NodeId
    href: str

_OptimizePass = TypedDict('_OptimizePass', {'pass': str, 'assets_changed': int, 'bytes_saved': int})

class _OptimizeReport(TypedDict):
    passes: list[_OptimizePass]
    assets_changed: int
    bytes_saved: int

class Chapter:
    @property
    def id(self) -> int: ...
    @property
    def source_path(self) -> str | None: ...
    @property
    def raw(self) -> bytes: ...
    @property
    def text(self) -> str: ...
    @property
    def xhtml(self) -> str: ...
    @property
    def css(self) -> str: ...
    def node_text(self, node_id: int) -> str: ...

class ResolvedLinks:
    def __len__(self) -> int: ...
    @property
    def links(self) -> list[_Link]: ...
    @property
    def broken_links(self) -> list[_BrokenLink]: ...
    def get(self, chapter_id: int, node_id: int) -> _Target | None: ...
    def links_to(self, chapter_id: int, node_id: int | None = None) -> list[_NodeId]: ...

class Book:
    @staticmethod
    def open(path: str | PathLike[str], format: str | None = None) -> Book: ...
    @staticmethod
    def from_bytes(data: bytes, format: str) -> Book: ...
    def close(self) -> None: ...
    @property
    def closed(self) -> bool: ...
    def __enter__(self) -> Book: ...
    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None: ...
    @property
    def metadata(self) -> _Metadata: ...
    @property
    def toc(self) -> list[_TocEntry]: ...
    @property
    def landmarks(self) -> list[_Landmark]: ...
    @property
    def spine(self) -> list[_SpineEntry]: ...
    @property
    def assets(self) -> list[str]: ...
    @property
    def font_faces(self) -> list[_FontFace]: ...
    @property
    def requires_normalized_export(self) -> bool: ...
    def load_asset(self, path: str) -> bytes: ...
    def cover(self) -> bytes | None: ...
    def chapter(self, chapter_id: int) -> Chapter: ...
    def chapters(self, ids: Sequence[int] | None = None) -> list[Chapter]: ...
    def sections(self) -> _SectionTree: ...
    def resolve_links(self) -> ResolvedLinks: ...
    def clear_cache(self) -> None: ...
    def optimize(self) -> _OptimizeReport: ...
    def export(self, format: str, *, normalize: bool | None = None, compression_level: int | None = None) -> bytes: ...

def convert(data: bytes, from_format: str, to_format: str) -> bytes: ...
def convert_file(input_path: str | PathLike[str], output_path: str | PathLike[str]) -> None: ...
