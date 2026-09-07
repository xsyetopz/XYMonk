//! `UIKit` lifecycle adapter for the shared artwork renderer and pointer handler.

use std::{cell::RefCell, ptr::NonNull, sync::Arc};

use num_traits::ToPrimitive;
use objc2::{
    DefinedClass, MainThreadMarker, MainThreadOnly, define_class, msg_send, rc::Retained, sel,
};
use objc2_foundation::{NSPoint, NSRect, NSRunLoop, NSRunLoopCommonModes, NSSet, NSSize};
use objc2_quartz_core::{CADisplayLink, CAFrameRateRange};
use objc2_ui_kit::{UIEvent, UITouch, UIView};
use raw_window_handle::{
    RawDisplayHandle, RawWindowHandle as NativeHandle, UiKitDisplayHandle, UiKitWindowHandle,
};
use truce::core::editor::RawWindowHandle;
use truce::prelude::{Editor, PluginContext};

use super::{
    SIZE,
    interaction::{Handler, PointerPhase},
    renderer::Renderer,
};
use crate::plugin::params::PluginParams;

#[expect(
    unsafe_code,
    reason = "Objective-C UIView overrides use UIKit's exact selector signatures; all callbacks are main-thread-only"
)]
mod view {
    use super::{
        CADisplayLink, DefinedClass, Handler, MainThreadOnly, NSSet, PointerPhase, RefCell,
        UIEvent, UITouch, UIView, define_class, msg_send,
    };

    define_class!(
        // SAFETY: UIView is initialized through initWithFrame and remains on
        // the main thread. Ivars own the renderer and are cleared before removal.
        #[unsafe(super(UIView))]
        #[thread_kind = MainThreadOnly]
        #[ivars = RefCell<Option<Handler>>]
        pub(super) struct PluginView;

        impl PluginView {
            #[unsafe(method(tick:))]
            fn tick(&self, _link: &CADisplayLink) {
                if self.window().is_some()
                    && let Ok(mut state) = self.ivars().try_borrow_mut()
                    && let Some(handler) = state.as_mut()
                {
                    handler.frame();
                }
            }

            #[unsafe(method(touchesBegan:withEvent:))]
            fn touches_began(&self, touches: &NSSet<UITouch>, _event: Option<&UIEvent>) {
                self.pointer(touches, PointerPhase::Down);
            }

            #[unsafe(method(touchesMoved:withEvent:))]
            fn touches_moved(&self, touches: &NSSet<UITouch>, _event: Option<&UIEvent>) {
                self.pointer(touches, PointerPhase::Drag);
            }

            #[unsafe(method(touchesEnded:withEvent:))]
            fn touches_ended(&self, touches: &NSSet<UITouch>, _event: Option<&UIEvent>) {
                self.pointer(touches, PointerPhase::Up);
            }

            #[unsafe(method(touchesCancelled:withEvent:))]
            fn touches_cancelled(&self, _touches: &NSSet<UITouch>, _event: Option<&UIEvent>) {
                self.release();
            }

            #[unsafe(method(didMoveToWindow))]
            fn moved_to_window(&self) {
                // SAFETY: Calls UIView's implementation of this exact override.
                let (): () = unsafe { msg_send![super(self), didMoveToWindow] };
                if self.window().is_none() {
                    self.release();
                }
            }
        }
    );
}

use view::PluginView;

impl PluginView {
    fn pointer(&self, touches: &NSSet<UITouch>, phase: PointerPhase) {
        if let Some(touch) = touches.anyObject()
            && let Ok(mut state) = self.ivars().try_borrow_mut()
            && let Some(handler) = state.as_mut()
        {
            let point = touch.locationInView(Some(self));
            handler.pointer(
                phase,
                (
                    point.x.to_f32().unwrap_or_default(),
                    point.y.to_f32().unwrap_or_default(),
                ),
            );
        }
    }

    fn release(&self) {
        if let Ok(mut state) = self.ivars().try_borrow_mut()
            && let Some(handler) = state.as_mut()
        {
            handler.release();
        }
    }
}

pub(in crate::plugin) struct RawEditor {
    params: Arc<PluginParams>,
    view: Option<Retained<PluginView>>,
    display_link: Option<Retained<CADisplayLink>>,
}

#[expect(
    unsafe_code,
    clippy::non_send_fields_in_send_ty,
    reason = "Truce requires Editor: Send; AUv3 invokes editor lifecycle exclusively on the main thread"
)]
// SAFETY: UIKit values are created, used, and released on the host UI thread.
// Display-link and touch callbacks are also confined to that thread.
unsafe impl Send for RawEditor {}

impl RawEditor {
    pub(in crate::plugin) const fn new(params: Arc<PluginParams>) -> Self {
        Self {
            params,
            view: None,
            display_link: None,
        }
    }
}

impl Editor for RawEditor {
    fn size(&self) -> (u32, u32) {
        SIZE
    }

    #[expect(
        unsafe_code,
        reason = "UIKit initialization, parent-view borrowing, and wgpu surface lifetimes are confined to this editor's main-thread lifecycle"
    )]
    fn open(&mut self, parent: RawWindowHandle, context: PluginContext) {
        self.close();
        let Some(main) = MainThreadMarker::new() else {
            return;
        };
        let RawWindowHandle::UiKit(ui_view) = parent else {
            return;
        };
        // SAFETY: AUv3 supplies a live UIView pointer and keeps it alive for open.
        let Some(parent) = (unsafe { ui_view.cast::<UIView>().as_ref() }) else {
            return;
        };
        let allocated = PluginView::alloc(main).set_ivars(RefCell::new(None));
        let frame = NSRect::new(
            NSPoint::new(0.0, 0.0),
            NSSize::new(f64::from(SIZE.0), f64::from(SIZE.1)),
        );
        // SAFETY: Ivars are installed before calling the UIView designated initializer.
        let view: Retained<PluginView> =
            unsafe { msg_send![super(allocated), initWithFrame: frame] };
        view.setMultipleTouchEnabled(false);
        parent.addSubview(&view);
        let instance = wgpu::Instance::new(truce_gui::platform::editor_instance_descriptor());
        let handle = UiKitWindowHandle::new(NonNull::from(&*view).cast());
        // SAFETY: view is retained until close; its renderer/surface is dropped
        // before removing/releasing the view. wgpu supplies the Metal layer.
        let surface = unsafe {
            instance.create_surface_unsafe(wgpu::SurfaceTargetUnsafe::RawHandle {
                raw_display_handle: Some(RawDisplayHandle::UiKit(UiKitDisplayHandle::new())),
                raw_window_handle: NativeHandle::UiKit(handle),
            })
        };
        let Ok(surface) = surface else {
            view.removeFromSuperview();
            return;
        };
        let scale = truce_gui::platform::query_backing_scale(&parent_handle(parent));
        let Some(renderer) = Renderer::with_surface(
            &instance,
            surface,
            truce_gui::to_physical_px(SIZE.0, scale),
            truce_gui::to_physical_px(SIZE.1, scale),
        ) else {
            view.removeFromSuperview();
            return;
        };
        *view.ivars().borrow_mut() = Some(Handler::new(
            Some(renderer),
            Arc::clone(&self.params),
            context.with_params(Arc::clone(&self.params)),
            SIZE,
        ));
        // SAFETY: tick: has the CADisplayLink target signature. The link retains
        // its target and is invalidated before the editor releases either value.
        let display_link =
            unsafe { CADisplayLink::displayLinkWithTarget_selector(&view, sel!(tick:)) };
        display_link.setPreferredFrameRateRange(CAFrameRateRange {
            minimum: 15.0,
            maximum: 30.0,
            preferred: 30.0,
        });
        // SAFETY: Both link and run loop are used on the main thread; Foundation
        // owns the common-modes constant for the process lifetime.
        unsafe {
            display_link.addToRunLoop_forMode(&NSRunLoop::mainRunLoop(), NSRunLoopCommonModes);
        }
        self.view = Some(view);
        self.display_link = Some(display_link);
    }

    fn close(&mut self) {
        if let Some(link) = self.display_link.take() {
            link.invalidate();
        }
        if let Some(view) = self.view.take() {
            view.release();
            drop(view.ivars().borrow_mut().take());
            view.removeFromSuperview();
        }
    }

    fn can_resize(&self) -> bool {
        false
    }
}

fn parent_handle(parent: &UIView) -> RawWindowHandle {
    RawWindowHandle::UiKit(NonNull::from(parent).as_ptr().cast())
}

impl Drop for RawEditor {
    fn drop(&mut self) {
        self.close();
    }
}
