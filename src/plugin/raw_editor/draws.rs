use num_traits::ToPrimitive;

use super::{
    super::params::PluginParams,
    artwork::TextureSlot,
    geometry::{DrawCommand, SourceRect, ViewTransform, quad, quad_rotated, strip_uv},
};

#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) struct ControlValues {
    pub(super) vowel: f32,
    pub(super) portamento: f32,
    pub(super) delay: f32,
}

pub(super) fn build_draws(
    draws: &mut Vec<DrawCommand>,
    marker: (f32, f32),
    show_help: bool,
    params: &PluginParams,
    controls: ControlValues,
    logical_size: (u32, u32),
) {
    let transform = ViewTransform::fit(
        logical_size.0.to_f32().unwrap_or(f32::MAX),
        logical_size.1.to_f32().unwrap_or(f32::MAX),
    );
    push_scene(draws, params, transform, logical_size);
    push_controls(draws, controls, transform, logical_size);
    push_pad_markers(draws, marker, transform, logical_size);
    if show_help {
        draws.push(quad(
            TextureSlot::Help,
            SourceRect::HELP_PANEL,
            [0.0, 0.0, 1.0, 1.0],
            transform,
            logical_size,
        ));
    }
}

fn push_scene(
    draws: &mut Vec<DrawCommand>,
    params: &PluginParams,
    transform: ViewTransform,
    logical_size: (u32, u32),
) {
    draws.push(quad(
        TextureSlot::Scene,
        SourceRect::SCENE_BACKGROUND,
        [0.0, 0.0, 1.0, 1.0],
        transform,
        logical_size,
    ));
    let animation = params.editor.animation_frame().min(29);
    let column = (animation / 6).to_f32().unwrap_or(0.0);
    let row = (animation % 6).to_f32().unwrap_or(0.0);
    draws.push(quad(
        TextureSlot::Monk,
        SourceRect::MONK,
        [
            column / 5.0,
            row / 6.0,
            (column + 1.0) / 5.0,
            (row + 1.0) / 6.0,
        ],
        transform,
        logical_size,
    ));
    draws.push(quad(
        TextureSlot::Panel,
        SourceRect::CONTROL_PANEL,
        [0.0, 0.0, 1.0, 1.0],
        transform,
        logical_size,
    ));
}

fn push_controls(
    draws: &mut Vec<DrawCommand>,
    controls: ControlValues,
    transform: ViewTransform,
    logical_size: (u32, u32),
) {
    let portamento_frame = frame_from_parameter(controls.portamento);
    let vowel_frame = frame_from_parameter(controls.vowel);
    draws.push(quad(
        TextureSlot::PortamentoKnob,
        SourceRect::PORTAMENTO,
        strip_uv(portamento_frame),
        transform,
        logical_size,
    ));
    draws.push(quad(
        TextureSlot::VoiceKnob,
        SourceRect::VOICE,
        strip_uv(vowel_frame),
        transform,
        logical_size,
    ));
    let arrow = SourceRect::ARROW;
    let delay_x = controls
        .delay
        .clamp(0.0, 1.0)
        .mul_add(SourceRect::DELAY.width - arrow.width, SourceRect::DELAY.x);
    let delay_y = (SourceRect::DELAY.height - arrow.height).mul_add(0.5, SourceRect::DELAY.y - 5.0);
    draws.push(quad(
        TextureSlot::Arrow,
        SourceRect::new(delay_x, delay_y, arrow.width, arrow.height),
        [0.0, 0.0, 1.0, 1.0],
        transform,
        logical_size,
    ));
}

fn push_pad_markers(
    draws: &mut Vec<DrawCommand>,
    marker: (f32, f32),
    transform: ViewTransform,
    logical_size: (u32, u32),
) {
    const MARKER_WIDTH: f32 = 12.0;
    const MARKER_HEIGHT: f32 = 10.0;

    let horizontal_x = marker.0.mul_add(
        SourceRect::PAD.width,
        MARKER_WIDTH.mul_add(-0.5, SourceRect::PAD.x),
    );
    draws.push(quad(
        TextureSlot::Arrow,
        SourceRect::new(
            horizontal_x,
            SourceRect::PAD.y - MARKER_HEIGHT,
            MARKER_WIDTH,
            MARKER_HEIGHT,
        ),
        [0.0, 0.0, 1.0, 1.0],
        transform,
        logical_size,
    ));
    let vertical_y = marker
        .1
        .mul_add(SourceRect::PAD.height - MARKER_WIDTH, SourceRect::PAD.y);
    draws.push(quad_rotated(
        TextureSlot::Arrow,
        SourceRect::new(
            SourceRect::PAD.x - MARKER_HEIGHT,
            vertical_y,
            MARKER_HEIGHT,
            MARKER_WIDTH,
        ),
        [0.0, 0.0, 1.0, 1.0],
        transform,
        logical_size,
    ));
}

fn frame_from_parameter(value: f32) -> usize {
    (value.clamp(0.0, 1.0) * 59.0)
        .round()
        .to_usize()
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn vowel_knob_artwork_tracks_the_vowel_range() {
        for (vowel, frame) in [(0.0, 0), (0.5, 30), (1.0, 59)] {
            let mut draws = Vec::new();
            push_controls(
                &mut draws,
                ControlValues {
                    vowel,
                    portamento: 0.2,
                    delay: 0.8,
                },
                ViewTransform::fit(360.0, 510.0),
                (360, 510),
            );
            let knob = draws
                .iter()
                .find(|draw| draw.texture == TextureSlot::VoiceKnob)
                .expect("vowel knob draw");
            let [u, v, _, _] = strip_uv(frame);
            for (actual, expected) in knob.vertices[0].uv.into_iter().zip([u, v]) {
                assert!((actual - expected).abs() <= f32::EPSILON);
            }
        }
    }
}
