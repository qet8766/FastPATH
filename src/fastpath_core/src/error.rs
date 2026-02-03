//! Error types for fastpath_core.

use pyo3::exceptions::PyRuntimeError;
use pyo3::PyErr;
use thiserror::Error;

/// Error types for tile operations.
#[derive(Error, Debug)]
pub enum TileError {
    #[error("Failed to decode JPEG: {0}")]
    Decode(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON parse error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Invalid metadata: {0}")]
    Validation(String),
}

impl From<TileError> for PyErr {
    fn from(err: TileError) -> PyErr {
        PyRuntimeError::new_err(err.to_string())
    }
}

/// Result type alias for tile operations.
pub type TileResult<T> = Result<T, TileError>;
