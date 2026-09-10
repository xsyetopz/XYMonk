use bytemuck::{Pod, Zeroable};
use num_traits::ToPrimitive;

use super::artwork::TextureSlot;

/// Visible artwork dimensions after cropping the three-pixel right border.
pub(super) const SOURCE_SIZE: (u32, u32) = (357, 510);
/// Width of the source artwork coordinate space.
pub(super) const SOURCE_WIDTH: f32 = 357.0;
/// Height of the source artwork coordinate space.
pub(super) const SOURCE_HEIGHT: f32 = 510.0;

/// Axis-aligned bounds in source artwork coordinates.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) struct SourceRect {
    /// Left coordinate.
    pub(super) x: f32,
    /// Top coordinate.
    pub(super) y: f32,
    /// Rectangle width.
    pub(super) width: f32,
    /// Rectangle height.
    pub(super) height: f32,
}

impl SourceRect {
    /// Scene-background bounds.
    pub(super) const SCENE_BACKGROUND: Self = Self {
        x: 0.0,
        y: 0.0,
        width: SOURCE_WIDTH,
        height: 311.0,
    };
    /// Animated monk bounds, aligned with the static panel pixels in each frame.
    pub(super) const MONK: Self = Self {
        x: 20.0,
        y: 5.0,
        width: 314.0,
        height: 311.0,
    };
    /// Control-panel bounds.
    pub(super) const CONTROL_PANEL: Self = Self {
        x: 0.0,
        y: 290.0,
        width: SOURCE_WIDTH,
        height: 220.0,
    };
    /// Editor pad bounds.
    pub(super) const PAD: Self = Self {
        x: 96.0,
        y: 362.0,
        width: 166.0,
        height: 84.0,
    };
    /// Portamento control bounds.
    pub(super) const PORTAMENTO: Self = Self {
        x: 19.0,
        y: 448.0,
        width: 50.0,
        height: 50.0,
    };
    /// Visible delay control bounds.
    pub(super) const DELAY: Self = Self {
        x: 104.0,
        y: 479.0,
        width: 152.0,
        height: 25.0,
    };
    /// Interactive delay control bounds.
    pub(super) const DELAY_HITBOX: Self = Self {
        x: 94.0,
        y: 469.0,
        width: 172.0,
        height: 45.0,
    };
    /// Voice control bounds.
    pub(super) const VOICE: Self = Self {
        x: 291.0,
        y: 447.0,
        width: 50.0,
        height: 50.0,
    };
    /// Help control bounds.
    pub(super) const HELP: Self = Self {
        x: 284.0,
        y: 300.0,
        width: 43.0,
        height: 35.0,
    };
    /// Help-panel artwork bounds.
    pub(super) const HELP_PANEL: Self = Self {
        x: 53.5,
        y: 117.5,
        width: 253.0,
        height: 275.0,
    };
    /// Arrow artwork dimensions at the origin.
    pub(super) const ARROW: Self = Self {
        x: 0.0,
        y: 0.0,
        width: 20.0,
        height: 17.0,
    };

    /// Creates bounds in source artwork coordinates.
    pub(super) const fn new(x: f32, y: f32, width: f32, height: f32) -> Self {
        Self {
            x,
            y,
            width,
            height,
        }
    }

    /// Returns whether a point lies inside the rectangle.
    pub(super) fn contains(self, point: (f32, f32)) -> bool {
        point.0 >= self.x
            && point.0 <= self.x + self.width
            && point.1 >= self.y
            && point.1 <= self.y + self.height
    }

    fn contains_ellipse(self, point: (f32, f32)) -> bool {
        let radius_x = self.width * 0.5;
        let radius_y = self.height * 0.5;
        let normalized_x = (point.0 - (self.x + radius_x)) / radius_x;
        let normalized_y = (point.1 - (self.y + radius_y)) / radius_y;
        normalized_x * normalized_x + normalized_y * normalized_y <= 1.0
    }
}

/// Letterboxed transform between source and view coordinates.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) struct ViewTransform {
    scale: f32,
    offset_x: f32,
    offset_y: f32,
}

impl ViewTransform {
    /// Creates a transform that fits the source into the view.
    pub(super) fn fit(view_width: f32, view_height: f32) -> Self {
        let scale = (view_width / SOURCE_WIDTH)
            .min(view_height / SOURCE_HEIGHT)
            .max(f32::EPSILON);
        Self {
            scale,
            offset_x: SOURCE_WIDTH.mul_add(-scale, view_width) * 0.5,
            offset_y: SOURCE_HEIGHT.mul_add(-scale, view_height) * 0.5,
        }
    }

    /// Converts source coordinates to view coordinates.
    pub(super) const fn source_to_view(self, point: (f32, f32)) -> (f32, f32) {
        (
            point.0.mul_add(self.scale, self.offset_x),
            point.1.mul_add(self.scale, self.offset_y),
        )
    }

    /// Converts view coordinates to source coordinates.
    pub(super) fn view_to_source(self, point: (f32, f32)) -> (f32, f32) {
        (
            (point.0 - self.offset_x) / self.scale,
            (point.1 - self.offset_y) / self.scale,
        )
    }
}

/// Interactive region selected by hit testing.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum HitTarget {
    /// The pad region.
    Pad,
    /// The portamento region.
    Portamento,
    /// The delay region.
    Delay,
    /// The voice region.
    Voice,
    /// The help region.
    Help,
}

/// Finds the interactive region at a source coordinate.
pub(super) fn hit_target(source_point: (f32, f32)) -> Option<HitTarget> {
    if SourceRect::PAD.contains(source_point) {
        Some(HitTarget::Pad)
    } else if SourceRect::PORTAMENTO.contains_ellipse(source_point) {
        Some(HitTarget::Portamento)
    } else if SourceRect::DELAY_HITBOX.contains(source_point) {
        Some(HitTarget::Delay)
    } else if SourceRect::VOICE.contains_ellipse(source_point) {
        Some(HitTarget::Voice)
    } else if SourceRect::HELP.contains(source_point) {
        Some(HitTarget::Help)
    } else {
        None
    }
}

/// Converts a source point into normalized pad coordinates.
pub(super) fn pad_position(source_point: (f32, f32)) -> (f32, f32) {
    (
        ((source_point.0 - SourceRect::PAD.x) / SourceRect::PAD.width).clamp(0.0, 1.0),
        ((source_point.1 - SourceRect::PAD.y) / SourceRect::PAD.height).clamp(0.0, 1.0),
    )
}

/// Maps a source x coordinate into a normalized control value.
pub(super) fn linear_value(source_x: f32, bounds: SourceRect) -> f32 {
    ((source_x - bounds.x) / bounds.width).clamp(0.0, 1.0)
}

/// Maps a pointer delta into a normalized rotary value.
pub(super) fn rotary_value(origin: f32, view_delta: (f32, f32)) -> f32 {
    (origin + (view_delta.0 - view_delta.1) / 250.0).clamp(0.0, 1.0)
}

#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
pub(super) struct Vertex {
    pub(super) position: [f32; 2],
    pub(super) uv: [f32; 2],
}

pub(super) struct DrawCommand {
    pub(super) texture: TextureSlot,
    pub(super) vertices: [Vertex; 6],
}

pub(super) fn strip_uv(frame: usize) -> [f32; 4] {
    let frame = frame.min(59);
    let frame_start = frame.to_f32().unwrap_or(0.0) / 60.0;
    let frame_end = (frame + 1).to_f32().unwrap_or(0.0) / 60.0;
    [0.0, frame_start, 1.0, frame_end]
}

pub(super) fn quad(
    texture: TextureSlot,
    bounds: SourceRect,
    [u0, v0, u1, v1]: [f32; 4],
    transform: ViewTransform,
    (view_width, view_height): (u32, u32),
) -> DrawCommand {
    let (x0, y0) = transform.source_to_view((bounds.x, bounds.y));
    let (x1, y1) = transform.source_to_view((bounds.x + bounds.width, bounds.y + bounds.height));
    let view_width = view_width.to_f32().unwrap_or(f32::MAX);
    let view_height = view_height.to_f32().unwrap_or(f32::MAX);
    let ndc = |x: f32, y: f32| {
        [
            x.mul_add(2.0 / view_width, -1.0),
            (-y).mul_add(2.0 / view_height, 1.0),
        ]
    };
    let top_left = Vertex {
        position: ndc(x0, y0),
        uv: [u0, v0],
    };
    let top_right = Vertex {
        position: ndc(x1, y0),
        uv: [u1, v0],
    };
    let bottom_right = Vertex {
        position: ndc(x1, y1),
        uv: [u1, v1],
    };
    let bottom_left = Vertex {
        position: ndc(x0, y1),
        uv: [u0, v1],
    };
    DrawCommand {
        texture,
        vertices: [
            top_left,
            top_right,
            bottom_right,
            top_left,
            bottom_right,
            bottom_left,
        ],
    }
}

pub(super) fn quad_rotated(
    texture: TextureSlot,
    bounds: SourceRect,
    [u0, v0, u1, v1]: [f32; 4],
    transform: ViewTransform,
    view_size: (u32, u32),
) -> DrawCommand {
    let mut draw = quad(texture, bounds, [u0, v0, u1, v1], transform, view_size);
    let rotated = [[u1, v0], [u1, v1], [u0, v1], [u1, v0], [u0, v1], [u0, v0]];
    for (vertex, mapped) in draw.vertices.iter_mut().zip(rotated) {
        vertex.uv = mapped;
    }
    draw
}
