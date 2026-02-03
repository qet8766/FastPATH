//! Packed tile reader for .fastpath directories.

use std::fs::File;
use std::path::Path;

use bytes::Bytes;

use crate::error::{TileError, TileResult};

const MAGIC: &[u8; 8] = b"FPTIDX1\0";
const VERSION: u32 = 1;
const HEADER_SIZE: usize = 16;
const LEVEL_SIZE: usize = 20;
const ENTRY_SIZE: usize = 16;

#[derive(Debug, Clone)]
pub struct PackLevel {
    pub level: u32,
    pub cols: u32,
    pub rows: u32,
    pub entry_offset: u64,
}

#[derive(Debug, Clone, Copy)]
pub struct PackTileRef {
    pub offset: u64,
    pub length: u32,
}

#[derive(Debug)]
pub struct TilePack {
    pack: File,
    levels: Vec<PackLevel>,
    index_bytes: Vec<u8>,
    entries_base: u64,
    pack_len: u64,
}

impl TilePack {
    pub fn open(fastpath_dir: &Path) -> TileResult<Self> {
        let idx_path = fastpath_dir.join("tiles.idx");
        let pack_path = fastpath_dir.join("tiles.pack");

        let index_bytes = std::fs::read(&idx_path)?;
        let (levels, entries_base) = Self::parse_index(&index_bytes)?;

        let pack = File::open(&pack_path)?;
        let pack_len = pack.metadata()?.len();

        Ok(Self {
            pack,
            levels,
            index_bytes,
            entries_base,
            pack_len,
        })
    }

    fn parse_index(index_bytes: &[u8]) -> TileResult<(Vec<PackLevel>, u64)> {
        if index_bytes.len() < HEADER_SIZE {
            return Err(TileError::Validation("tiles.idx is too small".into()));
        }

        let magic = &index_bytes[0..8];
        if magic != MAGIC {
            return Err(TileError::Validation("tiles.idx magic mismatch".into()));
        }

        let version = u32::from_le_bytes(index_bytes[8..12].try_into().unwrap());
        if version != VERSION {
            return Err(TileError::Validation(format!(
                "Unsupported tiles.idx version: {}",
                version
            )));
        }

        let level_count = u32::from_le_bytes(index_bytes[12..16].try_into().unwrap()) as usize;
        if level_count == 0 {
            return Err(TileError::Validation("tiles.idx has no levels".into()));
        }

        let levels_bytes_len = level_count * LEVEL_SIZE;
        if index_bytes.len() < HEADER_SIZE + levels_bytes_len {
            return Err(TileError::Validation("tiles.idx missing level table".into()));
        }

        let entries_base = (HEADER_SIZE + levels_bytes_len) as u64;
        let entries_len = index_bytes.len() as u64 - entries_base;

        let mut levels = Vec::with_capacity(level_count);
        for i in 0..level_count {
            let base = HEADER_SIZE + i * LEVEL_SIZE;
            let level = u32::from_le_bytes(index_bytes[base..base + 4].try_into().unwrap());
            let cols = u32::from_le_bytes(index_bytes[base + 4..base + 8].try_into().unwrap());
            let rows = u32::from_le_bytes(index_bytes[base + 8..base + 12].try_into().unwrap());
            let entry_offset =
                u64::from_le_bytes(index_bytes[base + 12..base + 20].try_into().unwrap());

            let entry_count = (cols as u64).saturating_mul(rows as u64);
            let level_end = entry_offset + entry_count * ENTRY_SIZE as u64;
            if level_end > entries_len {
                return Err(TileError::Validation(format!(
                    "tiles.idx entry range out of bounds for level {}",
                    level
                )));
            }

            levels.push(PackLevel {
                level,
                cols,
                rows,
                entry_offset,
            });
        }

        Ok((levels, entries_base))
    }

    fn find_level(&self, level: u32) -> Option<&PackLevel> {
        self.levels.iter().find(|info| info.level == level)
    }

    pub fn tile_ref(&self, level: u32, col: u32, row: u32) -> Option<PackTileRef> {
        let info = self.find_level(level)?;
        if col >= info.cols || row >= info.rows {
            return None;
        }

        let idx = (row as u64).saturating_mul(info.cols as u64) + col as u64;
        let entry_offset = self.entries_base + info.entry_offset + idx * ENTRY_SIZE as u64;
        if entry_offset + ENTRY_SIZE as u64 > self.index_bytes.len() as u64 {
            return None;
        }

        let start = entry_offset as usize;
        let offset = u64::from_le_bytes(self.index_bytes[start..start + 8].try_into().unwrap());
        let length =
            u32::from_le_bytes(self.index_bytes[start + 8..start + 12].try_into().unwrap());

        if length == 0 {
            return None;
        }

        Some(PackTileRef { offset, length })
    }

    pub fn read_tile_bytes(&self, tile_ref: PackTileRef) -> TileResult<Bytes> {
        if tile_ref.length == 0 {
            return Err(TileError::Validation("zero-length tile".into()));
        }

        let end = tile_ref
            .offset
            .checked_add(tile_ref.length as u64)
            .ok_or_else(|| TileError::Validation("tile offset overflow".into()))?;
        if end > self.pack_len {
            return Err(TileError::Validation(
                "tile byte range exceeds pack size".into(),
            ));
        }

        let mut buf = vec![0u8; tile_ref.length as usize];
        read_at(&self.pack, tile_ref.offset, &mut buf)?;
        Ok(Bytes::from(buf))
    }
}

#[cfg(windows)]
fn read_at(file: &File, offset: u64, buf: &mut [u8]) -> std::io::Result<()> {
    use std::os::windows::fs::FileExt;
    file.seek_read(buf, offset)?;
    Ok(())
}

#[cfg(unix)]
fn read_at(file: &File, offset: u64, buf: &mut [u8]) -> std::io::Result<()> {
    use std::os::unix::fs::FileExt;
    file.read_at(buf, offset)?;
    Ok(())
}
