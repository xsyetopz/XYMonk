//! Embedded-artwork contract tests.

fn qoi_dimensions(bytes: &[u8]) -> Option<(u32, u32)> {
    let mut decoder = qoi::Decoder::new(bytes)
        .ok()?
        .with_channels(qoi::Channels::Rgba);
    let dimensions = (decoder.header().width, decoder.header().height);
    let pixel_count = dimensions.0.checked_mul(dimensions.1)?.checked_mul(4)?;
    let decoded_length = usize::try_from(pixel_count).ok()?;
    (decoder.decode_to_vec().ok()?.len() == decoded_length).then_some(dimensions)
}

fn qoi_pixels(bytes: &[u8]) -> Option<(Vec<u8>, usize, usize)> {
    let mut decoder = qoi::Decoder::new(bytes)
        .ok()?
        .with_channels(qoi::Channels::Rgba);
    let width = usize::try_from(decoder.header().width).ok()?;
    let height = usize::try_from(decoder.header().height).ok()?;
    Some((decoder.decode_to_vec().ok()?, width, height))
}

fn fingerprint_without_right_edge(pixels: &[u8], width: usize, height: usize) -> u64 {
    let mut fingerprint = 0xcbf2_9ce4_8422_2325_u64;
    for row in pixels.chunks_exact(width * 4).take(height) {
        for byte in row.iter().take((width - 2) * 4) {
            fingerprint = (fingerprint ^ u64::from(*byte)).wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
    fingerprint
}

#[test]
fn asset_pixel_dimensions_are_preserved() {
    let assets: [(&[u8], (u32, u32)); 10] = [
        (include_bytes!("../assets/source_surface.qoi"), (360, 510)),
        (include_bytes!("../assets/scene_background.qoi"), (360, 311)),
        (include_bytes!("../assets/control_panel.qoi"), (360, 220)),
        (
            include_bytes!("../assets/monk_sprite_sheet.qoi"),
            (1570, 1866),
        ),
        (include_bytes!("../assets/knob_strip_a.qoi"), (50, 3000)),
        (include_bytes!("../assets/knob_strip_b.qoi"), (50, 3000)),
        (include_bytes!("../assets/ui_arrow.qoi"), (20, 17)),
        (include_bytes!("../assets/ui_tile_a.qoi"), (10, 10)),
        (include_bytes!("../assets/ui_tile_b.qoi"), (10, 10)),
        (include_bytes!("../assets/help_panel.qoi"), (253, 275)),
    ];
    for (bytes, dimensions) in assets {
        assert_eq!(qoi_dimensions(bytes), Some(dimensions));
    }
}

#[test]
fn rendered_backgrounds_preserve_content_and_repair_the_right_edge() {
    let assets = [
        (
            include_bytes!("../assets/scene_background.qoi").as_slice(),
            12_741_140_312_361_243_458_u64,
        ),
        (
            include_bytes!("../assets/control_panel.qoi").as_slice(),
            7_030_253_285_547_380_992_u64,
        ),
    ];
    for (bytes, expected_fingerprint) in assets {
        let (pixels, width, height) = qoi_pixels(bytes).expect("valid RGBA QOI artwork");
        assert_eq!(width, 360);
        assert_eq!(
            fingerprint_without_right_edge(&pixels, width, height),
            expected_fingerprint,
        );
        for row in pixels.chunks_exact(width * 4).take(height) {
            let clean_edge = &row[(width - 3) * 4..(width - 2) * 4];
            assert_eq!(&row[(width - 2) * 4..(width - 1) * 4], clean_edge);
            assert_eq!(&row[(width - 1) * 4..width * 4], clean_edge);
        }
    }
}
