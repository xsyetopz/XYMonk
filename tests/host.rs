//! Public host-processor contract tests.

use xymonk::host::ProcessorModel;
use xymonk::protocol::{
    GestureResult, GestureTransition, PAD_HOST_NOTE, PAD_INTERNAL_NOTE, PadPosition,
};
use xymonk::synthesizer::Parameters;

fn processor_with_held_pad() -> ProcessorModel {
    let mut processor = ProcessorModel::default();
    processor.prepare(44_100.0, 64);
    processor.apply_pad_gesture(GestureResult {
        position: PadPosition { x: 0.25, y: 0.75 },
        vowel: 0.25,
        transition: GestureTransition::NoteOn(PAD_HOST_NOTE),
    });
    processor
}

#[test]
fn parameter_round_trip() {
    let mut p = ProcessorModel::default();
    let v = Parameters {
        vowel: 0.02,
        port_time: 0.03,
        delay_mix: 0.04,
        voice: 0.05,
        vibrato: 0.06,
        volume: 0.07,
        xy_routing: 0.08,
    };
    p.set_parameters(v);
    assert_eq!(p.parameters(), v);
}

#[test]
fn visual_state_follows_processor_and_pad_ownership() {
    let mut processor = ProcessorModel::default();
    processor.set_parameters(Parameters {
        vowel: 0.25,
        ..Parameters::default()
    });
    let state = processor.visual_state();
    assert_eq!(state.note, -1);
    assert!(!state.gate);
    assert!((state.vowel - 0.25).abs() <= f32::EPSILON);
    assert!(state.atlas_selector.abs() <= f32::EPSILON);
}

#[test]
fn factory_programs_match_original_contract() {
    assert_eq!(ProcessorModel::factory_programs().len(), 5);
    assert_eq!(
        ProcessorModel::factory_programs()
            .first()
            .map(|program| program.0),
        Some("Rabten")
    );
    let mut processor = ProcessorModel::default();
    assert!(processor.load_factory_program(4));
    assert!((processor.parameters().voice - 1.0).abs() <= f32::EPSILON);
    assert!(!processor.load_factory_program(5));
}

#[test]
fn state_round_trip_is_versioned_and_deterministic() {
    let mut source = ProcessorModel::default();
    source.set_parameters(Parameters {
        vowel: 0.2,
        volume: 0.7,
        ..Parameters::default()
    });
    let state = source.save_state();
    let mut restored = ProcessorModel::default();
    assert!(restored.load_state(&state));
    assert_eq!(restored.parameters(), source.parameters());
    assert!(!restored.load_state(b"invalid"));
}

#[test]
fn noncanonical_state_is_normalized_by_the_single_parameter_authority() {
    let mut raw_state = ProcessorModel::default().save_state();
    let noncanonical = [f32::NAN, -1.0, 2.0, f32::INFINITY, 0.0, 0.1, 0.0];
    let payload = raw_state.get_mut(4..);
    assert!(
        payload.is_some(),
        "fixed-size state must contain its payload"
    );
    let Some(payload) = payload else {
        return;
    };
    for (destination, value) in payload.as_chunks_mut::<4>().0.iter_mut().zip(noncanonical) {
        destination.copy_from_slice(&value.to_le_bytes());
    }

    let mut processor = ProcessorModel::default();
    assert!(processor.load_state(&raw_state));
    let normalized = processor.parameters();
    assert!(normalized.vowel.is_finite());
    assert!((normalized.port_time - 0.0).abs() <= f32::EPSILON);
    assert!((normalized.delay_mix - 1.0).abs() <= f32::EPSILON);
    assert!(normalized.voice.is_finite());
    assert_ne!(processor.save_state(), raw_state);
}

#[test]
fn pad_gesture_crosses_the_host_boundary_once() {
    let processor = processor_with_held_pad();

    assert_eq!(processor.voice_state().current_note, PAD_INTERNAL_NOTE);
    assert!(processor.voice_state().gate);
    assert!((processor.visual_state().vowel - 0.25).abs() <= f32::EPSILON);
}

#[test]
fn pad_drag_modulates_without_retriggering_the_local_voice() {
    let mut processor = processor_with_held_pad();
    processor.apply_pad_gesture(GestureResult {
        position: PadPosition { x: 0.8, y: 0.2 },
        vowel: 0.8,
        transition: GestureTransition::None,
    });

    assert!(processor.voice_state().gate);
    assert!((processor.visual_state().vowel - 0.8).abs() <= f32::EPSILON);
    processor.apply_pad_gesture(GestureResult {
        position: PadPosition { x: 0.8, y: 0.2 },
        vowel: 0.8,
        transition: GestureTransition::NoteOff(PAD_HOST_NOTE),
    });
    assert!(!processor.voice_state().gate);
}
