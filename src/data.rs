use boko_core::model::{AnchorTarget, GlobalNodeId, Landmark, LandmarkType};
use boko_core::{Metadata, TocEntry};
use pyo3::prelude::*;
use pyo3::types::PyDict;

macro_rules! dict {
    ($py:expr, $($key:literal => $value:expr),* $(,)?) => {{
        let result = pyo3::types::PyDict::new($py);
        $(result.set_item($key, $value)?;)*
        Ok::<_, pyo3::PyErr>(result)
    }};
}
pub(crate) use dict;

pub(crate) fn metadata<'py>(py: Python<'py>, meta: &Metadata) -> PyResult<Bound<'py, PyDict>> {
    let contributors = meta
        .contributors
        .iter()
        .map(|contributor| {
            dict!(py,
                "name" => &contributor.name,
                "file_as" => &contributor.file_as,
                "role" => &contributor.role,
            )
        })
        .collect::<PyResult<Vec<_>>>()?;
    let collection = meta
        .collection
        .as_ref()
        .map(|collection| -> PyResult<_> {
            dict!(py,
                "name" => &collection.name,
                "collection_type" => &collection.collection_type,
                "position" => collection.position,
            )
        })
        .transpose()?;
    dict!(py,
        "title" => &meta.title,
        "authors" => &meta.authors,
        "language" => &meta.language,
        "identifier" => &meta.identifier,
        "publisher" => &meta.publisher,
        "description" => &meta.description,
        "subjects" => &meta.subjects,
        "date" => &meta.date,
        "rights" => &meta.rights,
        "cover_image" => &meta.cover_image,
        "modified_date" => &meta.modified_date,
        "title_sort" => &meta.title_sort,
        "author_sort" => &meta.author_sort,
        "page_progression_direction" => &meta.page_progression_direction,
        "is_rtl" => meta.is_rtl(),
        "contributors" => contributors,
        "collection" => collection,
    )
}

pub(crate) fn node_id(py: Python<'_>, id: GlobalNodeId) -> PyResult<Bound<'_, PyDict>> {
    dict!(py, "chapter_id" => id.chapter.0, "node_id" => id.node.0)
}

pub(crate) fn target<'py>(py: Python<'py>, target: &AnchorTarget) -> PyResult<Bound<'py, PyDict>> {
    match target {
        AnchorTarget::Internal(id) => dict!(py,
            "kind" => "internal", "chapter_id" => id.chapter.0, "node_id" => id.node.0,
        ),
        AnchorTarget::Chapter(id) => dict!(py, "kind" => "chapter", "chapter_id" => id.0),
        AnchorTarget::External(url) => dict!(py, "kind" => "external", "url" => url),
    }
}

pub(crate) fn toc<'py>(py: Python<'py>, entries: &[TocEntry]) -> PyResult<Vec<Bound<'py, PyDict>>> {
    entries
        .iter()
        .map(|entry| {
            dict!(py,
                "title" => &entry.title,
                "href" => &entry.href,
                "play_order" => entry.play_order,
                "target" => entry.target.as_ref().map(|value| target(py, value)).transpose()?,
                "children" => toc(py, &entry.children)?,
            )
        })
        .collect()
}

pub(crate) fn landmarks<'py>(
    py: Python<'py>,
    entries: &[Landmark],
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    entries
        .iter()
        .map(|entry| {
            let kind = match entry.landmark_type {
                LandmarkType::Cover => "cover",
                LandmarkType::TitlePage => "title_page",
                LandmarkType::Toc => "toc",
                LandmarkType::StartReading => "start_reading",
                LandmarkType::BodyMatter => "body_matter",
                LandmarkType::FrontMatter => "front_matter",
                LandmarkType::BackMatter => "back_matter",
                LandmarkType::Acknowledgements => "acknowledgements",
                LandmarkType::Bibliography => "bibliography",
                LandmarkType::Glossary => "glossary",
                LandmarkType::Index => "index",
                LandmarkType::Preface => "preface",
                LandmarkType::Endnotes => "endnotes",
                LandmarkType::Loi => "loi",
                LandmarkType::Lot => "lot",
            };
            dict!(py, "type" => kind, "href" => &entry.href, "label" => &entry.label)
        })
        .collect()
}
