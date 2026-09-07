use std::mem::size_of;

use num_traits::ToPrimitive;
use qoi::Channels;
use wgpu::util::DeviceExt;

use super::{
    super::params::PluginParams,
    artwork::Artwork,
    draws::{ControlValues, build_draws},
    geometry::{DrawCommand, Vertex},
};

const SHADER: &str = include_str!("shader.wgsl");

struct Texture {
    bind_group: wgpu::BindGroup,
}

struct FrameGeometry {
    draws: Vec<DrawCommand>,
    vertices: Vec<Vertex>,
}

impl FrameGeometry {
    fn new() -> Self {
        Self {
            draws: Vec::with_capacity(9),
            vertices: Vec::with_capacity(54),
        }
    }
}

pub(super) struct Renderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    surface: wgpu::Surface<'static>,
    pipeline: wgpu::RenderPipeline,
    textures: Vec<Texture>,
    frame_geometry: FrameGeometry,
}

impl Renderer {
    /// # Safety
    ///
    /// The caller must keep `window` alive until the returned renderer is dropped.
    #[expect(
        unsafe_code,
        reason = "wgpu requires the baseview child window to outlive its surface"
    )]
    #[cfg(not(target_os = "ios"))]
    pub(super) unsafe fn new(window: &baseview::Window, width: u32, height: u32) -> Option<Self> {
        let instance = wgpu::Instance::new(truce_gui::platform::editor_instance_descriptor());
        // SAFETY: The baseview child window outlives the surface through the renderer.
        let surface = unsafe { truce_gui::platform::create_wgpu_surface(&instance, window) }?;
        Self::with_surface(&instance, surface, width, height)
    }

    pub(super) fn with_surface(
        instance: &wgpu::Instance,
        surface: wgpu::Surface<'static>,
        width: u32,
        height: u32,
    ) -> Option<Self> {
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            compatible_surface: Some(&surface),
            force_fallback_adapter: false,
        }))
        .ok()?;
        let limits = adapter.limits();
        let (device, queue) = pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("delay-lama-editor"),
            required_features: wgpu::Features::empty(),
            required_limits: limits,
            experimental_features: wgpu::ExperimentalFeatures::default(),
            memory_hints: wgpu::MemoryHints::Performance,
            trace: wgpu::Trace::Off,
        }))
        .ok()?;

        let surface_capabilities = surface.get_capabilities(&adapter);
        let format = surface_capabilities
            .formats
            .iter()
            .find(|format| format.is_srgb())
            .copied()
            .or_else(|| surface_capabilities.formats.first().copied())?;
        let surface_config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width,
            height,
            present_mode: wgpu::PresentMode::AutoVsync,
            desired_maximum_frame_latency: 2,
            alpha_mode: wgpu::CompositeAlphaMode::Auto,
            view_formats: vec![],
        };
        surface.configure(&device, &surface_config);

        let bind_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("delay-lama-texture-layout"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });
        let pipeline = Self::create_pipeline(&device, &bind_layout, format);

        if !Artwork::reference_assets_complete() {
            return None;
        }
        let assets = Artwork::EMBEDDED.rendered_assets();
        let mut textures = Vec::with_capacity(assets.len());
        for (slot, bytes) in assets {
            if slot.index() != textures.len() {
                return None;
            }
            textures.push(Self::upload(&device, &queue, &bind_layout, bytes)?);
        }

        Some(Self {
            device,
            queue,
            surface,
            pipeline,
            textures,
            frame_geometry: FrameGeometry::new(),
        })
    }

    fn create_pipeline(
        device: &wgpu::Device,
        bind_layout: &wgpu::BindGroupLayout,
        format: wgpu::TextureFormat,
    ) -> wgpu::RenderPipeline {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("delay-lama-quads"),
            source: wgpu::ShaderSource::Wgsl(SHADER.into()),
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("delay-lama-pipeline-layout"),
            bind_group_layouts: &[Some(bind_layout)],
            immediate_size: 0,
        });
        device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("delay-lama-pipeline"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                buffers: &[wgpu::VertexBufferLayout {
                    array_stride: size_of::<Vertex>().to_u64().unwrap_or(0),
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &[
                        wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x2,
                            offset: 0,
                            shader_location: 0,
                        },
                        wgpu::VertexAttribute {
                            format: wgpu::VertexFormat::Float32x2,
                            offset: 8,
                            shader_location: 1,
                        },
                    ],
                }],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs"),
                compilation_options: wgpu::PipelineCompilationOptions::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format,
                    blend: Some(wgpu::BlendState::ALPHA_BLENDING),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState::default(),
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            multiview_mask: None,
            cache: None,
        })
    }

    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        layout: &wgpu::BindGroupLayout,
        bytes: &[u8],
    ) -> Option<Texture> {
        let mut decoder = qoi::Decoder::new(bytes).ok()?.with_channels(Channels::Rgba);
        let (width, height) = (decoder.header().width, decoder.header().height);
        let mut pixels = decoder.decode_to_vec().ok()?;
        if width == 20 && height == 17 {
            key_white(&mut pixels);
        }
        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("delay-lama-asset"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8UnormSrgb,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            &pixels,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(4 * width),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        let view = texture.create_view(&wgpu::TextureViewDescriptor::default());
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            mag_filter: wgpu::FilterMode::Nearest,
            min_filter: wgpu::FilterMode::Nearest,
            ..wgpu::SamplerDescriptor::default()
        });
        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("delay-lama-asset-bind"),
            layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
            ],
        });
        Some(Texture { bind_group })
    }

    pub(super) fn render(
        &mut self,
        marker: (f32, f32),
        show_help: bool,
        params: &PluginParams,
        controls: ControlValues,
        logical_size: (u32, u32),
    ) {
        let (wgpu::CurrentSurfaceTexture::Success(frame)
        | wgpu::CurrentSurfaceTexture::Suboptimal(frame)) = self.surface.get_current_texture()
        else {
            return;
        };
        let view = frame
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());

        self.frame_geometry.draws.clear();
        build_draws(
            &mut self.frame_geometry.draws,
            marker,
            show_help,
            params,
            controls,
            logical_size,
        );
        self.frame_geometry.vertices.clear();
        self.frame_geometry.vertices.extend(
            self.frame_geometry
                .draws
                .iter()
                .flat_map(|draw| draw.vertices.iter().copied()),
        );

        let buffer = self
            .device
            .create_buffer_init(&wgpu::util::BufferInitDescriptor {
                label: Some("delay-lama-quads"),
                contents: bytemuck::cast_slice(&self.frame_geometry.vertices),
                usage: wgpu::BufferUsages::VERTEX,
            });
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor::default());

        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("delay-lama-pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_pipeline(&self.pipeline);
            pass.set_vertex_buffer(0, buffer.slice(..));
            let mut vertex_start = 0_u32;
            for draw in &self.frame_geometry.draws {
                if let Some(texture) = self.textures.get(draw.texture.index()) {
                    pass.set_bind_group(0, &texture.bind_group, &[]);
                    pass.draw(vertex_start..vertex_start + 6, 0..1);
                }
                vertex_start += 6;
            }
        }

        self.queue.submit(Some(encoder.finish()));
        frame.present();
    }
}

fn key_white(pixels: &mut [u8]) {
    for [red, green, blue, alpha] in pixels.as_chunks_mut::<4>().0 {
        if *red == 255 && *green == 255 && *blue == 255 {
            *alpha = 0;
        }
    }
}
