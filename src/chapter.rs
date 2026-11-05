use std::sync::Arc;

use boko_core::export::{generate_css_all, synthesize_xhtml_document};
use boko_core::{Book, Chapter as CoreChapter, ChapterId, NodeId, Role};
use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;

use crate::detach;

/// An owned, read-only chapter snapshot, usable after its book is closed.
#[pyclass(frozen, module = "boko")]
pub(crate) struct Chapter {
    #[pyo3(get)]
    id: u32,
    #[pyo3(get)]
    source_path: Option<String>,
    raw: Vec<u8>,
    inner: Arc<CoreChapter>,
}

impl Chapter {
    pub(crate) fn load(
        book: &Book,
        id: ChapterId,
        inner: Arc<CoreChapter>,
    ) -> boko_core::Result<Self> {
        Ok(Self {
            id: id.0,
            source_path: book.source_id(id).map(str::to_owned),
            raw: book.load_raw(id)?,
            inner,
        })
    }
}

#[pymethods]
impl Chapter {
    /// Original format-specific chapter bytes. KFX raw content is binary, not HTML.
    #[getter]
    fn raw(&self) -> &[u8] {
        &self.raw
    }

    /// Readable live-node text, including footnotes and code whitespace.
    #[getter]
    fn text(&self, py: Python<'_>) -> PyResult<String> {
        detach(py, || text(&self.inner, NodeId::ROOT))
    }

    /// Text of a specific normalized node, for navigating resolved link targets.
    fn node_text(&self, py: Python<'_>, node_id: u32) -> PyResult<String> {
        let id = NodeId(node_id);
        if self.inner.node(id).is_none() {
            return Err(PyKeyError::new_err(format!("node {node_id}")));
        }
        detach(py, || text(&self.inner, id))
    }

    /// Normalized XHTML. Its stylesheet link refers to the separate css property as chapter.css.
    #[getter]
    fn xhtml(&self, py: Python<'_>) -> PyResult<String> {
        detach(py, || {
            let css = generate_css_all(&self.inner.styles);
            synthesize_xhtml_document(&self.inner, &css.class_map, "", Some("chapter.css")).body
        })
    }

    /// CSS matching the class names in xhtml.
    #[getter]
    fn css(&self, py: Python<'_>) -> PyResult<String> {
        detach(py, || generate_css_all(&self.inner.styles).stylesheet)
    }
}

fn text(chapter: &CoreChapter, root: NodeId) -> String {
    let mut output = String::new();
    let mut pending = vec![(root, false)];
    while let Some((id, exit)) = pending.pop() {
        let Some(node) = chapter.node(id) else {
            continue;
        };
        let separator = match node.role {
            Role::TableCell => "\t",
            Role::Paragraph
            | Role::Heading(_)
            | Role::ListItem
            | Role::DefinitionTerm
            | Role::DefinitionDescription
            | Role::TableRow
            | Role::CodeBlock
            | Role::BlockQuote
            | Role::Footnote
            | Role::Caption
            | Role::Container
            | Role::Sidebar => "\n",
            _ => "",
        };
        if exit {
            if separator == "\t" || (!separator.is_empty() && !output.ends_with(separator)) {
                output.push_str(separator);
            }
            continue;
        }
        if separator == "\n" && !output.is_empty() && !output.ends_with('\n') {
            output.push('\n');
        }
        match node.role {
            Role::Text => output.push_str(chapter.text(node.text)),
            Role::Break | Role::Rule => output.push('\n'),
            Role::Math => {
                if let Some(math) = chapter.math.get(&id) {
                    output.push_str(&math.to_text());
                }
            }
            Role::Image => {
                if let Some(alt) = chapter.semantics.alt(id) {
                    output.push_str(alt);
                }
            }
            _ => {}
        }
        pending.push((id, true));
        let children: Vec<_> = chapter.children(id).collect();
        pending.extend(children.into_iter().rev().map(|child| (child, false)));
    }
    output
}

#[cfg(test)]
mod tests {
    use super::*;
    use boko_core::Node;

    #[test]
    fn text_separates_blocks_without_trimming_code() {
        let mut chapter = CoreChapter::new();
        let range = chapter.append_text("prefix");
        let prefix = chapter.alloc_node(Node::text(range));
        chapter.append_child(NodeId::ROOT, prefix);
        for (role, value) in [(Role::Paragraph, "body"), (Role::CodeBlock, "  code\n\n")] {
            let parent = chapter.alloc_node(Node::new(role));
            chapter.append_child(NodeId::ROOT, parent);
            let range = chapter.append_text(value);
            let child = chapter.alloc_node(Node::text(range));
            chapter.append_child(parent, child);
        }
        assert_eq!(text(&chapter, NodeId::ROOT), "prefix\nbody\n  code\n\n");
    }

    #[test]
    fn text_uses_live_nodes_and_keeps_footnotes() {
        let mut chapter = CoreChapter::new();
        chapter.append_text("unreferenced text must not leak");
        for (role, value) in [
            (Role::Paragraph, "hello"),
            (Role::Footnote, "note"),
            (Role::CodeBlock, "  indented\ncode"),
        ] {
            let parent = chapter.alloc_node(Node::new(role));
            chapter.append_child(NodeId::ROOT, parent);
            let range = chapter.append_text(value);
            let child = chapter.alloc_node(Node::text(range));
            chapter.append_child(parent, child);
        }
        assert_eq!(
            text(&chapter, NodeId::ROOT),
            "hello\nnote\n  indented\ncode\n"
        );
    }
}
