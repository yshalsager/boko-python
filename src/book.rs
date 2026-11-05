use std::path::PathBuf;

use boko_core::{Book as CoreBook, ChapterId, ToCss};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::chapter::Chapter;
use crate::data::dict;
use crate::export::ExportOptions;
use crate::links::ResolvedLinks;
use crate::{data, detach, parse_format, parse_import_format, py_err, sections};

/// A reusable ebook handle. Use `open`/`from_bytes` and `close` or a with statement.
#[pyclass(module = "boko")]
pub(crate) struct Book {
    inner: Option<CoreBook>,
}

impl Book {
    fn inner(&self) -> PyResult<&CoreBook> {
        self.inner
            .as_ref()
            .ok_or_else(|| PyValueError::new_err("book is closed"))
    }

    fn inner_mut(&mut self) -> PyResult<&mut CoreBook> {
        self.inner
            .as_mut()
            .ok_or_else(|| PyValueError::new_err("book is closed"))
    }
}

#[pymethods]
impl Book {
    /// Open a path, inferring its format from the extension unless explicitly supplied.
    #[staticmethod]
    #[pyo3(signature = (path, format=None))]
    fn open(py: Python<'_>, path: PathBuf, format: Option<&str>) -> PyResult<Self> {
        let format = format.map(parse_import_format).transpose()?;
        detach(py, || match format {
            Some(format) => CoreBook::open_format(path, format),
            None => CoreBook::open(path),
        })?
        .map(|book| Self { inner: Some(book) })
        .map_err(py_err)
    }

    /// Parse ebook bytes with an explicit input format.
    #[staticmethod]
    fn from_bytes(py: Python<'_>, data: &[u8], format: &str) -> PyResult<Self> {
        let format = parse_import_format(format)?;
        detach(py, || CoreBook::from_bytes(data, format))?
            .map(|book| Self { inner: Some(book) })
            .map_err(py_err)
    }

    /// Release the source file and caches. Calling close more than once is harmless.
    fn close(&mut self, py: Python<'_>) -> PyResult<()> {
        let book = self.inner.take();
        detach(py, || drop(book))
    }

    #[getter]
    fn closed(&self) -> bool {
        self.inner.is_none()
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyResult<PyRef<'_, Self>> {
        slf.inner()?;
        Ok(slf)
    }

    fn __exit__(
        &mut self,
        py: Python<'_>,
        _exc_type: &Bound<'_, PyAny>,
        _exc_value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.close(py)
    }

    /// Complete metadata as a detached Python dictionary, including inferred `is_rtl`.
    #[getter]
    fn metadata<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        data::metadata(py, self.inner()?.metadata())
    }

    #[getter]
    fn toc<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        data::toc(py, self.inner()?.toc())
    }

    #[getter]
    fn landmarks<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        data::landmarks(py, self.inner()?.landmarks())
    }

    /// Reading order with stable chapter IDs, source paths, and estimated sizes.
    #[getter]
    fn spine<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let book = self.inner()?;
        book.spine()
            .iter()
            .map(|entry| {
                dict!(py,
                    "id" => entry.id.0,
                    "source_path" => book.source_id(entry.id),
                    "size_estimate" => entry.size_estimate,
                )
            })
            .collect()
    }

    /// Archive-relative asset names, not filesystem paths.
    #[getter]
    fn assets(&self) -> PyResult<Vec<String>> {
        Ok(self.inner()?.list_assets().to_vec())
    }

    #[getter]
    fn font_faces<'py>(&self, py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let book = self.inner()?;
        let fonts = detach(py, || book.font_faces())?;
        fonts
            .iter()
            .map(|font| {
                dict!(py,
                    "font_family" => &font.font_family,
                    "font_weight" => font.font_weight.0,
                    "font_style" => font.font_style.to_css_string(),
                    "src" => &font.src,
                )
            })
            .collect()
    }

    #[getter]
    fn requires_normalized_export(&self) -> PyResult<bool> {
        Ok(self.inner()?.requires_normalized_export())
    }

    fn load_asset(&self, py: Python<'_>, path: &str) -> PyResult<Vec<u8>> {
        let book = self.inner()?;
        detach(py, || book.load_asset(path))?.map_err(py_err)
    }

    /// Return cover bytes, or None if the source does not identify a cover.
    fn cover(&self, py: Python<'_>) -> PyResult<Option<Vec<u8>>> {
        let book = self.inner()?;
        detach(py, || {
            book.metadata()
                .cover_image
                .as_ref()
                .map(|path| book.load_asset(path))
                .transpose()
        })?
        .map_err(py_err)
    }

    fn chapter(&self, py: Python<'_>, chapter_id: u32) -> PyResult<Chapter> {
        let book = self.inner()?;
        let id = ChapterId(chapter_id);
        detach(py, || {
            Chapter::load(book, id, book.load_chapter_cached(id)?)
        })?
        .map_err(py_err)
    }

    /// Load in the supplied order, or spine order if omitted; uncached loads use core parallelism.
    #[pyo3(signature = (ids=None))]
    fn chapters(&self, py: Python<'_>, ids: Option<Vec<u32>>) -> PyResult<Vec<Chapter>> {
        let book = self.inner()?;
        let ids: Vec<_> = ids.map_or_else(
            || book.spine().iter().map(|entry| entry.id).collect(),
            |ids| ids.into_iter().map(ChapterId).collect(),
        );
        detach(py, || {
            let chapters = book.load_chapters_cached(&ids)?;
            ids.into_iter()
                .zip(chapters)
                .map(|(id, inner)| Chapter::load(book, id, inner))
                .collect::<boko_core::Result<Vec<_>>>()
        })?
        .map_err(py_err)
    }

    /// Extract heading-nested content. Core footnote nodes are omitted; classification depends on the importer.
    fn sections<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let book = self.inner_mut()?;
        let tree = detach(py, || boko_core::extract_section_tree(book))?
            .map_err(|error| py_err(error.into()))?;
        sections::tree(py, &tree)
    }

    /// Resolve forward links, backlinks, and broken links; the result is an owned snapshot.
    fn resolve_links(&self, py: Python<'_>) -> PyResult<ResolvedLinks> {
        let book = self.inner()?;
        Ok(ResolvedLinks {
            inner: detach(py, || book.resolve_links())?.map_err(py_err)?,
        })
    }

    /// Clear the core chapter cache with exclusive access. Existing chapter snapshots remain valid.
    fn clear_cache(&mut self, py: Python<'_>) -> PyResult<()> {
        let book = self.inner_mut()?;
        detach(py, || book.clear_cache())
    }

    /// Apply the core's default image optimization, mutating this book and returning savings.
    fn optimize<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let book = self.inner_mut()?;
        let report = detach(py, || book.optimize())?;
        let passes = report
            .passes
            .iter()
            .map(|pass| {
                dict!(py,
                    "pass" => pass.pass,
                    "assets_changed" => pass.assets_changed,
                    "bytes_saved" => pass.bytes_saved,
                )
            })
            .collect::<PyResult<Vec<_>>>()?;
        dict!(py,
            "assets_changed" => report.assets_changed(),
            "bytes_saved" => report.bytes_saved(),
            "passes" => passes,
        )
    }

    /// Export bytes, optionally normalizing EPUB/AZW3 or setting EPUB deflate compression (1-9).
    #[pyo3(signature = (format, *, normalize=None, compression_level=None))]
    fn export(
        &self,
        py: Python<'_>,
        format: &str,
        normalize: Option<bool>,
        compression_level: Option<u32>,
    ) -> PyResult<Vec<u8>> {
        let book = self.inner()?;
        let options = ExportOptions::new(parse_format(format)?, normalize, compression_level)?;
        detach(py, || options.export(book))?.map_err(py_err)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::exceptions::PyRuntimeError;

    #[test]
    fn cache_clearing_requires_exclusive_access() {
        Python::initialize();
        Python::attach(|py| {
            let book = Py::new(py, Book { inner: None }).unwrap();
            let book = book.bind(py);
            let reader = book.borrow();
            let error = book.call_method0("clear_cache").unwrap_err();
            assert!(error.is_instance_of::<PyRuntimeError>(py));
            drop(reader);
            let error = book.call_method0("clear_cache").unwrap_err();
            assert!(error.is_instance_of::<PyValueError>(py));
        });
    }
}
