use std::sync::Arc;

use boko_core::model::{GlobalNodeId, ResolvedLinks as CoreLinks};
use boko_core::{ChapterId, NodeId};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::data::{self, dict};

/// Owned link-resolution snapshot. Identifiers refer to normalized chapter nodes.
#[pyclass(frozen, module = "boko")]
pub(crate) struct ResolvedLinks {
    pub(crate) inner: Arc<CoreLinks>,
}

#[pymethods]
impl ResolvedLinks {
    fn __len__(&self) -> usize {
        self.inner.len()
    }

    /// All resolved links in deterministic chapter/node order.
    #[getter]
    fn links<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let mut links: Vec<_> = self.inner.iter().collect();
        links.sort_by_key(|(id, _)| (id.chapter.0, id.node.0));
        links
            .into_iter()
            .map(|(source, target)| {
                dict!(py, "source" => data::node_id(py, source)?, "target" => data::target(py, target)?)
            })
            .collect()
    }

    /// Unresolved hrefs and the source nodes containing them.
    #[getter]
    fn broken_links<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let mut links: Vec<_> = self.inner.broken_links().iter().collect();
        links.sort_by_key(|(id, _)| (id.chapter.0, id.node.0));
        links
            .into_iter()
            .map(
                |(source, href)| dict!(py, "source" => data::node_id(py, *source)?, "href" => href),
            )
            .collect()
    }

    /// Look up the target of a link node, or None if it is not a resolved source.
    fn get<'py>(
        &self,
        py: Python<'py>,
        chapter_id: u32,
        node_id: u32,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        self.inner
            .get(GlobalNodeId::new(ChapterId(chapter_id), NodeId(node_id)))
            .map(|target| data::target(py, target))
            .transpose()
    }

    /// Backlinks to a node, or to the chapter start when `node_id` is omitted.
    #[pyo3(signature = (chapter_id, node_id=None))]
    fn links_to<'py>(
        &self,
        py: Python<'py>,
        chapter_id: u32,
        node_id: Option<u32>,
    ) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let chapter = ChapterId(chapter_id);
        let links = match node_id {
            Some(node) => self
                .inner
                .links_to(GlobalNodeId::new(chapter, NodeId(node))),
            None => self.inner.links_to_chapter(chapter),
        };
        let mut links = links.to_vec();
        links.sort_by_key(|id| (id.chapter.0, id.node.0));
        links.into_iter().map(|id| data::node_id(py, id)).collect()
    }
}
