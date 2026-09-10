use std::sync::Arc;

#[cfg(not(target_os = "ios"))]
use baseview::{Event, EventStatus, MouseButton, MouseEvent, Window, WindowHandler};
use num_traits::ToPrimitive;
use truce::core::editor::PluginContextReadF32;
use truce::prelude::PluginContext;

use crate::protocol::{GestureResult, GestureTransition, PAD_HOST_NOTE, PadPosition};

use super::{
    super::{parameter::PluginParameter, params::PluginParams},
    draws::ControlValues,
    geometry::{
        HitTarget, SourceRect, ViewTransform, hit_target, linear_value, pad_position, rotary_value,
    },
    renderer::Renderer,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(in crate::plugin) enum PointerPhase {
    Down,
    Drag,
    Up,
}

pub(in crate::plugin) fn pad_gesture(x: f32, y: f32, phase: PointerPhase) -> GestureResult {
    let position = PadPosition {
        x: x.clamp(0.0, 1.0),
        y: y.clamp(0.0, 1.0),
    };
    let transition = match phase {
        PointerPhase::Down => GestureTransition::NoteOn(PAD_HOST_NOTE),
        PointerPhase::Drag => GestureTransition::None,
        PointerPhase::Up => GestureTransition::NoteOff(PAD_HOST_NOTE),
    };
    GestureResult {
        position,
        vowel: 1.0 - position.y,
        transition,
    }
}

#[derive(Default)]
struct PointerState {
    cursor: (f32, f32),
    drag_start: (f32, f32),
    marker: (f32, f32),
}

#[derive(Default)]
struct UiState {
    pointer: PointerState,
    active: Option<HitTarget>,
    origin: f32,
    show_help: bool,
}

pub(super) struct Handler {
    renderer: Option<Renderer>,
    params: Arc<PluginParams>,
    context: PluginContext<PluginParams>,
    state: UiState,
    logical_size: (u32, u32),
}

impl Handler {
    #[cfg(any(test, target_os = "ios"))]
    pub(super) fn pointer(&mut self, phase: PointerPhase, position: (f32, f32)) {
        self.state.pointer.cursor = position;
        match phase {
            PointerPhase::Down => self.press(),
            PointerPhase::Drag => {
                if let Some(active) = self.state.active {
                    self.drag(active);
                }
            }
            PointerPhase::Up => self.release(),
        }
    }

    pub(super) fn frame(&mut self) {
        let controls = self.sync_control_values();
        if let Some(renderer) = self.renderer.as_mut() {
            renderer.render(
                self.state.pointer.marker,
                self.state.show_help,
                &self.params,
                controls,
                self.logical_size,
            );
        }
    }

    pub(super) fn new(
        renderer: Option<Renderer>,
        params: Arc<PluginParams>,
        context: PluginContext<PluginParams>,
        logical_size: (u32, u32),
    ) -> Self {
        Self {
            renderer,
            params,
            context,
            state: UiState {
                pointer: PointerState {
                    marker: (0.5, 0.5),
                    ..PointerState::default()
                },
                ..UiState::default()
            },
            logical_size,
        }
    }

    fn source_point(&self) -> (f32, f32) {
        ViewTransform::fit(
            self.logical_size.0.to_f32().unwrap_or(f32::MAX),
            self.logical_size.1.to_f32().unwrap_or(f32::MAX),
        )
        .view_to_source(self.state.pointer.cursor)
    }

    fn host_parameter(&self, parameter: PluginParameter) -> f32 {
        self.context
            .get_param(PluginParams::info(parameter).id)
            .clamp(0.0, 1.0)
    }

    fn sync_control_values(&mut self) -> ControlValues {
        let mut controls = ControlValues {
            vowel: self.host_parameter(PluginParameter::Vowel),
            portamento: self.host_parameter(PluginParameter::Portamento),
            delay: self.host_parameter(PluginParameter::Delay),
        };
        if self.state.active == Some(HitTarget::Pad) {
            controls.vowel = 1.0 - self.state.pointer.marker.1;
        } else {
            self.state.pointer.marker.1 = 1.0 - controls.vowel;
        }
        controls
    }

    fn press(&mut self) {
        if self.state.active.is_some() {
            return;
        }
        self.state.pointer.drag_start = self.state.pointer.cursor;
        let point = self.source_point();
        if self.state.show_help {
            self.state.show_help = false;
            return;
        }
        match hit_target(point) {
            Some(HitTarget::Pad) => {
                let (x, y) = pad_position(point);
                self.state.pointer.marker = (x, y);
                let gesture = pad_gesture(x, y, PointerPhase::Down);
                self.state.active = Some(HitTarget::Pad);
                let vowel_id = PluginParams::info(PluginParameter::Vowel).id;
                self.context.begin_edit(vowel_id);
                self.context.set_param(vowel_id, f64::from(gesture.vowel));
                self.params.editor.push(gesture);
            }
            Some(HitTarget::Portamento) => {
                self.state.active = Some(HitTarget::Portamento);
                self.state.origin = self.params.value(PluginParameter::Portamento);
                self.context
                    .begin_edit(PluginParams::info(PluginParameter::Portamento).id);
            }
            Some(HitTarget::Delay) => {
                self.state.active = Some(HitTarget::Delay);
                self.context
                    .begin_edit(PluginParams::info(PluginParameter::Delay).id);
                self.drag(HitTarget::Delay);
            }
            // The original right-hand knob artwork is named Voice, but it edits
            // the same vowel parameter as the pad. Voice remains a host parameter.
            Some(HitTarget::Voice) => {
                self.state.active = Some(HitTarget::Voice);
                self.state.origin = self.host_parameter(PluginParameter::Vowel);
                self.context
                    .begin_edit(PluginParams::info(PluginParameter::Vowel).id);
            }
            Some(HitTarget::Help) => self.state.show_help = !self.state.show_help,
            None => {}
        }
    }

    fn drag(&mut self, target: HitTarget) {
        let point = self.source_point();
        match target {
            HitTarget::Pad => {
                let (x, y) = pad_position(point);
                self.state.pointer.marker = (x, y);
                let gesture = pad_gesture(x, y, PointerPhase::Drag);
                self.context.set_param(
                    PluginParams::info(PluginParameter::Vowel).id,
                    f64::from(gesture.vowel),
                );
                self.params.editor.push(gesture);
            }
            HitTarget::Delay => self.context.set_param(
                PluginParams::info(PluginParameter::Delay).id,
                f64::from(linear_value(point.0, SourceRect::DELAY)),
            ),
            HitTarget::Portamento | HitTarget::Voice => {
                let delta = (
                    self.state.pointer.cursor.0 - self.state.pointer.drag_start.0,
                    self.state.pointer.cursor.1 - self.state.pointer.drag_start.1,
                );
                let parameter = match target {
                    HitTarget::Portamento => PluginParameter::Portamento,
                    HitTarget::Voice => PluginParameter::Vowel,
                    HitTarget::Pad | HitTarget::Delay | HitTarget::Help => return,
                };
                self.context.set_param(
                    PluginParams::info(parameter).id,
                    f64::from(rotary_value(self.state.origin, delta)),
                );
            }
            HitTarget::Help => {}
        }
    }

    pub(super) fn release(&mut self) {
        let Some(target) = self.state.active.take() else {
            return;
        };
        if target == HitTarget::Pad {
            let (x, y) = self.state.pointer.marker;
            let gesture = pad_gesture(x, y, PointerPhase::Up);
            self.params.editor.push(gesture);
            self.context
                .end_edit(PluginParams::info(PluginParameter::Vowel).id);
            return;
        }
        let parameter = match target {
            HitTarget::Portamento => Some(PluginParameter::Portamento),
            HitTarget::Delay => Some(PluginParameter::Delay),
            HitTarget::Voice => Some(PluginParameter::Vowel),
            HitTarget::Pad | HitTarget::Help => None,
        };
        if let Some(parameter) = parameter {
            self.context.end_edit(PluginParams::info(parameter).id);
        }
    }
}

#[cfg(test)]
mod tests;

#[cfg(not(target_os = "ios"))]
impl WindowHandler for Handler {
    fn on_frame(&mut self, _window: &mut Window) {
        self.frame();
    }

    fn on_event(&mut self, _window: &mut Window, event: Event) -> EventStatus {
        match event {
            Event::Mouse(MouseEvent::CursorMoved { position, .. }) => {
                self.state.pointer.cursor = (
                    position.x.to_f32().unwrap_or(0.0),
                    position.y.to_f32().unwrap_or(0.0),
                );
                if let Some(active) = self.state.active {
                    self.drag(active);
                }
                EventStatus::Captured
            }
            Event::Mouse(MouseEvent::ButtonPressed {
                button: MouseButton::Left,
                ..
            }) => {
                self.press();
                EventStatus::Captured
            }
            // Leaving the child window must not terminate a held gesture. The
            // button release (or lifecycle events below) owns its completion.
            Event::Mouse(MouseEvent::ButtonReleased {
                button: MouseButton::Left,
                ..
            })
            | Event::Window(baseview::WindowEvent::Unfocused | baseview::WindowEvent::WillClose) => {
                self.release();
                EventStatus::Captured
            }
            Event::Window(baseview::WindowEvent::Resized(info)) => {
                let logical_size = info.logical_size();
                self.logical_size = (
                    logical_size
                        .width
                        .clamp(0.0, f64::from(u32::MAX))
                        .to_u32()
                        .unwrap_or(0),
                    logical_size
                        .height
                        .clamp(0.0, f64::from(u32::MAX))
                        .to_u32()
                        .unwrap_or(0),
                );
                EventStatus::Captured
            }
            Event::Mouse(_)
            | Event::Keyboard(_)
            | Event::Window(baseview::WindowEvent::Focused) => EventStatus::Ignored,
        }
    }
}
