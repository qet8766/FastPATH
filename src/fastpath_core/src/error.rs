//! Error types for fastpath_core.

use pyo3::exceptions::PyRuntimeError;
use pyo3::PyErr;
use thiserror::Error;

/// Error types for tile operations.
#[derive(Error, Debug)]
pub enum TileError {
    #[error("Slide not loaded")]
    NotLoaded,

    #[error("Invalid tile coordinate: level={level}, col={col}, row={row}")]
    InvalidCoord { level: u32, col: u32, row: u32 },

    #[error("Tile not found: {path}")]
    TileNotFound { path: String },

    #[error("Failed to decode JPEG: {0}")]
    DecodeError(String),

    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    #[error("Metadata error: {0}")]
    MetadataError(String),

    #[error("JSON parse error: {0}")]
    JsonError(#[from] serde_json::Error),
}

impl From<TileError> for PyErr {
    fn from(err: TileError) -> PyErr {
        PyRuntimeError::new_err(err.to_string())
    }
}

/// Result type alias for tile operations.
pub type TileResult<T> = Result<T, TileError>;
