//! Python buffer wrapper for decoded tile bytes.
//!
//! This enables zero-copy transfer of decoded RGB tiles from Rust to Python by
//! exposing `bytes::Bytes` through Python's buffer protocol.

use std::ffi::CString;
use std::os::raw::{c_int, c_void};
use std::ptr;

use bytes::Bytes;
use pyo3::exceptions::PyBufferError;
use pyo3::ffi;
use pyo3::prelude::*;

/// Read-only buffer over tile pixel bytes.
#[pyclass]
pub struct TileBuffer {
    data: Bytes,
}

impl TileBuffer {
    pub fn new(data: Bytes) -> Self {
        Self { data }
    }
}

#[pymethods]
impl TileBuffer {
    fn __len__(&self) -> usize {
        self.data.len()
    }

    /// Python buffer protocol: fill `view` with a pointer to our bytes.
    ///
    /// # Safety
    /// CPython calls this with a valid `Py_buffer*` or NULL.
    unsafe fn __getbuffer__(
        slf: Bound<'_, Self>,
        view: *mut ffi::Py_buffer,
        flags: c_int,
    ) -> PyResult<()> {
        if view.is_null() {
            return Err(PyBufferError::new_err("View is null"));
        }

        if (flags & ffi::PyBUF_WRITABLE) == ffi::PyBUF_WRITABLE {
            return Err(PyBufferError::new_err("Object is not writable"));
        }

        let (ptr, len) = {
            let borrowed = slf.borrow();
            (borrowed.data.as_ref().as_ptr(), borrowed.data.len())
        };

        // Keep `self` alive for the lifetime of the exported buffer.
        (*view).obj = slf.into_any().into_ptr();

        (*view).buf = ptr as *mut c_void;
        (*view).len = len as isize;
        (*view).readonly = 1;
        (*view).itemsize = 1;

        // Optional PEP 3118 format string.
        (*view).format = if (flags & ffi::PyBUF_FORMAT) == ffi::PyBUF_FORMAT {
            CString::new("B").unwrap().into_raw()
        } else {
            ptr::null_mut()
        };

        (*view).ndim = 1;
        (*view).shape = if (flags & ffi::PyBUF_ND) == ffi::PyBUF_ND {
            &mut (*view).len
        } else {
            ptr::null_mut()
        };

        (*view).strides = if (flags & ffi::PyBUF_STRIDES) == ffi::PyBUF_STRIDES {
            &mut (*view).itemsize
        } else {
            ptr::null_mut()
        };

        (*view).suboffsets = ptr::null_mut();
        (*view).internal = ptr::null_mut();

        Ok(())
    }

    /// Python buffer protocol: release any auxiliary memory.
    ///
    /// # Safety
    /// CPython calls this with a valid `Py_buffer*` used previously for getbuffer.
    unsafe fn __releasebuffer__(&self, view: *mut ffi::Py_buffer) {
        if view.is_null() {
            return;
        }
        // Release memory held by the optional format string (if allocated).
        if !(*view).format.is_null() {
            drop(CString::from_raw((*view).format));
            (*view).format = ptr::null_mut();
        }
    }
}

