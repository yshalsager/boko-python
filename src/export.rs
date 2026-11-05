use std::io::{Cursor, Seek, Write};

use boko_core::{Azw3Config, Azw3Exporter, Book, EpubConfig, EpubExporter, Exporter, Format};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

pub(crate) struct ExportOptions {
    format: Format,
    normalize: bool,
    compression_level: Option<u32>,
}

impl ExportOptions {
    pub(crate) fn new(
        format: Format,
        normalize: Option<bool>,
        compression_level: Option<u32>,
    ) -> PyResult<Self> {
        if !format.can_export() {
            return Err(PyValueError::new_err("MOBI output is not supported"));
        }
        if normalize.is_some() && !matches!(format, Format::Epub | Format::Azw3) {
            return Err(PyValueError::new_err(
                "normalize is only supported for EPUB and AZW3",
            ));
        }
        if compression_level.is_some() && format != Format::Epub {
            return Err(PyValueError::new_err(
                "compression_level is only supported for EPUB",
            ));
        }
        // The zip backend rejects level 0 despite the core config's 0-9 documentation.
        if compression_level.is_some_and(|level| !(1..=9).contains(&level)) {
            return Err(PyValueError::new_err(
                "compression_level must be between 1 and 9",
            ));
        }
        Ok(Self {
            format,
            normalize: normalize.unwrap_or(false),
            compression_level,
        })
    }

    pub(crate) fn export(&self, book: &Book) -> boko_core::Result<Vec<u8>> {
        let mut output = Cursor::new(Vec::new());
        self.write(book, &mut output)?;
        Ok(output.into_inner())
    }

    pub(crate) fn write<W: Write + Seek>(
        &self,
        book: &Book,
        output: &mut W,
    ) -> boko_core::Result<()> {
        match self.format {
            Format::Epub => EpubExporter::new()
                .with_config(EpubConfig {
                    normalize: self.normalize,
                    compression_level: self.compression_level,
                })
                .export(book, output),
            Format::Azw3 => Azw3Exporter::new()
                .with_config(Azw3Config {
                    normalize: self.normalize,
                })
                .export(book, output),
            format => book.export(format, output),
        }
    }
}
