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

fn fingerprint(pixels: &[u8]) -> u64 {
    pixels.iter().fold(0xcbf2_9ce4_8422_2325_u64, |hash, byte| {
        (hash ^ u64::from(*byte)).wrapping_mul(0x0000_0100_0000_01b3)
    })
}

#[test]
fn asset_pixel_dimensions_match_the_rendering_contract() {
    let assets: [(&[u8], (u32, u32)); 10] = [
        (include_bytes!("../assets/source_surface.qoi"), (360, 510)),
        (include_bytes!("../assets/scene_background.qoi"), (357, 311)),
        (include_bytes!("../assets/control_panel.qoi"), (357, 220)),
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
fn rendered_backgrounds_crop_three_columns_without_resampling() {
    let assets = [
        (
            include_bytes!("../assets/scene_background.qoi").as_slice(),
            15_167_596_836_934_979_104_u64,
        ),
        (
            include_bytes!("../assets/control_panel.qoi").as_slice(),
            5_565_318_640_726_019_791_u64,
        ),
    ];
    for (bytes, expected_fingerprint) in assets {
        let (pixels, width, height) = qoi_pixels(bytes).expect("valid RGBA QOI artwork");
        assert_eq!(width, 357);
        assert_eq!(pixels.len(), width * height * 4);
        // Fingerprints of the original assets' first 357 columns: cropping must
        // preserve every retained pixel instead of stretching or repeating edges.
        assert_eq!(fingerprint(&pixels), expected_fingerprint);
    }
}
