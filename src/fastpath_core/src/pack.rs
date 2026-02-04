//! Packed tile reader for .fastpath directories.

use std::fs::File;
use std::io::{BufWriter, Write};
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

/// Pack dzsave output (tiles_files) into tiles.pack/tiles.idx and remove dzsave files.
///
/// The dzsave layout is expected to be:
/// `fastpath_dir/tiles_files/<level>/<col>_<row>.jpg` (or `.jpeg`).
///
/// Missing tiles are written as zero-length entries, matching the Python packer behavior.
pub fn pack_dzsave_tiles(fastpath_dir: &Path, levels: &[(u32, u32, u32)]) -> TileResult<()> {
    let tiles_dir = fastpath_dir.join("tiles_files");
    if !tiles_dir.exists() {
        return Err(TileError::Validation(format!(
            "Missing dzsave tiles at {}",
            tiles_dir.display()
        )));
    }

    let pack_path = fastpath_dir.join("tiles.pack");
    let idx_path = fastpath_dir.join("tiles.idx");

    let pack_file = File::create(&pack_path)?;
    let idx_file = File::create(&idx_path)?;
    let mut pack_writer = BufWriter::new(pack_file);
    let mut idx_writer = BufWriter::new(idx_file);

    idx_writer.write_all(MAGIC)?;
    idx_writer.write_all(&VERSION.to_le_bytes())?;
    idx_writer.write_all(&(levels.len() as u32).to_le_bytes())?;

    // Level table: entry_offset is relative to entries section (after header + level table).
    let mut entry_offset: u64 = 0;
    for (level, cols, rows) in levels {
        idx_writer.write_all(&level.to_le_bytes())?;
        idx_writer.write_all(&cols.to_le_bytes())?;
        idx_writer.write_all(&rows.to_le_bytes())?;
        idx_writer.write_all(&entry_offset.to_le_bytes())?;

        let entry_count = (*cols as u64).saturating_mul(*rows as u64);
        let level_bytes = entry_count
            .checked_mul(ENTRY_SIZE as u64)
            .ok_or_else(|| TileError::Validation("tiles.idx entry table overflow".into()))?;
        entry_offset = entry_offset
            .checked_add(level_bytes)
            .ok_or_else(|| TileError::Validation("tiles.idx entry_offset overflow".into()))?;
    }

    // Entry table + packed bytes.
    let mut pack_offset: u64 = 0;
    for (level, cols, rows) in levels {
        let level_dir = tiles_dir.join(level.to_string());
        if !level_dir.exists() {
            return Err(TileError::Validation(format!(
                "Missing level directory: {}",
                level_dir.display()
            )));
        }

        for row in 0..*rows {
            for col in 0..*cols {
                let jpg = level_dir.join(format!("{}_{}.jpg", col, row));
                let jpeg = level_dir.join(format!("{}_{}.jpeg", col, row));

                let tile_path = if jpg.exists() {
                    Some(jpg)
                } else if jpeg.exists() {
                    Some(jpeg)
                } else {
                    None
                };

                let Some(tile_path) = tile_path else {
                    idx_writer.write_all(&0u64.to_le_bytes())?;
                    idx_writer.write_all(&0u32.to_le_bytes())?;
                    idx_writer.write_all(&0u32.to_le_bytes())?;
                    continue;
                };

                let data = std::fs::read(&tile_path)?;
                let length: u32 = data.len().try_into().map_err(|_e| {
                    TileError::Validation(format!(
                        "Tile too large to pack ({} bytes): {}",
                        data.len(),
                        tile_path.display()
                    ))
                })?;

                pack_writer.write_all(&data)?;

                idx_writer.write_all(&pack_offset.to_le_bytes())?;
                idx_writer.write_all(&length.to_le_bytes())?;
                idx_writer.write_all(&0u32.to_le_bytes())?;

                pack_offset = pack_offset
                    .checked_add(length as u64)
                    .ok_or_else(|| TileError::Validation("tiles.pack offset overflow".into()))?;
            }
        }
    }

    idx_writer.flush()?;
    pack_writer.flush()?;

    // Clean up dzsave output to save disk space.
    std::fs::remove_dir_all(&tiles_dir)?;
    let dzi_path = fastpath_dir.join("tiles.dzi");
    if dzi_path.exists() {
        std::fs::remove_file(&dzi_path)?;
    }

    Ok(())
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

#[cfg(test)]
mod tests {
    use std::fs;

    use tempfile::TempDir;

    use super::*;
    use crate::test_utils::test_jpeg_bytes;

    #[test]
    fn test_pack_dzsave_tiles_writes_pack_and_cleans_up() {
        let temp = TempDir::new().unwrap();
        let dir = temp.path();

        let tiles_dir = dir.join("tiles_files");
        fs::create_dir_all(tiles_dir.join("0")).unwrap();
        fs::create_dir_all(tiles_dir.join("1")).unwrap();

        let jpeg = test_jpeg_bytes();
        // Present tile with .jpg extension
        fs::write(tiles_dir.join("0").join("0_0.jpg"), &jpeg).unwrap();
        // Present tile with .jpeg extension (fallback path)
        fs::write(tiles_dir.join("1").join("0_0.jpeg"), &jpeg).unwrap();
        // Missing tile: 0/1_0.jpg is intentionally absent

        fs::write(dir.join("tiles.dzi"), b"dummy").unwrap();

        pack_dzsave_tiles(dir, &[(0, 2, 1), (1, 1, 1)]).unwrap();

        assert!(!tiles_dir.exists(), "tiles_files should be removed");
        assert!(!dir.join("tiles.dzi").exists(), "tiles.dzi should be removed");
        assert!(dir.join("tiles.pack").exists());
        assert!(dir.join("tiles.idx").exists());

        let pack = TilePack::open(dir).unwrap();

        // Present .jpg tile
        let t0 = pack.tile_ref(0, 0, 0).unwrap();
        let b0 = pack.read_tile_bytes(t0).unwrap();
        assert_eq!(b0.as_ref(), jpeg.as_slice());

        // Missing tile should be encoded as a zero-length entry (tile_ref == None).
        assert!(pack.tile_ref(0, 1, 0).is_none());

        // Present .jpeg tile
        let t1 = pack.tile_ref(1, 0, 0).unwrap();
        let b1 = pack.read_tile_bytes(t1).unwrap();
        assert_eq!(b1.as_ref(), jpeg.as_slice());
    }
}
