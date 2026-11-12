// Optional Battle Brothers-only window decoration workaround.
// Loaded alongside the existing OpenGL facade, not injected into other apps.
// WineWindow checkTransparency in the reviewed 41303 driver:
// Confirmed against the shipped CrossOver 27.0.0.41303 x86_64 driver.
#import <Cocoa/Cocoa.h>
#import <objc/runtime.h>
#import <dispatch/dispatch.h>
#include <stdio.h>

static void (*bb_original_check)(id, SEL);
static BOOL bb_did_log;

static void bb_fix_window(NSWindow *window)
{
    if (![NSThread isMainThread]) return;
    if (![window isKindOfClass:NSClassFromString(@"WineWindow")]) return;
    if (![[window title] hasPrefix:@"Battle Brothers"]) return;
    if (!(window.styleMask & NSWindowStyleMaskTitled)) return;
    if (window.styleMask & NSWindowStyleMaskFullScreen) return;
    if (window.titlebarAppearsTransparent) window.titlebarAppearsTransparent = NO;
    if (!window.isOpaque || window.backgroundColor.alphaComponent < 1.0) {
        window.backgroundColor = NSColor.windowBackgroundColor;
        window.opaque = YES;
        [window invalidateShadow];
    }
    if (!window.isMovable) window.movable = YES;
    if (!bb_did_log) {
        fprintf(stderr, "[bb-titlebar] applied opaque native title bar to Battle Brothers\n");
        bb_did_log = YES;
    }
}

static void bb_check_transparency(id self, SEL cmd)
{
    bb_original_check(self, cmd);
    bb_fix_window((NSWindow *)self);
}

__attribute__((constructor)) static void bb_install_titlebar_fix(void)
{
    dispatch_async(dispatch_get_main_queue(), ^{
        @autoreleasepool {
            Class cls = NSClassFromString(@"WineWindow");
            Method method = cls ? class_getInstanceMethod(cls, @selector(checkTransparency)) : NULL;
            if (!method) {
                fprintf(stderr, "[bb-titlebar] WineWindow checkTransparency missing; workaround skipped\n");
                return;
            }
            bb_original_check = (void (*)(id, SEL))method_setImplementation(method, (IMP)bb_check_transparency);
            NSNotificationCenter *nc = NSNotificationCenter.defaultCenter;
            for (NSNotificationName name in @[NSWindowDidBecomeKeyNotification, NSWindowDidResizeNotification]) {
                [nc addObserverForName:name object:nil queue:NSOperationQueue.mainQueue
                    usingBlock:^(NSNotification *note) { bb_fix_window(note.object); }];
            }
            for (NSWindow *window in NSApp.windows) bb_fix_window(window);
            // A newly created game window can acquire its title after becoming key.
            // Bound the startup scan to ten seconds; later updates use the hooks above.
            for (int n = 1; n <= 20; n++) {
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, n * NSEC_PER_SEC / 2), dispatch_get_main_queue(), ^{
                    for (NSWindow *window in NSApp.windows) bb_fix_window(window);
                });
            }
            fprintf(stderr, "[bb-titlebar] window decoration workaround loaded\n");
        }
    });
}
