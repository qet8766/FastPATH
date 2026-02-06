//! Packed tile reader for .fastpath directories (pack_v2).

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::path::Path;
use std::sync::atomic::{AtomicU32, Ordering};

use bytes::Bytes;
use rayon::prelude::*;

use crate::error::{TileError, TileResult};

const LEVEL_MAGIC: &[u8; 8] = b"FPLIDX1\0";
const LEVEL_VERSION: u32 = 1;
const LEVEL_HEADER_SIZE: usize = 16;
const LEVEL_ENTRY_SIZE: usize = 12;

#[derive(Debug, Clone, Copy)]
struct TileEntry {
    offset: u64,
    length: u32,
}

#[derive(Debug)]
struct LevelPack {
    level: u32,
    cols: u32,
    rows: u32,
    entries: Vec<TileEntry>,
    pack: File,
    pack_len: u64,
}

impl LevelPack {
    fn parse(level: u32, idx_bytes: &[u8], pack: File, pack_len: u64) -> TileResult<Self> {
        if idx_bytes.len() < LEVEL_HEADER_SIZE {
            return Err(TileError::Validation(format!(
                "level_{}.idx is too small",
                level
            )));
        }

        let magic = &idx_bytes[0..8];
        if magic != LEVEL_MAGIC {
            return Err(TileError::Validation(format!(
                "level_{}.idx magic mismatch",
                level
            )));
        }

        let version = u32::from_le_bytes(idx_bytes[8..12].try_into().unwrap());
        if version != LEVEL_VERSION {
            return Err(TileError::Validation(format!(
                "Unsupported level_{}.idx version: {}",
                level, version
            )));
        }

        let cols = u16::from_le_bytes(idx_bytes[12..14].try_into().unwrap()) as u32;
        let rows = u16::from_le_bytes(idx_bytes[14..16].try_into().unwrap()) as u32;
        if cols == 0 || rows == 0 {
            return Err(TileError::Validation(format!(
                "level_{}.idx has zero cols/rows",
                level
            )));
        }

        let entry_count = (cols as u64).saturating_mul(rows as u64);
        let entries_bytes = entry_count
            .checked_mul(LEVEL_ENTRY_SIZE as u64)
            .ok_or_else(|| {
                TileError::Validation(format!("level_{}.idx entry table overflow", level))
            })?;
        let expected_len = LEVEL_HEADER_SIZE as u64 + entries_bytes;
        if (idx_bytes.len() as u64) < expected_len {
            return Err(TileError::Validation(format!(
                "level_{}.idx missing entry table",
                level
            )));
        }

        let mut entries = Vec::with_capacity(entry_count as usize);
        let mut cursor = LEVEL_HEADER_SIZE;
        for _ in 0..entry_count {
            let offset = u64::from_le_bytes(idx_bytes[cursor..cursor + 8].try_into().unwrap());
            let length =
                u32::from_le_bytes(idx_bytes[cursor + 8..cursor + 12].try_into().unwrap());
            entries.push(TileEntry { offset, length });
            cursor += LEVEL_ENTRY_SIZE;
        }

        Ok(Self {
            level,
            cols,
            rows,
            entries,
            pack,
            pack_len,
        })
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PackTileRef {
    pub level: u32,
    pub offset: u64,
    pub length: u32,
}

#[derive(Debug)]
pub struct TilePack {
    levels: Vec<LevelPack>,
}

impl TilePack {
    pub fn open(fastpath_dir: &Path) -> TileResult<Self> {
        let tiles_dir = fastpath_dir.join("tiles");
        if !tiles_dir.exists() {
            return Err(TileError::Validation(format!(
                "Missing tiles directory: {}",
                tiles_dir.display()
            )));
        }

        let mut levels = Vec::new();
        for entry in std::fs::read_dir(&tiles_dir)? {
            let entry = entry?;
            if !entry.file_type()?.is_file() {
                continue;
            }

            let name = entry.file_name();
            let name = name.to_string_lossy();
            let Some(level_str) = name
                .strip_prefix("level_")
                .and_then(|s| s.strip_suffix(".idx"))
            else {
                continue;
            };

            let level: u32 = level_str.parse().map_err(|_| {
                TileError::Validation(format!("Invalid level index: {}", level_str))
            })?;

            let idx_bytes = std::fs::read(entry.path())?;
            let pack_path = tiles_dir.join(format!("level_{}.pack", level));
            let pack = File::open(&pack_path)?;
            let pack_len = pack.metadata()?.len();

            let level_pack = LevelPack::parse(level, &idx_bytes, pack, pack_len)?;
            levels.push(level_pack);
        }

        if levels.is_empty() {
            return Err(TileError::Validation(
                "No level index files found in tiles/".into(),
            ));
        }

        levels.sort_by_key(|l| l.level);
        for i in 1..levels.len() {
            if levels[i].level == levels[i - 1].level {
                return Err(TileError::Validation(format!(
                    "Duplicate level index: {}",
                    levels[i].level
                )));
            }
        }
        Ok(Self { levels })
    }

    fn find_level(&self, level: u32) -> Option<&LevelPack> {
        self.levels.iter().find(|info| info.level == level)
    }

    pub fn tile_ref(&self, level: u32, col: u32, row: u32) -> Option<PackTileRef> {
        let info = self.find_level(level)?;
        if col >= info.cols || row >= info.rows {
            return None;
        }

        let idx = (row as u64).saturating_mul(info.cols as u64) + col as u64;
        let entry = info.entries.get(idx as usize)?;
        if entry.length == 0 {
            return None;
        }

        Some(PackTileRef {
            level,
            offset: entry.offset,
            length: entry.length,
        })
    }

    pub fn read_tile_bytes(&self, tile_ref: PackTileRef) -> TileResult<Bytes> {
        if tile_ref.length == 0 {
            return Err(TileError::Validation("zero-length tile".into()));
        }

        let level = self.find_level(tile_ref.level).ok_or_else(|| {
            TileError::Validation(format!("Unknown level {}", tile_ref.level))
        })?;

        let end = tile_ref
            .offset
            .checked_add(tile_ref.length as u64)
            .ok_or_else(|| TileError::Validation("tile offset overflow".into()))?;
        if end > level.pack_len {
            return Err(TileError::Validation(
                "tile byte range exceeds pack size".into(),
            ));
        }

        let mut buf = vec![0u8; tile_ref.length as usize];
        read_at(&level.pack, tile_ref.offset, &mut buf)?;
        Ok(Bytes::from(buf))
    }
}

/// Pack dzsave output (tiles_files) into per-level tiles/level_N.pack + level_N.idx
/// and remove dzsave files.
///
/// The dzsave layout is expected to be:
/// `fastpath_dir/tiles_files/<level>/<col>_<row>.jpg` (or `.jpeg`).
///
/// Missing tiles are written as zero-length entries.
pub fn pack_dzsave_tiles(
    fastpath_dir: &Path,
    levels: &[(u32, u32, u32)],
    progress_cb: Option<Box<dyn Fn(u32, u32) + Send + Sync>>,
) -> TileResult<()> {
    let tiles_dir = fastpath_dir.join("tiles_files");
    if !tiles_dir.exists() {
        return Err(TileError::Validation(format!(
            "Missing dzsave tiles at {}",
            tiles_dir.display()
        )));
    }

    let out_dir = fastpath_dir.join("tiles");
    std::fs::create_dir_all(&out_dir)?;

    let total_levels = levels.len() as u32;
    let completed = AtomicU32::new(0);

    levels.par_iter().try_for_each(|(level, cols, rows)| -> TileResult<()> {
        let level_dir = tiles_dir.join(level.to_string());
        if !level_dir.exists() {
            return Err(TileError::Validation(format!(
                "Missing level directory: {}",
                level_dir.display()
            )));
        }

        let cols_u16 = u16::try_from(*cols).map_err(|_| {
            TileError::Validation(format!("level {} cols exceeds u16: {}", level, cols))
        })?;
        let rows_u16 = u16::try_from(*rows).map_err(|_| {
            TileError::Validation(format!("level {} rows exceeds u16: {}", level, rows))
        })?;

        // One readdir per level instead of 2 * cols * rows stat calls
        let mut tile_files: HashMap<String, std::path::PathBuf> = HashMap::new();
        for entry in std::fs::read_dir(&level_dir)? {
            let entry = entry?;
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if let Some(stem) = name_str.strip_suffix(".jpg")
                .or_else(|| name_str.strip_suffix(".jpeg"))
            {
                tile_files.insert(stem.to_string(), entry.path());
            }
        }

        let pack_path = out_dir.join(format!("level_{}.pack", level));
        let idx_path = out_dir.join(format!("level_{}.idx", level));

        let pack_file = File::create(&pack_path)?;
        let idx_file = File::create(&idx_path)?;
        let mut pack_writer = BufWriter::new(pack_file);
        let mut idx_writer = BufWriter::new(idx_file);

        idx_writer.write_all(LEVEL_MAGIC)?;
        idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
        idx_writer.write_all(&cols_u16.to_le_bytes())?;
        idx_writer.write_all(&rows_u16.to_le_bytes())?;

        let mut pack_offset: u64 = 0;
        for row in 0..*rows {
            for col in 0..*cols {
                let key = format!("{}_{}", col, row);
                let tile_path = tile_files.get(&key);

                let Some(tile_path) = tile_path else {
                    idx_writer.write_all(&0u64.to_le_bytes())?;
                    idx_writer.write_all(&0u32.to_le_bytes())?;
                    continue;
                };

                let data = std::fs::read(tile_path)?;
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

                pack_offset = pack_offset
                    .checked_add(length as u64)
                    .ok_or_else(|| TileError::Validation("pack offset overflow".into()))?;
            }
        }

        idx_writer.flush()?;
        pack_writer.flush()?;

        let done = completed.fetch_add(1, Ordering::Relaxed) + 1;
        if let Some(ref cb) = progress_cb {
            cb(done, total_levels);
        }
        Ok(())
    })?;

    // Clean up dzsave output to save disk space.
    std::fs::remove_dir_all(&tiles_dir)?;
    let dzi_path = fastpath_dir.join("tiles.dzi");
    if dzi_path.exists() {
        std::fs::remove_file(&dzi_path)?;
    }

    Ok(())
}

/// Old sequential packing with per-tile stat calls (for benchmarking only).
/// Does NOT remove tiles_files or tiles.dzi (caller handles cleanup).
pub fn pack_dzsave_tiles_bench_seq_stat(
    fastpath_dir: &Path,
    levels: &[(u32, u32, u32)],
) -> TileResult<()> {
    let tiles_dir = fastpath_dir.join("tiles_files");
    let out_dir = fastpath_dir.join("tiles");
    std::fs::create_dir_all(&out_dir)?;

    for (level, cols, rows) in levels.iter() {
        let level_dir = tiles_dir.join(level.to_string());

        let cols_u16 = u16::try_from(*cols).map_err(|_| {
            TileError::Validation(format!("level {} cols exceeds u16: {}", level, cols))
        })?;
        let rows_u16 = u16::try_from(*rows).map_err(|_| {
            TileError::Validation(format!("level {} rows exceeds u16: {}", level, rows))
        })?;

        let pack_file = File::create(out_dir.join(format!("level_{}.pack", level)))?;
        let idx_file = File::create(out_dir.join(format!("level_{}.idx", level)))?;
        let mut pack_writer = BufWriter::new(pack_file);
        let mut idx_writer = BufWriter::new(idx_file);

        idx_writer.write_all(LEVEL_MAGIC)?;
        idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
        idx_writer.write_all(&cols_u16.to_le_bytes())?;
        idx_writer.write_all(&rows_u16.to_le_bytes())?;

        let mut pack_offset: u64 = 0;
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

                pack_offset = pack_offset
                    .checked_add(length as u64)
                    .ok_or_else(|| TileError::Validation("pack offset overflow".into()))?;
            }
        }

        idx_writer.flush()?;
        pack_writer.flush()?;
    }

    Ok(())
}

/// Sequential packing with directory pre-scan (for benchmarking only).
/// Does NOT remove tiles_files or tiles.dzi (caller handles cleanup).
pub fn pack_dzsave_tiles_bench_seq_prescan(
    fastpath_dir: &Path,
    levels: &[(u32, u32, u32)],
) -> TileResult<()> {
    let tiles_dir = fastpath_dir.join("tiles_files");
    let out_dir = fastpath_dir.join("tiles");
    std::fs::create_dir_all(&out_dir)?;

    for (level, cols, rows) in levels.iter() {
        let level_dir = tiles_dir.join(level.to_string());

        let cols_u16 = u16::try_from(*cols).map_err(|_| {
            TileError::Validation(format!("level {} cols exceeds u16: {}", level, cols))
        })?;
        let rows_u16 = u16::try_from(*rows).map_err(|_| {
            TileError::Validation(format!("level {} rows exceeds u16: {}", level, rows))
        })?;

        // Directory pre-scan
        let mut tile_files: HashMap<String, std::path::PathBuf> = HashMap::new();
        for entry in std::fs::read_dir(&level_dir)? {
            let entry = entry?;
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if let Some(stem) = name_str.strip_suffix(".jpg")
                .or_else(|| name_str.strip_suffix(".jpeg"))
            {
                tile_files.insert(stem.to_string(), entry.path());
            }
        }

        let pack_file = File::create(out_dir.join(format!("level_{}.pack", level)))?;
        let idx_file = File::create(out_dir.join(format!("level_{}.idx", level)))?;
        let mut pack_writer = BufWriter::new(pack_file);
        let mut idx_writer = BufWriter::new(idx_file);

        idx_writer.write_all(LEVEL_MAGIC)?;
        idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
        idx_writer.write_all(&cols_u16.to_le_bytes())?;
        idx_writer.write_all(&rows_u16.to_le_bytes())?;

        let mut pack_offset: u64 = 0;
        for row in 0..*rows {
            for col in 0..*cols {
                let key = format!("{}_{}", col, row);
                let tile_path = tile_files.get(&key);

                let Some(tile_path) = tile_path else {
                    idx_writer.write_all(&0u64.to_le_bytes())?;
                    idx_writer.write_all(&0u32.to_le_bytes())?;
                    continue;
                };

                let data = std::fs::read(tile_path)?;
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

                pack_offset = pack_offset
                    .checked_add(length as u64)
                    .ok_or_else(|| TileError::Validation("pack offset overflow".into()))?;
            }
        }

        idx_writer.flush()?;
        pack_writer.flush()?;
    }

    Ok(())
}

/// Parallel packing with prescan, without cleanup (for benchmarking only).
pub fn pack_dzsave_tiles_bench_parallel(
    fastpath_dir: &Path,
    levels: &[(u32, u32, u32)],
) -> TileResult<()> {
    let tiles_dir = fastpath_dir.join("tiles_files");
    let out_dir = fastpath_dir.join("tiles");
    std::fs::create_dir_all(&out_dir)?;

    levels.par_iter().try_for_each(|(level, cols, rows)| -> TileResult<()> {
        let level_dir = tiles_dir.join(level.to_string());

        let cols_u16 = u16::try_from(*cols).map_err(|_| {
            TileError::Validation(format!("level {} cols exceeds u16: {}", level, cols))
        })?;
        let rows_u16 = u16::try_from(*rows).map_err(|_| {
            TileError::Validation(format!("level {} rows exceeds u16: {}", level, rows))
        })?;

        let mut tile_files: HashMap<String, std::path::PathBuf> = HashMap::new();
        for entry in std::fs::read_dir(&level_dir)? {
            let entry = entry?;
            let name = entry.file_name();
            let name_str = name.to_string_lossy();
            if let Some(stem) = name_str.strip_suffix(".jpg")
                .or_else(|| name_str.strip_suffix(".jpeg"))
            {
                tile_files.insert(stem.to_string(), entry.path());
            }
        }

        let pack_file = File::create(out_dir.join(format!("level_{}.pack", level)))?;
        let idx_file = File::create(out_dir.join(format!("level_{}.idx", level)))?;
        let mut pack_writer = BufWriter::new(pack_file);
        let mut idx_writer = BufWriter::new(idx_file);

        idx_writer.write_all(LEVEL_MAGIC)?;
        idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
        idx_writer.write_all(&cols_u16.to_le_bytes())?;
        idx_writer.write_all(&rows_u16.to_le_bytes())?;

        let mut pack_offset: u64 = 0;
        for row in 0..*rows {
            for col in 0..*cols {
                let key = format!("{}_{}", col, row);
                let tile_path = tile_files.get(&key);

                let Some(tile_path) = tile_path else {
                    idx_writer.write_all(&0u64.to_le_bytes())?;
                    idx_writer.write_all(&0u32.to_le_bytes())?;
                    continue;
                };

                let data = std::fs::read(tile_path)?;
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

                pack_offset = pack_offset
                    .checked_add(length as u64)
                    .ok_or_else(|| TileError::Validation("pack offset overflow".into()))?;
            }
        }

        idx_writer.flush()?;
        pack_writer.flush()?;
        Ok(())
    })?;

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

        pack_dzsave_tiles(dir, &[(0, 2, 1), (1, 1, 1)], None).unwrap();

        assert!(!tiles_dir.exists(), "tiles_files should be removed");
        assert!(!dir.join("tiles.dzi").exists(), "tiles.dzi should be removed");
        assert!(dir.join("tiles").join("level_0.pack").exists());
        assert!(dir.join("tiles").join("level_0.idx").exists());
        assert!(dir.join("tiles").join("level_1.pack").exists());
        assert!(dir.join("tiles").join("level_1.idx").exists());

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

    /// Old sequential implementation (for benchmarking comparison).
    fn pack_dzsave_tiles_sequential(
        fastpath_dir: &Path,
        levels: &[(u32, u32, u32)],
    ) -> TileResult<()> {
        let tiles_dir = fastpath_dir.join("tiles_files");
        let out_dir = fastpath_dir.join("tiles");
        fs::create_dir_all(&out_dir)?;

        for (level, cols, rows) in levels.iter() {
            let level_dir = tiles_dir.join(level.to_string());

            let cols_u16 = u16::try_from(*cols).unwrap();
            let rows_u16 = u16::try_from(*rows).unwrap();

            let pack_path = out_dir.join(format!("level_{}.pack", level));
            let idx_path = out_dir.join(format!("level_{}.idx", level));

            let pack_file = File::create(&pack_path)?;
            let idx_file = File::create(&idx_path)?;
            let mut pack_writer = BufWriter::new(pack_file);
            let mut idx_writer = BufWriter::new(idx_file);

            idx_writer.write_all(LEVEL_MAGIC)?;
            idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
            idx_writer.write_all(&cols_u16.to_le_bytes())?;
            idx_writer.write_all(&rows_u16.to_le_bytes())?;

            let mut pack_offset: u64 = 0;
            for row in 0..*rows {
                for col in 0..*cols {
                    // Old approach: 2 stat calls per tile
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
                        continue;
                    };

                    let data = fs::read(&tile_path)?;
                    let length: u32 = data.len().try_into().unwrap();

                    pack_writer.write_all(&data)?;
                    idx_writer.write_all(&pack_offset.to_le_bytes())?;
                    idx_writer.write_all(&length.to_le_bytes())?;
                    pack_offset += length as u64;
                }
            }

            idx_writer.flush()?;
            pack_writer.flush()?;
        }

        Ok(())
    }

    /// Old sequential implementation with per-tile stat calls (no prescan).
    fn pack_dzsave_tiles_seq_stat(
        fastpath_dir: &Path,
        levels: &[(u32, u32, u32)],
    ) -> TileResult<()> {
        let tiles_dir = fastpath_dir.join("tiles_files");
        let out_dir = fastpath_dir.join("tiles");
        fs::create_dir_all(&out_dir)?;

        for (level, cols, rows) in levels.iter() {
            let level_dir = tiles_dir.join(level.to_string());

            let cols_u16 = u16::try_from(*cols).unwrap();
            let rows_u16 = u16::try_from(*rows).unwrap();

            let pack_path = out_dir.join(format!("level_{}.pack", level));
            let idx_path = out_dir.join(format!("level_{}.idx", level));

            let pack_file = File::create(&pack_path)?;
            let idx_file = File::create(&idx_path)?;
            let mut pack_writer = BufWriter::new(pack_file);
            let mut idx_writer = BufWriter::new(idx_file);

            idx_writer.write_all(LEVEL_MAGIC)?;
            idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
            idx_writer.write_all(&cols_u16.to_le_bytes())?;
            idx_writer.write_all(&rows_u16.to_le_bytes())?;

            let mut pack_offset: u64 = 0;
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
                        continue;
                    };

                    let data = fs::read(&tile_path)?;
                    let length: u32 = data.len().try_into().unwrap();

                    pack_writer.write_all(&data)?;
                    idx_writer.write_all(&pack_offset.to_le_bytes())?;
                    idx_writer.write_all(&length.to_le_bytes())?;
                    pack_offset += length as u64;
                }
            }

            idx_writer.flush()?;
            pack_writer.flush()?;
        }

        Ok(())
    }

    /// Sequential with directory pre-scan (isolates prescan improvement).
    fn pack_dzsave_tiles_seq_prescan(
        fastpath_dir: &Path,
        levels: &[(u32, u32, u32)],
    ) -> TileResult<()> {
        let tiles_dir = fastpath_dir.join("tiles_files");
        let out_dir = fastpath_dir.join("tiles");
        fs::create_dir_all(&out_dir)?;

        for (level, cols, rows) in levels.iter() {
            let level_dir = tiles_dir.join(level.to_string());

            let cols_u16 = u16::try_from(*cols).unwrap();
            let rows_u16 = u16::try_from(*rows).unwrap();

            let mut tile_files: HashMap<String, std::path::PathBuf> = HashMap::new();
            for entry in fs::read_dir(&level_dir)? {
                let entry = entry?;
                let name = entry.file_name();
                let name_str = name.to_string_lossy();
                if let Some(stem) = name_str.strip_suffix(".jpg")
                    .or_else(|| name_str.strip_suffix(".jpeg"))
                {
                    tile_files.insert(stem.to_string(), entry.path());
                }
            }

            let pack_path = out_dir.join(format!("level_{}.pack", level));
            let idx_path = out_dir.join(format!("level_{}.idx", level));

            let pack_file = File::create(&pack_path)?;
            let idx_file = File::create(&idx_path)?;
            let mut pack_writer = BufWriter::new(pack_file);
            let mut idx_writer = BufWriter::new(idx_file);

            idx_writer.write_all(LEVEL_MAGIC)?;
            idx_writer.write_all(&LEVEL_VERSION.to_le_bytes())?;
            idx_writer.write_all(&cols_u16.to_le_bytes())?;
            idx_writer.write_all(&rows_u16.to_le_bytes())?;

            let mut pack_offset: u64 = 0;
            for row in 0..*rows {
                for col in 0..*cols {
                    let key = format!("{}_{}", col, row);
                    let tile_path = tile_files.get(&key);

                    let Some(tile_path) = tile_path else {
                        idx_writer.write_all(&0u64.to_le_bytes())?;
                        idx_writer.write_all(&0u32.to_le_bytes())?;
                        continue;
                    };

                    let data = fs::read(tile_path)?;
                    let length: u32 = data.len().try_into().unwrap();

                    pack_writer.write_all(&data)?;
                    idx_writer.write_all(&pack_offset.to_le_bytes())?;
                    idx_writer.write_all(&length.to_le_bytes())?;
                    pack_offset += length as u64;
                }
            }

            idx_writer.flush()?;
            pack_writer.flush()?;
        }

        Ok(())
    }

    /// Helper: create a tiles_files directory tree mimicking dzsave output.
    /// `tile_size_bytes` controls the tile payload size (real tiles are ~20-50KB).
    fn create_bench_tiles(
        num_levels: u32,
        tiles_per_side: u32,
        tile_size_bytes: usize,
    ) -> (TempDir, Vec<(u32, u32, u32)>) {
        let temp = TempDir::new().unwrap();
        let dir = temp.path();
        let tiles_dir = dir.join("tiles_files");

        // Build a fake tile payload of the desired size (pad JPEG header with zeros)
        let jpeg_header = test_jpeg_bytes();
        let tile_data = if tile_size_bytes > jpeg_header.len() {
            let mut data = jpeg_header;
            data.resize(tile_size_bytes, 0u8);
            data
        } else {
            jpeg_header
        };

        let mut levels = Vec::new();

        for level in 0..num_levels {
            let side = (tiles_per_side >> level).max(1);
            let level_dir = tiles_dir.join(level.to_string());
            fs::create_dir_all(&level_dir).unwrap();

            for row in 0..side {
                for col in 0..side {
                    fs::write(level_dir.join(format!("{}_{}.jpg", col, row)), &tile_data).unwrap();
                }
            }

            levels.push((level, side, side));
        }

        (temp, levels)
    }

    #[test]
    fn bench_sequential_vs_parallel() {
        use std::time::Instant;

        const NUM_LEVELS: u32 = 12;
        const TILES_PER_SIDE: u32 = 64; // 64x64 = 4096 tiles at highest level
        const TILE_SIZE: usize = 30_000; // ~30KB, realistic Q80 JPEG 512x512
        const RUNS: u32 = 3;

        let mut seq_stat_times = Vec::new();
        let mut seq_prescan_times = Vec::new();
        let mut par_times = Vec::new();

        for run in 0..RUNS {
            // --- Old: sequential + per-tile stat ---
            let (temp, levels) = create_bench_tiles(NUM_LEVELS, TILES_PER_SIDE, TILE_SIZE);
            let start = Instant::now();
            pack_dzsave_tiles_seq_stat(temp.path(), &levels).unwrap();
            let elapsed = start.elapsed();
            seq_stat_times.push(elapsed);
            let seq_stat_ms = elapsed.as_secs_f64() * 1000.0;

            // --- Sequential + prescan (isolates prescan improvement) ---
            let (temp, levels) = create_bench_tiles(NUM_LEVELS, TILES_PER_SIDE, TILE_SIZE);
            let start = Instant::now();
            pack_dzsave_tiles_seq_prescan(temp.path(), &levels).unwrap();
            let elapsed = start.elapsed();
            seq_prescan_times.push(elapsed);
            let seq_prescan_ms = elapsed.as_secs_f64() * 1000.0;

            // --- New: parallel + prescan ---
            let (temp, levels) = create_bench_tiles(NUM_LEVELS, TILES_PER_SIDE, TILE_SIZE);
            let start = Instant::now();
            pack_dzsave_tiles(temp.path(), &levels, None).unwrap();
            let elapsed = start.elapsed();
            par_times.push(elapsed);
            let par_ms = elapsed.as_secs_f64() * 1000.0;

            eprintln!(
                "[BENCH run {}] seq+stat: {:.0}ms, seq+prescan: {:.0}ms, parallel: {:.0}ms",
                run + 1, seq_stat_ms, seq_prescan_ms, par_ms,
            );
        }

        let total_tiles: u32 = (0..NUM_LEVELS).map(|l| {
            let side = (TILES_PER_SIDE >> l).max(1);
            side * side
        }).sum();
        let total_bytes = total_tiles as u64 * TILE_SIZE as u64;

        let avg = |v: &[std::time::Duration]| -> f64 {
            v.iter().map(|t| t.as_secs_f64()).sum::<f64>() / v.len() as f64
        };

        let avg_seq_stat = avg(&seq_stat_times);
        let avg_seq_prescan = avg(&seq_prescan_times);
        let avg_par = avg(&par_times);

        eprintln!("\n[BENCH] {NUM_LEVELS} levels, {total_tiles} tiles, {:.0}MB data",
            total_bytes as f64 / 1_048_576.0);
        eprintln!("[BENCH] avg seq+stat:    {:.0}ms", avg_seq_stat * 1000.0);
        eprintln!("[BENCH] avg seq+prescan: {:.0}ms  ({:.2}x vs stat)",
            avg_seq_prescan * 1000.0, avg_seq_stat / avg_seq_prescan);
        eprintln!("[BENCH] avg parallel:    {:.0}ms  ({:.2}x vs stat)",
            avg_par * 1000.0, avg_seq_stat / avg_par);
    }
}
