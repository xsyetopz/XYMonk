mod animation;
mod artwork;
mod draws;
mod geometry;
mod interaction;
#[cfg(target_os = "ios")]
mod ios;
#[cfg(not(target_os = "ios"))]
mod lifecycle;
mod renderer;

pub(super) use animation::animation_frame;
#[cfg(target_os = "ios")]
pub(super) use ios::RawEditor;
#[cfg(not(target_os = "ios"))]
pub(super) use lifecycle::RawEditor;

#[cfg(test)]
pub(super) use interaction::{PointerPhase, pad_gesture};

pub(super) const SIZE: (u32, u32) = geometry::SOURCE_SIZE;

#[cfg(test)]
mod tests;
