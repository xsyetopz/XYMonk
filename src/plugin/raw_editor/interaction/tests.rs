use std::sync::Arc;

use crossbeam_queue::ArrayQueue;
use truce::core::editor::ClosureBridge;
use truce::prelude::{Params, PluginContext};

use super::{Handler, HitTarget, PluginParameter, PluginParams};

#[derive(Debug, PartialEq, Eq)]
enum HostEdit {
    Begin(u32),
    Set(u32, u64),
    End(u32),
}

fn record(events: &ArrayQueue<HostEdit>, event: HostEdit) {
    assert!(events.push(event).is_ok());
}

fn test_context(
    params: Arc<PluginParams>,
    events: Arc<ArrayQueue<HostEdit>>,
    host_values: [f64; 4],
) -> PluginContext<PluginParams> {
    let begin_events = Arc::clone(&events);
    let set_events = Arc::clone(&events);
    let end_events = events;
    let concrete_params = Arc::clone(&params);
    let erased_params: Arc<dyn Params> = concrete_params;
    PluginContext::from_closures(
        ClosureBridge {
            begin_edit: Box::new(move |id| record(&begin_events, HostEdit::Begin(id))),
            set_param: Box::new(move |id, value| {
                record(&set_events, HostEdit::Set(id, value.to_bits()));
            }),
            end_edit: Box::new(move |id| record(&end_events, HostEdit::End(id))),
            request_resize: Box::new(|_, _| false),
            get_param: Box::new(move |id| {
                PluginParameter::from_id(id)
                    .and_then(|parameter| host_values.get(parameter.index()).copied())
                    .unwrap_or_default()
            }),
            get_param_plain: Box::new(|_| 0.0),
            format_param: Box::new(|_| String::new()),
            get_meter: Box::new(|_| 0.0),
            get_state: Box::new(Vec::new),
            set_state: Box::new(drop),
            transport: Box::new(|| None),
        },
        erased_params,
    )
    .with_params(params)
}

#[test]
fn pad_y_axis_is_reported_as_a_vowel_host_edit() {
    let params = Arc::new(PluginParams::new());
    let events = Arc::new(ArrayQueue::new(4));
    let context = test_context(
        Arc::clone(&params),
        Arc::clone(&events),
        [0.5, 0.5, 0.8, 0.5],
    );
    let mut handler = Handler::new(None, Arc::clone(&params), context, (360, 510));

    handler.state.pointer.cursor = (179.0, 383.0);
    handler.press();
    handler.state.pointer.cursor = (179.0, 425.0);
    handler.drag(HitTarget::Pad);
    handler.release();

    let vowel_id = PluginParameter::Vowel.id();
    let host_edits: Vec<_> = std::iter::from_fn(|| events.pop()).collect();
    assert_eq!(
        host_edits,
        [
            HostEdit::Begin(vowel_id),
            HostEdit::Set(vowel_id, 0.75_f64.to_bits()),
            HostEdit::Set(vowel_id, 0.25_f64.to_bits()),
            HostEdit::End(vowel_id),
        ]
    );

    let commands: Vec<_> = std::iter::from_fn(|| params.editor.pop()).collect();
    assert_eq!(commands.len(), 3);
    assert!(commands.first().is_some_and(|command| matches!(
        command.transition,
        crate::protocol::GestureTransition::NoteOn(_)
    )));
    assert!(
        commands.get(1).is_some_and(|command| {
            command.transition == crate::protocol::GestureTransition::None
        })
    );
    assert!(commands.get(2).is_some_and(|command| matches!(
        command.transition,
        crate::protocol::GestureTransition::NoteOff(_)
    )));
}

#[test]
fn host_parameters_drive_control_assets_and_idle_vowel_marker() {
    let params = Arc::new(PluginParams::new());
    let events = Arc::new(ArrayQueue::new(4));
    let context = test_context(Arc::clone(&params), events, [0.75, 0.2, 0.3, 0.9]);
    let mut handler = Handler::new(None, params, context, (360, 510));

    let controls = handler.sync_control_values();

    assert_eq!(
        controls,
        super::ControlValues {
            vowel: 0.75,
            portamento: 0.2,
            delay: 0.3,
            voice: 0.9,
        }
    );
    assert!((handler.state.pointer.marker.1 - 0.25).abs() <= f32::EPSILON);

    handler.state.active = Some(HitTarget::Pad);
    handler.state.pointer.marker.1 = 0.6;
    handler.sync_control_values();
    assert!((handler.state.pointer.marker.1 - 0.6).abs() <= f32::EPSILON);
}

#[test]
fn touch_cancellation_and_close_release_the_pad_once() {
    let params = Arc::new(PluginParams::new());
    let events = Arc::new(ArrayQueue::new(8));
    let context = test_context(Arc::clone(&params), Arc::clone(&events), [0.5; 4]);
    let mut handler = Handler::new(None, Arc::clone(&params), context, (360, 510));
    handler.pointer(super::PointerPhase::Down, (179.0, 383.0));
    handler.pointer(super::PointerPhase::Drag, (179.0, 425.0));
    handler.release(); // UIKit touch cancellation.
    handler.release(); // Editor close after cancellation.
    let edits: Vec<_> = std::iter::from_fn(|| events.pop()).collect();
    assert_eq!(
        edits
            .iter()
            .filter(|edit| matches!(edit, HostEdit::End(_)))
            .count(),
        1
    );
    let commands: Vec<_> = std::iter::from_fn(|| params.editor.pop()).collect();
    assert_eq!(
        commands
            .iter()
            .filter(|command| matches!(
                command.transition,
                crate::protocol::GestureTransition::NoteOff(_)
            ))
            .count(),
        1
    );
    assert!(handler.state.active.is_none());
}
