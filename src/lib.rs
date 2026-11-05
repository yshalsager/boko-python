//! Python bindings for ebook conversion and inspection.

mod book;
mod chapter;
mod data;
mod export;
mod links;
mod sections;

use std::fs::File;
use std::io::ErrorKind;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::{PathBuf, absolute};

use pyo3::exceptions::{PyKeyError, PyPermissionError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;

use boko_core::{Book, Error, Format};

fn parse_format(name: &str) -> PyResult<Format> {
    match name.to_ascii_lowercase().as_str() {
        "epub" => Ok(Format::Epub),
        "azw3" => Ok(Format::Azw3),
        "mobi" | "azw" => Ok(Format::Mobi),
        "kfx" => Ok(Format::Kfx),
        "markdown" | "md" => Ok(Format::Markdown),
        _ => Err(PyValueError::new_err(format!("unknown format: {name}"))),
    }
}

fn parse_import_format(name: &str) -> PyResult<Format> {
    let format = parse_format(name)?;
    if !format.can_import() {
        return Err(PyValueError::new_err(format!(
            "format not supported as input: {name}"
        )));
    }
    Ok(format)
}

fn py_err(error: Error) -> PyErr {
    match error {
        Error::Io(error) => match error.downcast::<Error>() {
            Ok(error) => py_err(error),
            // Byte parsers also report malformed input through io::Error.
            Err(error) => match error.kind() {
                ErrorKind::InvalidData | ErrorKind::UnexpectedEof => {
                    PyValueError::new_err(error.to_string())
                }
                _ => error.into(),
            },
        },
        Error::UnsupportedFormat { .. } | Error::Malformed { .. } => {
            PyValueError::new_err(error.to_string())
        }
        Error::DrmProtected(_) => PyPermissionError::new_err(error.to_string()),
        Error::NotFound { .. } => PyKeyError::new_err(error.to_string()),
        _ => PyRuntimeError::new_err(error.to_string()),
    }
}

fn detach<T: Send>(py: Python<'_>, work: impl FnOnce() -> T + Send) -> PyResult<T> {
    py.detach(|| catch_unwind(AssertUnwindSafe(work)))
        .map_err(|_| PyRuntimeError::new_err("boko operation panicked"))
}

/// Convert ebook bytes. Inputs: epub, azw3, mobi/azw, kfx. Outputs: epub, azw3, kfx, markdown/md.
///
/// Returns bytes (UTF-8 for Markdown). Raises `ValueError` for invalid formats or malformed
/// books, `PermissionError` for DRM, and `OSError` for underlying I/O failures.
#[pyfunction]
fn convert(py: Python<'_>, data: &[u8], from_format: &str, to_format: &str) -> PyResult<Vec<u8>> {
    let from = parse_import_format(from_format)?;
    let options = export::ExportOptions::new(parse_format(to_format)?, None, None)?;
    detach(py, || options.export(&Book::from_bytes(data, from)?))?.map_err(py_err)
}

/// Convert files, inferring formats from extensions and replacing the output atomically.
#[pyfunction]
fn convert_file(py: Python<'_>, input_path: PathBuf, output_path: PathBuf) -> PyResult<()> {
    let input_path = absolute(input_path)?;
    let output_path = absolute(output_path)?;
    let extension = output_path
        .extension()
        .and_then(|extension| extension.to_str())
        .ok_or_else(|| PyValueError::new_err("output path must have a supported extension"))?;
    let options = export::ExportOptions::new(parse_format(extension)?, None, None)?;
    if output_path.try_exists()?
        && py
            .import("os.path")?
            .call_method1("samefile", (&input_path, &output_path))?
            .extract::<bool>()?
    {
        return Err(PyValueError::new_err(
            "input and output must be different files",
        ));
    }
    let book = detach(py, || Book::open(&input_path))?.map_err(py_err)?;
    let temporary = py
        .import("tempfile")?
        .getattr("TemporaryDirectory")?
        .call((), Some(&data::dict!(py, "dir" => output_path.parent())?))?;
    let temporary_path = temporary
        .getattr("name")?
        .extract::<PathBuf>()?
        .join("book");
    let result = detach(py, move || -> boko_core::Result<()> {
        let mut open_options = File::options();
        open_options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            open_options.mode(0o600);
        }
        let mut file = open_options.open(&temporary_path)?;
        options.write(&book, &mut file)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(temporary_path, output_path)?;
        Ok(())
    })
    .and_then(|result| result.map_err(py_err));
    // Cleanup runs on errors too, without replacing the original conversion error.
    result.and(temporary.call_method0("cleanup").map(|_| ()))
}

/// Native ebook conversion and metadata inspection, powered by Boko.
#[pymodule]
mod boko {
    #[pymodule_export]
    use super::{convert, convert_file};
    #[pymodule_export]
    use crate::book::Book;
    #[pymodule_export]
    use crate::chapter::Chapter;
    #[pymodule_export]
    use crate::links::ResolvedLinks;
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::exceptions::PyFileNotFoundError;

    #[test]
    fn detached_panics_are_runtime_errors() {
        Python::initialize();
        Python::attach(|py| {
            assert_eq!(detach(py, || 42).unwrap(), 42);
            let error = detach::<()>(py, || panic!("test panic")).unwrap_err();
            assert!(error.is_instance_of::<PyRuntimeError>(py));
        });
    }

    #[test]
    fn errors_keep_their_python_types() {
        Python::initialize();
        Python::attach(|py| {
            let error = py_err(Error::Io(std::io::Error::from(
                std::io::ErrorKind::NotFound,
            )));
            assert!(error.is_instance_of::<PyFileNotFoundError>(py));
            for kind in [ErrorKind::InvalidData, ErrorKind::UnexpectedEof] {
                let error = py_err(Error::Io(std::io::Error::from(kind)));
                assert!(error.is_instance_of::<PyValueError>(py));
            }
            let error = py_err(Error::UnsupportedFormat {
                detail: "test".into(),
            });
            assert!(error.is_instance_of::<PyValueError>(py));
            let error = py_err(Error::Malformed {
                format: Format::Epub,
                context: "test".into(),
            });
            assert!(error.is_instance_of::<PyValueError>(py));
            let error = py_err(Error::DrmProtected(Format::Kfx));
            assert!(error.is_instance_of::<PyPermissionError>(py));
            let error = py_err(Error::NotFound {
                what: "test".into(),
            });
            assert!(error.is_instance_of::<PyKeyError>(py));
            let wrapped: std::io::Error = Error::NotFound {
                what: "wrapped resource".into(),
            }
            .into();
            assert!(py_err(Error::Io(wrapped)).is_instance_of::<PyKeyError>(py));
            let wrapped: std::io::Error = Error::DrmProtected(Format::Kfx).into();
            assert!(py_err(Error::Io(wrapped)).is_instance_of::<PyPermissionError>(py));
            let build = || -> PyResult<_> {
                crate::data::dict!(py, "before" => 1, "error" => Err::<u32, _>(PyValueError::new_err("test"))?)
            };
            assert!(build().unwrap_err().is_instance_of::<PyValueError>(py));
        });
    }
}
