use boko_core::{ContentBlock, SectionNode, SectionTree};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::data::dict;

pub(crate) fn tree<'py>(py: Python<'py>, tree: &SectionTree) -> PyResult<Bound<'py, PyDict>> {
    dict!(py,
        "title" => &tree.title,
        "authors" => &tree.authors,
        "language" => &tree.language,
        "preamble" => blocks(py, &tree.preamble)?,
        "sections" => sections(py, &tree.sections)?,
    )
}

fn sections<'py>(py: Python<'py>, entries: &[SectionNode]) -> PyResult<Vec<Bound<'py, PyDict>>> {
    entries
        .iter()
        .map(|section| {
            dict!(py,
                "level" => section.level,
                "title" => &section.title,
                "content" => blocks(py, &section.content)?,
                "children" => sections(py, &section.children)?,
            )
        })
        .collect()
}

fn blocks<'py>(py: Python<'py>, blocks: &[ContentBlock]) -> PyResult<Vec<Bound<'py, PyDict>>> {
    blocks
        .iter()
        .map(|block| match block {
            ContentBlock::Paragraph { text } => dict!(py, "type" => "paragraph", "text" => text),
            ContentBlock::CodeBlock { language, code } => {
                dict!(py, "type" => "code_block", "language" => language, "code" => code)
            }
            ContentBlock::BlockQuote { text } => dict!(py, "type" => "block_quote", "text" => text),
            ContentBlock::List { ordered, items } => {
                dict!(py, "type" => "list", "ordered" => ordered, "items" => items)
            }
            ContentBlock::Table { headers, rows } => {
                dict!(py, "type" => "table", "headers" => headers, "rows" => rows)
            }
            ContentBlock::Image { src, alt } => {
                dict!(py, "type" => "image", "src" => src, "alt" => alt)
            }
            ContentBlock::Rule => dict!(py, "type" => "rule"),
        })
        .collect()
}
