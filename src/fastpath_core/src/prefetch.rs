//! Viewport-based tile prefetching.

use crate::cache::TileCoord;
use crate::format::{LevelInfo, SlideMetadata};

/// Viewport state for prefetch calculations.
#[derive(Debug, Clone, Copy, Default)]
pub struct Viewport {
    /// Left edge in slide coordinates.
    pub x: f64,
    /// Top edge in slide coordinates.
    pub y: f64,
    /// Width in slide coordinates.
    pub width: f64,
    /// Height in slide coordinates.
    pub height: f64,
    /// Current scale (1.0 = full resolution).
    pub scale: f64,
    /// Horizontal velocity (pixels per second).
    pub velocity_x: f64,
    /// Vertical velocity (pixels per second).
    pub velocity_y: f64,
}

impl Viewport {
    pub fn new(
        x: f64,
        y: f64,
        width: f64,
        height: f64,
        scale: f64,
        velocity_x: f64,
        velocity_y: f64,
    ) -> Self {
        Self {
            x,
            y,
            width,
            height,
            scale,
            velocity_x,
            velocity_y,
        }
    }
}

/// Configuration for prefetching behavior.
#[derive(Debug, Clone)]
pub struct PrefetchConfig {
    /// Number of tiles to prefetch ahead in movement direction.
    pub tiles_ahead: u32,
    /// Number of tiles to prefetch in perpendicular directions.
    pub tiles_around: u32,
    /// Whether to prefetch adjacent pyramid levels.
    pub prefetch_levels: bool,
    /// Minimum velocity to trigger directional prefetch.
    pub min_velocity: f64,
}

impl Default for PrefetchConfig {
    fn default() -> Self {
        Self {
            tiles_ahead: 2,
            tiles_around: 1,
            prefetch_levels: true,
            min_velocity: 50.0, // pixels per second
        }
    }
}

/// Prefetch calculator.
pub struct PrefetchCalculator {
    config: PrefetchConfig,
}

impl PrefetchCalculator {
    pub fn new(config: PrefetchConfig) -> Self {
        Self { config }
    }

    /// Get the best pyramid level for a given scale.
    ///
    /// Biases toward higher resolution by picking the level with downsample <= target.
    /// This ensures crisp display (GPU downscaling looks better than upscaling).
    pub fn level_for_scale(&self, metadata: &SlideMetadata, scale: f64) -> u32 {
        let target_downsample = 1.0 / scale;

        // Find highest resolution level (lowest downsample) where downsample <= target.
        // Among qualifying levels, pick the one with highest level number (most efficient
        // while still meeting resolution requirement).
        metadata
            .levels
            .iter()
            .filter(|l| (l.downsample as f64) <= target_downsample)
            .max_by_key(|l| l.level)
            .map(|l| l.level)
            .unwrap_or(0) // Default to level 0 (highest resolution) if none qualify
    }

    /// Calculate tiles visible in the current viewport.
    pub fn visible_tiles(
        &self,
        metadata: &SlideMetadata,
        viewport: &Viewport,
    ) -> Vec<TileCoord> {
        let level = self.level_for_scale(metadata, viewport.scale);

        if let Some(level_info) = metadata.get_level(level) {
            self.tiles_in_rect(
                metadata.tile_size,
                level_info,
                viewport.x,
                viewport.y,
                viewport.width,
                viewport.height,
            )
        } else {
            Vec::new()
        }
    }

    /// Calculate tiles to prefetch based on viewport and velocity.
    ///
    /// Returns tiles ordered by priority (highest first).
    pub fn prefetch_tiles(
        &self,
        metadata: &SlideMetadata,
        viewport: &Viewport,
        cached: &impl Fn(&TileCoord) -> bool,
    ) -> Vec<TileCoord> {
        let mut tiles = Vec::new();
        let level = self.level_for_scale(metadata, viewport.scale);

        // Get visible tiles first (highest priority)
        let visible = self.visible_tiles(metadata, viewport);

        // Calculate extended viewport based on velocity
        let (ext_x, ext_y, ext_w, ext_h) = self.extended_viewport(viewport, metadata.tile_size);

        if let Some(level_info) = metadata.get_level(level) {
            // Add tiles from extended viewport (based on velocity)
            let extended_tiles = self.tiles_in_rect(
                metadata.tile_size,
                level_info,
                ext_x,
                ext_y,
                ext_w,
                ext_h,
            );

            // Prioritize: visible tiles first, then extended
            for coord in visible {
                if !cached(&coord) {
                    tiles.push(coord);
                }
            }

            for coord in extended_tiles {
                if !tiles.contains(&coord) && !cached(&coord) {
                    tiles.push(coord);
                }
            }

            // Optionally prefetch adjacent pyramid levels
            if self.config.prefetch_levels {
                // Prefetch one level up (lower resolution) for zooming out
                if level + 1 < metadata.num_levels() as u32 {
                    if let Some(up_level) = metadata.get_level(level + 1) {
                        let up_tiles = self.tiles_in_rect(
                            metadata.tile_size,
                            up_level,
                            viewport.x,
                            viewport.y,
                            viewport.width,
                            viewport.height,
                        );
                        for coord in up_tiles {
                            if !tiles.contains(&coord) && !cached(&coord) {
                                tiles.push(coord);
                            }
                        }
                    }
                }

                // Prefetch one level down (higher resolution) for zooming in
                if level > 0 {
                    if let Some(down_level) = metadata.get_level(level - 1) {
                        // Only prefetch center tiles at higher resolution
                        let center_x = viewport.x + viewport.width / 2.0;
                        let center_y = viewport.y + viewport.height / 2.0;
                        let small_width = viewport.width / 4.0;
                        let small_height = viewport.height / 4.0;

                        let down_tiles = self.tiles_in_rect(
                            metadata.tile_size,
                            down_level,
                            center_x - small_width / 2.0,
                            center_y - small_height / 2.0,
                            small_width,
                            small_height,
                        );
                        for coord in down_tiles {
                            if !tiles.contains(&coord) && !cached(&coord) {
                                tiles.push(coord);
                            }
                        }
                    }
                }
            }
        }

        tiles
    }

    /// Calculate extended viewport based on velocity.
    fn extended_viewport(
        &self,
        viewport: &Viewport,
        tile_size: u32,
    ) -> (f64, f64, f64, f64) {
        let tile_size = tile_size as f64;
        let tiles_ahead = self.config.tiles_ahead as f64;

        // Base extension around viewport
        let base_ext = tile_size * (self.config.tiles_around as f64);

        // Velocity-based extension
        let (vel_ext_x, vel_ext_y) = if viewport.velocity_x.abs() > self.config.min_velocity
            || viewport.velocity_y.abs() > self.config.min_velocity
        {
            // Extend in direction of movement
            let ext_x = if viewport.velocity_x.abs() > self.config.min_velocity {
                viewport.velocity_x.signum() * tile_size * tiles_ahead
            } else {
                0.0
            };

            let ext_y = if viewport.velocity_y.abs() > self.config.min_velocity {
                viewport.velocity_y.signum() * tile_size * tiles_ahead
            } else {
                0.0
            };

            (ext_x, ext_y)
        } else {
            (0.0, 0.0)
        };

        // Calculate extended rectangle
        let x = viewport.x - base_ext + vel_ext_x.min(0.0);
        let y = viewport.y - base_ext + vel_ext_y.min(0.0);
        let w = viewport.width + base_ext * 2.0 + vel_ext_x.abs();
        let h = viewport.height + base_ext * 2.0 + vel_ext_y.abs();

        (x, y, w, h)
    }

    /// Get tiles that intersect a rectangle.
    fn tiles_in_rect(
        &self,
        tile_size: u32,
        level_info: &LevelInfo,
        x: f64,
        y: f64,
        width: f64,
        height: f64,
    ) -> Vec<TileCoord> {
        let level_tile_size = (tile_size * level_info.downsample) as f64;

        let col_start = ((x / level_tile_size).floor() as i32).max(0) as u32;
        let col_end = (((x + width) / level_tile_size).ceil() as u32).min(level_info.cols);
        let row_start = ((y / level_tile_size).floor() as i32).max(0) as u32;
        let row_end = (((y + height) / level_tile_size).ceil() as u32).min(level_info.rows);

        let mut tiles = Vec::with_capacity(
            ((col_end - col_start) * (row_end - row_start)) as usize,
        );

        for row in row_start..row_end {
            for col in col_start..col_end {
                tiles.push(TileCoord::new(level_info.level, col, row));
            }
        }

        tiles
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_metadata() -> SlideMetadata {
        SlideMetadata {
            dimensions: (10000, 10000),
            tile_size: 512,
            levels: vec![
                LevelInfo {
                    level: 0,
                    downsample: 1,
                    cols: 20,
                    rows: 20,
                },
                LevelInfo {
                    level: 1,
                    downsample: 2,
                    cols: 10,
                    rows: 10,
                },
                LevelInfo {
                    level: 2,
                    downsample: 4,
                    cols: 5,
                    rows: 5,
                },
            ],
            target_mpp: 0.5,
            target_magnification: 20.0,
            tile_format: String::new(),
            source_file: String::new(),
        }
    }

    #[test]
    fn test_level_for_scale() {
        let calc = PrefetchCalculator::new(PrefetchConfig::default());
        let metadata = test_metadata();

        // Exact boundary cases
        assert_eq!(calc.level_for_scale(&metadata, 1.0), 0);
        assert_eq!(calc.level_for_scale(&metadata, 0.5), 1);
        assert_eq!(calc.level_for_scale(&metadata, 0.25), 2);

        // Intermediate scales should bias toward higher resolution (lower level number)
        // scale 0.6 → target_downsample=1.67 → only level 0 (ds=1) qualifies
        assert_eq!(calc.level_for_scale(&metadata, 0.6), 0);
        // scale 0.3 → target_downsample=3.33 → levels 0,1 qualify → pick level 1
        assert_eq!(calc.level_for_scale(&metadata, 0.3), 1);
        // scale 0.75 → target_downsample=1.33 → only level 0 qualifies
        assert_eq!(calc.level_for_scale(&metadata, 0.75), 0);
    }

    #[test]
    fn test_visible_tiles() {
        let calc = PrefetchCalculator::new(PrefetchConfig::default());
        let metadata = test_metadata();

        let viewport = Viewport::new(0.0, 0.0, 1024.0, 1024.0, 1.0, 0.0, 0.0);
        let tiles = calc.visible_tiles(&metadata, &viewport);

        // 1024 / 512 = 2 tiles in each direction, ceil'd to handle partial tiles
        assert!(!tiles.is_empty());
        assert!(tiles.iter().all(|t| t.level == 0));
    }

    #[test]
    fn test_prefetch_with_velocity() {
        let calc = PrefetchCalculator::new(PrefetchConfig {
            tiles_ahead: 2,
            tiles_around: 1,
            prefetch_levels: false,
            min_velocity: 50.0,
        });
        let metadata = test_metadata();

        // Moving right
        let viewport = Viewport::new(0.0, 0.0, 1024.0, 1024.0, 1.0, 100.0, 0.0);

        let tiles = calc.prefetch_tiles(&metadata, &viewport, &|_| false);

        // Should have more tiles to the right due to velocity
        assert!(!tiles.is_empty());
    }

    #[test]
    fn test_prefetch_filters_cached() {
        let calc = PrefetchCalculator::new(PrefetchConfig {
            prefetch_levels: false,
            ..Default::default()
        });
        let metadata = test_metadata();
        let viewport = Viewport::new(0.0, 0.0, 512.0, 512.0, 1.0, 0.0, 0.0);

        // All tiles cached
        let tiles = calc.prefetch_tiles(&metadata, &viewport, &|_| true);
        assert!(tiles.is_empty());

        // No tiles cached
        let tiles = calc.prefetch_tiles(&metadata, &viewport, &|_| false);
        assert!(!tiles.is_empty());
    }
}
