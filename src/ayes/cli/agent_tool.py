"""Thin local CLI wrapper for Ayes agent-facing HTTP APIs."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ayes.app.service_control import default_service_config, ensure_service_started
from ayes.cli.helpers import to_pretty_json
from ayes.config.models import DEFAULT_SAMPLING_INTERVAL_MS


DEFAULT_BASE_URL = "http://127.0.0.1:8770"


def build_menubar_app_bundle(*, root_dir: Path, runtime_dir: Path, python_bin: str, base_url: str) -> Path:
    app_path = runtime_dir / "Ayes 菜单栏.app"
    contents_dir = app_path / "Contents"
    macos_dir = contents_dir / "MacOS"
    contents_dir.mkdir(parents=True, exist_ok=True)
    macos_dir.mkdir(parents=True, exist_ok=True)
    plist = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>Ayes 菜单栏</string>
  <key>CFBundleExecutable</key>
  <string>AyesMenubar</string>
  <key>CFBundleIdentifier</key>
  <string>com.ayes.menubar</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>AyesMenubar</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
"""
    (contents_dir / "Info.plist").write_text(plist, encoding="utf-8")
    executable_path = macos_dir / "AyesMenubar"
    source_path = macos_dir / "AyesMenubar.m"
    source_path.write_text(
        _build_native_menubar_source(base_url=base_url, runtime_dir=runtime_dir),
        encoding="utf-8",
    )
    if not _compile_native_menubar_app(output_path=executable_path, source_path=source_path):
        raise RuntimeError("无法编译 Ayes 原生菜单栏宿主")
    return app_path


def _objc_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _build_native_menubar_source(*, base_url: str, runtime_dir: Path) -> str:
    base_url_literal = _objc_literal(base_url.rstrip("/"))
    runtime_dir_literal = _objc_literal(runtime_dir.resolve().as_posix())
    return f'''#import <Cocoa/Cocoa.h>

@interface RoiSelectionView : NSView
@property(strong) NSImage *image;
@property(assign) NSRect selectionRect;
@property(assign) NSPoint dragStart;
@property(assign) BOOL dragging;
- (instancetype)initWithImage:(NSImage *)image frame:(NSRect)frame;
- (NSRect)imageDrawRect;
- (NSRect)imagePixelRectFromDisplayedSelection;
@end

@implementation RoiSelectionView
- (instancetype)initWithImage:(NSImage *)image frame:(NSRect)frame {{
    self = [super initWithFrame:frame];
    if (self) {{
        self.image = image;
        self.selectionRect = NSZeroRect;
        self.wantsLayer = YES;
        self.layer.backgroundColor = [[NSColor colorWithWhite:0.96 alpha:1.0] CGColor];
    }}
    return self;
}}
- (BOOL)isFlipped {{ return YES; }}
- (NSRect)imageDrawRect {{
    if (self.image == nil || self.image.size.width <= 0 || self.image.size.height <= 0) {{ return NSZeroRect; }}
    CGFloat padding = 12.0;
    CGFloat availableWidth = MAX(1.0, self.bounds.size.width - padding * 2.0);
    CGFloat availableHeight = MAX(1.0, self.bounds.size.height - padding * 2.0);
    CGFloat scale = MIN(availableWidth / self.image.size.width, availableHeight / self.image.size.height);
    CGFloat drawWidth = self.image.size.width * scale;
    CGFloat drawHeight = self.image.size.height * scale;
    return NSMakeRect((self.bounds.size.width - drawWidth) / 2.0, (self.bounds.size.height - drawHeight) / 2.0, drawWidth, drawHeight);
}}
- (void)drawRect:(NSRect)dirtyRect {{
    [[NSColor colorWithWhite:0.96 alpha:1.0] setFill];
    NSRectFill(self.bounds);
    NSRect drawRect = [self imageDrawRect];
    if (self.image != nil && drawRect.size.width > 0 && drawRect.size.height > 0) {{
        [self.image drawInRect:drawRect fromRect:NSZeroRect operation:NSCompositingOperationSourceOver fraction:1.0];
    }}
    if (self.selectionRect.size.width > 1 && self.selectionRect.size.height > 1) {{
        [[NSColor colorWithCalibratedRed:0.0 green:0.42 blue:1.0 alpha:0.18] setFill];
        NSBezierPath *fill = [NSBezierPath bezierPathWithRect:self.selectionRect];
        [fill fill];
        [[NSColor systemBlueColor] setStroke];
        NSBezierPath *stroke = [NSBezierPath bezierPathWithRect:self.selectionRect];
        [stroke setLineWidth:2.0];
        [stroke stroke];
    }}
}}
- (void)mouseDown:(NSEvent *)event {{
    NSPoint point = [self convertPoint:[event locationInWindow] fromView:nil];
    NSRect drawRect = [self imageDrawRect];
    if (!NSPointInRect(point, drawRect)) {{ self.selectionRect = NSZeroRect; [self setNeedsDisplay:YES]; return; }}
    self.dragStart = point;
    self.selectionRect = NSMakeRect(point.x, point.y, 0, 0);
    self.dragging = YES;
    [self setNeedsDisplay:YES];
}}
- (void)mouseDragged:(NSEvent *)event {{
    if (!self.dragging) {{ return; }}
    NSPoint point = [self convertPoint:[event locationInWindow] fromView:nil];
    NSRect drawRect = [self imageDrawRect];
    point.x = MIN(MAX(point.x, NSMinX(drawRect)), NSMaxX(drawRect));
    point.y = MIN(MAX(point.y, NSMinY(drawRect)), NSMaxY(drawRect));
    CGFloat x = MIN(self.dragStart.x, point.x);
    CGFloat y = MIN(self.dragStart.y, point.y);
    CGFloat w = fabs(point.x - self.dragStart.x);
    CGFloat h = fabs(point.y - self.dragStart.y);
    self.selectionRect = NSMakeRect(x, y, w, h);
    [self setNeedsDisplay:YES];
}}
- (void)mouseUp:(NSEvent *)event {{
    self.dragging = NO;
}}
- (NSRect)imagePixelRectFromDisplayedSelection {{
    NSRect drawRect = [self imageDrawRect];
    NSRect selected = NSIntersectionRect(self.selectionRect, drawRect);
    if (self.image == nil || selected.size.width < 2 || selected.size.height < 2 || drawRect.size.width <= 0 || drawRect.size.height <= 0) {{ return NSZeroRect; }}
    CGFloat displayScaleX = self.image.size.width / drawRect.size.width;
    CGFloat displayScaleY = self.image.size.height / drawRect.size.height;
    CGFloat x = (selected.origin.x - drawRect.origin.x) * displayScaleX;
    CGFloat y = (selected.origin.y - drawRect.origin.y) * displayScaleY;
    CGFloat w = selected.size.width * displayScaleX;
    CGFloat h = selected.size.height * displayScaleY;
    return NSMakeRect(MAX(0, floor(x)), MAX(0, floor(y)), MAX(1, round(w)), MAX(1, round(h)));
}}
@end

@interface RoiPreviewView : NSView
@property(strong) NSImage *image;
@property(assign) NSRect pixelRect;
- (instancetype)initWithImage:(NSImage *)image pixelRect:(NSRect)pixelRect frame:(NSRect)frame;
@end

@implementation RoiPreviewView
- (instancetype)initWithImage:(NSImage *)image pixelRect:(NSRect)pixelRect frame:(NSRect)frame {{
    self = [super initWithFrame:frame];
    if (self) {{ self.image = image; self.pixelRect = pixelRect; self.wantsLayer = YES; }}
    return self;
}}
- (BOOL)isFlipped {{ return YES; }}
- (void)drawRect:(NSRect)dirtyRect {{
    [[NSColor colorWithWhite:0.96 alpha:1.0] setFill];
    NSRectFill(self.bounds);
    if (self.image == nil || self.pixelRect.size.width <= 0 || self.pixelRect.size.height <= 0) {{ return; }}
    CGFloat padding = 10.0;
    CGFloat scale = MIN((self.bounds.size.width - padding * 2.0) / self.pixelRect.size.width, (self.bounds.size.height - padding * 2.0) / self.pixelRect.size.height);
    CGFloat drawWidth = self.pixelRect.size.width * scale;
    CGFloat drawHeight = self.pixelRect.size.height * scale;
    NSRect drawRect = NSMakeRect((self.bounds.size.width - drawWidth) / 2.0, (self.bounds.size.height - drawHeight) / 2.0, drawWidth, drawHeight);
    [self.image drawInRect:drawRect fromRect:self.pixelRect operation:NSCompositingOperationSourceOver fraction:1.0];
    [[NSColor systemBlueColor] setStroke];
    NSBezierPath *stroke = [NSBezierPath bezierPathWithRect:drawRect];
    [stroke setLineWidth:2.0];
    [stroke stroke];
}}
@end

@interface AyesDelegate : NSObject <NSApplicationDelegate, NSMenuDelegate>
@property(strong) NSStatusItem *statusItem;
@property(strong) NSString *baseUrl;
@property(strong) NSString *runtimeDir;
@property(strong) NSMenu *menu;
@property(assign) NSButton *visionSettingsCheckbox;
@property(assign) NSPopUpButton *visionSettingsPopup;
@end

@implementation AyesDelegate
- (void)applicationDidFinishLaunching:(NSNotification *)notification {{
    self.baseUrl = @"{base_url_literal}";
    self.runtimeDir = @"{runtime_dir_literal}";
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    self.statusItem = [[NSStatusBar systemStatusBar] statusItemWithLength:NSVariableStatusItemLength];
    NSMenu *menu = [[NSMenu alloc] init];
    menu.delegate = self;
    self.menu = menu;
    NSMenuItem *title = [[NSMenuItem alloc] initWithTitle:@"Ayes 监控控制" action:nil keyEquivalent:@""];
    [title setEnabled:NO];
    [menu addItem:title];
    [menu addItem:[NSMenuItem separatorItem]];
    self.statusItem.menu = menu;
    [self logEvent:@"menubar_started"];
    [self refreshStatus:nil];
}}
- (void)logEvent:(NSString *)message {{
    NSString *line = [NSString stringWithFormat:@"{{\\"message\\":\\"%@\\",\\"ts\\":%.3f}}\\n", message ?: @"", [[NSDate date] timeIntervalSince1970]];
    NSString *path = [self.runtimeDir stringByAppendingPathComponent:@"ayes-menubar.log"];
    NSFileHandle *handle = [NSFileHandle fileHandleForWritingAtPath:path];
    if (handle == nil) {{
        [line writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
        return;
    }}
    [handle seekToEndOfFile];
    [handle writeData:[line dataUsingEncoding:NSUTF8StringEncoding]];
    [handle closeFile];
}}
- (void)addItem:(NSString *)title action:(SEL)action toMenu:(NSMenu *)menu {{
    NSMenuItem *item = [[NSMenuItem alloc] initWithTitle:title action:action keyEquivalent:@""];
    [item setTarget:self];
    [menu addItem:item];
}}
- (void)postPath:(NSString *)path {{
    NSTask *task = [[NSTask alloc] init];
    task.launchPath = @"/usr/bin/curl";
    task.arguments = @[@"-fsS", @"-X", @"POST", [self.baseUrl stringByAppendingString:path]];
    [task launch];
}}
- (NSDictionary *)postPathSync:(NSString *)path {{
    NSURL *url = [NSURL URLWithString:[self.baseUrl stringByAppendingString:path]];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    [request setHTTPMethod:@"POST"];
    NSData *body = [@"{{}}" dataUsingEncoding:NSUTF8StringEncoding];
    [request setHTTPBody:body];
    [request setValue:@"application/json; charset=utf-8" forHTTPHeaderField:@"Content-Type"];
    NSURLResponse *response = nil;
    NSError *error = nil;
    NSData *data = [NSURLConnection sendSynchronousRequest:request returningResponse:&response error:&error];
    if (error != nil) {{ return @{{@"error": [error localizedDescription] ?: @"请求失败"}}; }}
    NSInteger statusCode = [(NSHTTPURLResponse *)response statusCode];
    NSDictionary *result = @{{}};
    if (data != nil) {{
        id parsed = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if ([parsed isKindOfClass:[NSDictionary class]]) {{ result = parsed; }}
    }}
    if (statusCode < 200 || statusCode >= 300) {{
        NSString *message = [result objectForKey:@"error"] ?: [NSString stringWithFormat:@"HTTP %ld", (long)statusCode];
        return @{{@"error": message}};
    }}
    return result;
}}
- (NSDictionary *)jsonForPath:(NSString *)path {{
    NSURL *url = [NSURL URLWithString:[self.baseUrl stringByAppendingString:path]];
    NSData *data = [NSData dataWithContentsOfURL:url];
    if (data == nil) {{ return @{{}}; }}
    NSDictionary *payload = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    return [payload isKindOfClass:[NSDictionary class]] ? payload : @{{}};
}}
- (NSString *)querySuffixForTaskId:(NSString *)taskId {{
    if (taskId == nil || [taskId length] == 0) {{ return @""; }}
    NSString *encoded = [taskId stringByAddingPercentEncodingWithAllowedCharacters:[NSCharacterSet URLQueryAllowedCharacterSet]];
    return [@"?task_id=" stringByAppendingString:encoded];
}}
- (void)postJson:(NSDictionary *)payload toPath:(NSString *)path {{
    NSURL *url = [NSURL URLWithString:[self.baseUrl stringByAppendingString:path]];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    [request setHTTPMethod:@"POST"];
    [request setValue:@"application/json; charset=utf-8" forHTTPHeaderField:@"Content-Type"];
    NSData *body = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    [request setHTTPBody:body];
    [[[NSURLSession sharedSession] dataTaskWithRequest:request] resume];
}}
- (NSDictionary *)postJsonSync:(NSDictionary *)payload toPath:(NSString *)path {{
    NSURL *url = [NSURL URLWithString:[self.baseUrl stringByAppendingString:path]];
    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    [request setHTTPMethod:@"POST"];
    [request setValue:@"application/json; charset=utf-8" forHTTPHeaderField:@"Content-Type"];
    NSData *body = [NSJSONSerialization dataWithJSONObject:payload options:0 error:nil];
    [request setHTTPBody:body];
    NSURLResponse *response = nil;
    NSError *error = nil;
    NSData *data = [NSURLConnection sendSynchronousRequest:request returningResponse:&response error:&error];
    if (error != nil) {{ return @{{@"error": [error localizedDescription] ?: @"请求失败"}}; }}
    NSInteger statusCode = [(NSHTTPURLResponse *)response statusCode];
    NSDictionary *result = @{{}};
    if (data != nil) {{
        id parsed = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if ([parsed isKindOfClass:[NSDictionary class]]) {{ result = parsed; }}
    }}
    if (statusCode < 200 || statusCode >= 300) {{
        NSString *message = [result objectForKey:@"error"] ?: [NSString stringWithFormat:@"HTTP %ld", (long)statusCode];
        return @{{@"error": message}};
    }}
    return result;
}}
- (void)showError:(NSString *)message {{
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Ayes 设置保存失败";
    alert.informativeText = message ?: @"未知错误";
    [alert addButtonWithTitle:@"知道了"];
    [alert runModal];
}}
- (void)showInfo:(NSString *)message {{
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"Ayes";
    alert.informativeText = message ?: @"";
    [alert addButtonWithTitle:@"知道了"];
    [alert runModal];
}}
- (NSString *)absolutePathForRuntimePath:(NSString *)path {{
    NSString *clean = [self safeText:path fallback:@""];
    if ([clean length] == 0) {{ return @""; }}
    if ([clean hasPrefix:@"/runtime/"]) {{
        return [self.runtimeDir stringByAppendingPathComponent:[clean substringFromIndex:[@"/runtime/" length]]];
    }}
    if ([clean hasPrefix:@"runtime/"]) {{
        return [self.runtimeDir stringByAppendingPathComponent:[clean substringFromIndex:[@"runtime/" length]]];
    }}
    return clean;
}}
- (BOOL)selectedVisionPopupItemIsVision:(NSPopUpButton *)popup {{
    id rawModel = [[popup selectedItem] representedObject];
    NSDictionary *model = [rawModel isKindOfClass:[NSDictionary class]] ? rawModel : @{{}};
    id value = [model objectForKey:@"is_vision_model"];
    return value != nil && [value respondsToSelector:@selector(boolValue)] && [value boolValue];
}}
- (void)visionSelectionChanged:(id)sender {{
    NSButton *checkbox = self.visionSettingsCheckbox;
    NSPopUpButton *popup = self.visionSettingsPopup;
    if (checkbox == nil || popup == nil) {{ return; }}
    if (checkbox.state == NSControlStateValueOn && ![self selectedVisionPopupItemIsVision:popup]) {{
        checkbox.state = NSControlStateValueOff;
        [self showInfo:@"当前选择增强模型为非视觉模型，已关闭本地模型增强。"];
    }}
}}
- (BOOL)statusBoolForKey:(NSString *)key {{
    NSDictionary *payload = [self jsonForPath:@"/api/control/status"];
    id value = [payload objectForKey:key];
    return value != nil && [value respondsToSelector:@selector(boolValue)] && [value boolValue];
}}
- (void)refreshStatus:(id)sender {{
    BOOL running = [self statusBoolForKey:@"is_running"];
    BOOL paused = [self statusBoolForKey:@"is_paused"];
    self.statusItem.button.title = paused ? @"Ayes ◐" : (running ? @"Ayes ◉" : @"Ayes ○");
    self.statusItem.button.toolTip = paused ? @"Ayes 已暂停" : (running ? @"Ayes 正在监控" : @"Ayes 未在监控");
    [self rebuildMenu];
}}
- (void)menuWillOpen:(NSMenu *)menu {{
    [self logEvent:@"menu_will_open"];
    [self refreshStatus:nil];
}}
- (void)pause:(id)sender {{ [self postPathSync:@"/api/control/pause-all"]; [self refreshStatus:nil]; }}
- (void)resume:(id)sender {{ [self postPathSync:@"/api/control/resume-all"]; [self refreshStatus:nil]; }}
- (void)openDataDir:(id)sender {{
    NSDictionary *payload = [self jsonForPath:@"/api/control/open-data-dir"];
    NSString *path = [payload objectForKey:@"task_dir"] ?: [payload objectForKey:@"data_dir"] ?: self.runtimeDir;
    NSURL *url = [NSURL fileURLWithPath:path isDirectory:YES];
    [[NSWorkspace sharedWorkspace] openURL:url];
}}
- (void)openSettings:(id)sender {{
    @try {{
        [self openSettingsForTaskId:nil];
    }} @catch (NSException *exception) {{
        [NSApp activateIgnoringOtherApps:YES];
        [self showError:[exception reason] ?: @"设置面板打开失败"];
    }}
}}
- (void)openSettingsForTaskId:(NSString *)taskId {{
    BOOL isTaskSpecificSettings = taskId != nil && [taskId length] > 0;
    NSString *settingsPath = [@"/api/control/task-settings" stringByAppendingString:[self querySuffixForTaskId:taskId]];
    NSDictionary *payload = [self jsonForPath:settingsPath];
    id rawSettings = [payload objectForKey:@"settings"];
    NSDictionary *settings = [rawSettings isKindOfClass:[NSDictionary class]] ? rawSettings : @{{}};
    id rawSampling = [settings objectForKey:@"sampling"];
    NSDictionary *sampling = [rawSampling isKindOfClass:[NSDictionary class]] ? rawSampling : @{{}};
    id rawMemory = [settings objectForKey:@"memory_policy"];
    NSDictionary *memory = [rawMemory isKindOfClass:[NSDictionary class]] ? rawMemory : @{{}};
    id rawAppSettings = [settings objectForKey:@"app_settings"];
    NSDictionary *appSettings = [rawAppSettings isKindOfClass:[NSDictionary class]] ? rawAppSettings : @{{}};
    id rawVision = [settings objectForKey:@"vision_settings"];
    NSDictionary *vision = [rawVision isKindOfClass:[NSDictionary class]] ? rawVision : @{{}};
    NSString *resolvedTaskId = isTaskSpecificSettings ? taskId : @"";
    double interval = [[sampling objectForKey:@"interval_sec"] respondsToSelector:@selector(doubleValue)] ? [[sampling objectForKey:@"interval_sec"] doubleValue] : 6.0;
    NSString *quality = [sampling objectForKey:@"quality"] ?: @"standard";
    BOOL saveScreenshots = ![[sampling objectForKey:@"save_ocr_screenshots"] respondsToSelector:@selector(boolValue)] || [[sampling objectForKey:@"save_ocr_screenshots"] boolValue];
    NSInteger shortDays = [[memory objectForKey:@"short_term_retain_days"] respondsToSelector:@selector(integerValue)] ? [[memory objectForKey:@"short_term_retain_days"] integerValue] : 7;
    NSInteger longDays = [[memory objectForKey:@"long_term_retain_days"] respondsToSelector:@selector(integerValue)] ? [[memory objectForKey:@"long_term_retain_days"] integerValue] : 14;
    BOOL disableCleanup = [[memory objectForKey:@"disable_auto_cleanup"] respondsToSelector:@selector(boolValue)] && [[memory objectForKey:@"disable_auto_cleanup"] boolValue];
    BOOL virtualSleep = [[appSettings objectForKey:@"capture_screen_when_display_sleep"] respondsToSelector:@selector(boolValue)] && [[appSettings objectForKey:@"capture_screen_when_display_sleep"] boolValue];
    NSInteger cleanupDays = [[appSettings objectForKey:@"cleanup_reminder_days"] respondsToSelector:@selector(integerValue)] ? [[appSettings objectForKey:@"cleanup_reminder_days"] integerValue] : 7;
    NSString *hotkey = [appSettings objectForKey:@"latest_frame_hotkey"] ?: @"";
    BOOL visionEnabled = [[vision objectForKey:@"enabled"] respondsToSelector:@selector(boolValue)] && [[vision objectForKey:@"enabled"] boolValue];
    NSString *visionModel = [vision objectForKey:@"model"] ?: @"qwen2.5vl:7b";
    NSDictionary *visionModelsPayload = [self jsonForPath:@"/api/vision/models"];
    id rawVisionModelItems = [visionModelsPayload objectForKey:@"items"];
    NSArray *visionModelItems = [rawVisionModelItems isKindOfClass:[NSArray class]] ? rawVisionModelItems : @[];
    NSString *defaultVisionModel = [visionModelsPayload objectForKey:@"default_selected_model"] ?: visionModel;

    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = isTaskSpecificSettings ? [@"Ayes 设置 · " stringByAppendingString:resolvedTaskId] : @"Ayes 设置";
    alert.informativeText = isTaskSpecificSettings ? @"采样和记忆写入该任务专属配置；增强、快捷键和清理提醒为本机通用配置。" : @"当前为全局设置；不会覆盖任务专属采样和记忆配置。";
    [alert addButtonWithTitle:@"保存"];
    [alert addButtonWithTitle:@"取消"];

    NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 430, 360)];
    NSTextField *intervalLabel = [NSTextField labelWithString:@"采样间隔（秒）"];
    intervalLabel.frame = NSMakeRect(0, 324, 120, 22);
    NSTextField *intervalField = [[NSTextField alloc] initWithFrame:NSMakeRect(140, 320, 90, 28)];
    intervalField.stringValue = [NSString stringWithFormat:@"%.1f", interval];

    NSTextField *qualityLabel = [NSTextField labelWithString:@"采样质量"];
    qualityLabel.frame = NSMakeRect(0, 286, 120, 22);
    NSPopUpButton *qualityPopup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(140, 282, 190, 28)];
    NSArray *items = @[@[@"原始质量", @"original"], @[@"标准质量 1920", @"standard"], @[@"节省空间 1280", @"space_saver"], @[@"极省空间 960", @"ultra_saver"]];
    for (NSArray *item in items) {{
        [qualityPopup addItemWithTitle:item[0]];
        [[qualityPopup lastItem] setRepresentedObject:item[1]];
        if ([quality isEqualToString:item[1]]) {{ [qualityPopup selectItem:[qualityPopup lastItem]]; }}
    }}

    NSButton *saveCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(136, 246, 220, 24)];
    [saveCheckbox setButtonType:NSSwitchButton];
    saveCheckbox.title = @"保存 OCR 原始截图";
    saveCheckbox.state = saveScreenshots ? NSControlStateValueOn : NSControlStateValueOff;

    NSTextField *shortLabel = [NSTextField labelWithString:@"短期详细记忆（天）"];
    shortLabel.frame = NSMakeRect(0, 208, 130, 22);
    NSTextField *shortField = [[NSTextField alloc] initWithFrame:NSMakeRect(140, 204, 90, 28)];
    shortField.stringValue = [NSString stringWithFormat:@"%ld", (long)shortDays];

    NSTextField *longLabel = [NSTextField labelWithString:@"长期简略记忆（天）"];
    longLabel.frame = NSMakeRect(0, 170, 130, 22);
    NSTextField *longField = [[NSTextField alloc] initWithFrame:NSMakeRect(140, 166, 90, 28)];
    longField.stringValue = [NSString stringWithFormat:@"%ld", (long)longDays];

    NSButton *cleanupCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(136, 132, 250, 24)];
    [cleanupCheckbox setButtonType:NSSwitchButton];
    cleanupCheckbox.title = @"不自动清理该任务记忆";
    cleanupCheckbox.state = disableCleanup ? NSControlStateValueOn : NSControlStateValueOff;

    NSButton *visionCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(136, 94, 150, 24)];
    [visionCheckbox setButtonType:NSSwitchButton];
    visionCheckbox.title = @"本地大模型增强";
    visionCheckbox.state = visionEnabled ? NSControlStateValueOn : NSControlStateValueOff;
    NSPopUpButton *visionPopup = [[NSPopUpButton alloc] initWithFrame:NSMakeRect(286, 90, 135, 32)];
    BOOL didSelectVisionModel = NO;
    for (NSDictionary *model in visionModelItems) {{
        NSString *name = [model objectForKey:@"name"] ?: @"";
        if ([name length] == 0) {{ continue; }}
        BOOL isVisionModel = [[model objectForKey:@"is_vision_model"] respondsToSelector:@selector(boolValue)] && [[model objectForKey:@"is_vision_model"] boolValue];
        NSString *title = isVisionModel ? name : [name stringByAppendingString:@"（非视觉）"];
        [visionPopup addItemWithTitle:title];
        [[visionPopup lastItem] setRepresentedObject:model];
        if (!didSelectVisionModel && ([name isEqualToString:defaultVisionModel] || [name isEqualToString:visionModel])) {{
            [visionPopup selectItem:[visionPopup lastItem]];
            didSelectVisionModel = YES;
        }}
    }}
    if ([visionPopup numberOfItems] == 0) {{
        NSDictionary *fallbackModel = @{{@"name": @"", @"is_vision_model": @NO}};
        [visionPopup addItemWithTitle:@"未发现 Ollama 模型"];
        [[visionPopup lastItem] setRepresentedObject:fallbackModel];
    }} else if (!didSelectVisionModel && [visionPopup numberOfItems] > 0) {{
        [visionPopup selectItemAtIndex:0];
    }}
    [visionPopup setTarget:self];
    [visionPopup setAction:@selector(visionSelectionChanged:)];
    [visionCheckbox setTarget:self];
    [visionCheckbox setAction:@selector(visionSelectionChanged:)];
    self.visionSettingsCheckbox = visionCheckbox;
    self.visionSettingsPopup = visionPopup;
    [self visionSelectionChanged:visionCheckbox];

    NSTextField *hotkeyLabel = [NSTextField labelWithString:@"截图快捷键"];
    hotkeyLabel.frame = NSMakeRect(0, 56, 120, 22);
    NSTextField *hotkeyField = [[NSTextField alloc] initWithFrame:NSMakeRect(140, 52, 120, 28)];
    hotkeyField.stringValue = hotkey;
    NSTextField *cleanupDaysLabel = [NSTextField labelWithString:@"清理提醒（天）"];
    cleanupDaysLabel.frame = NSMakeRect(270, 56, 90, 22);
    NSTextField *cleanupDaysField = [[NSTextField alloc] initWithFrame:NSMakeRect(360, 52, 60, 28)];
    cleanupDaysField.stringValue = [NSString stringWithFormat:@"%ld", (long)cleanupDays];

    NSButton *sleepCheckbox = [[NSButton alloc] initWithFrame:NSMakeRect(136, 16, 260, 24)];
    [sleepCheckbox setButtonType:NSSwitchButton];
    sleepCheckbox.title = @"整屏熄屏时尝试虚拟屏幕监控";
    sleepCheckbox.state = virtualSleep ? NSControlStateValueOn : NSControlStateValueOff;

    [view addSubview:intervalLabel];
    [view addSubview:intervalField];
    [view addSubview:qualityLabel];
    [view addSubview:qualityPopup];
    [view addSubview:saveCheckbox];
    [view addSubview:shortLabel];
    [view addSubview:shortField];
    [view addSubview:longLabel];
    [view addSubview:longField];
    [view addSubview:cleanupCheckbox];
    [view addSubview:visionCheckbox];
    [view addSubview:visionPopup];
    [view addSubview:hotkeyLabel];
    [view addSubview:hotkeyField];
    [view addSubview:cleanupDaysLabel];
    [view addSubview:cleanupDaysField];
    [view addSubview:sleepCheckbox];
    alert.accessoryView = view;

    [NSApp activateIgnoringOtherApps:YES];
    NSModalResponse response = [alert runModal];
    if (response != NSAlertFirstButtonReturn) {{ return; }}
    double nextIntervalSec = [intervalField doubleValue];
    if (nextIntervalSec < 0.5) {{ nextIntervalSec = 0.5; }}
    if (nextIntervalSec > 3600.0) {{ nextIntervalSec = 3600.0; }}
    NSInteger shortDaysValue = [shortField integerValue];
    if (shortDaysValue < 1) {{ shortDaysValue = 1; }}
    if (shortDaysValue > 14) {{ shortDaysValue = 14; }}
    NSInteger longDaysValue = [longField integerValue];
    if (longDaysValue < 1) {{ longDaysValue = 1; }}
    if (longDaysValue > 30) {{ longDaysValue = 30; }}
    NSInteger cleanupDaysValue = [cleanupDaysField integerValue];
    if (cleanupDaysValue < 1) {{ cleanupDaysValue = 1; }}
    NSMutableDictionary *next = [@{{
        @"interval_ms": @((NSInteger)round(nextIntervalSec * 1000.0)),
        @"quality": [[qualityPopup selectedItem] representedObject] ?: @"standard",
        @"save_ocr_screenshots": saveCheckbox.state == NSControlStateValueOn ? @YES : @NO
    }} mutableCopy];
    if (isTaskSpecificSettings) {{
        [next setObject:resolvedTaskId forKey:@"task_id"];
        NSDictionary *samplingResult = [self postJsonSync:next toPath:@"/api/control/sampling"];
        if ([samplingResult objectForKey:@"error"] != nil) {{
            [self showError:[samplingResult objectForKey:@"error"]];
            return;
        }}
        NSString *encoded = [resolvedTaskId stringByAddingPercentEncodingWithAllowedCharacters:[NSCharacterSet URLPathAllowedCharacterSet]];
        NSDictionary *memoryResult = [self postJsonSync:@{{
            @"short_term_retain_days": @(shortDaysValue),
            @"long_term_retain_days": @(longDaysValue),
            @"disable_auto_cleanup": cleanupCheckbox.state == NSControlStateValueOn ? @YES : @NO
        }} toPath:[@"/api/tasks/" stringByAppendingFormat:@"%@/memory-policy", encoded]];
        if ([memoryResult objectForKey:@"error"] != nil) {{
            [self showError:[memoryResult objectForKey:@"error"]];
            return;
        }}
    }}
    NSDictionary *settingsResult = [self postJsonSync:@{{
        @"capture_screen_when_display_sleep": sleepCheckbox.state == NSControlStateValueOn ? @YES : @NO,
        @"cleanup_reminder_days": @(cleanupDaysValue),
        @"latest_frame_hotkey": hotkeyField.stringValue ?: @""
    }} toPath:@"/api/control/settings"];
    if ([settingsResult objectForKey:@"error"] != nil) {{
        [self showError:[settingsResult objectForKey:@"error"]];
        return;
    }}
    if (visionCheckbox.state == NSControlStateValueOn && ![self selectedVisionPopupItemIsVision:visionPopup]) {{
        visionCheckbox.state = NSControlStateValueOff;
        [self showInfo:@"当前选择增强模型为非视觉模型，已关闭本地模型增强。"];
    }}
    NSDictionary *selectedVisionModel = [[visionPopup selectedItem] representedObject] ?: @{{}};
    NSString *selectedVisionModelName = [selectedVisionModel objectForKey:@"name"] ?: @"";
    NSDictionary *visionResult = [self postJsonSync:@{{
        @"enabled": visionCheckbox.state == NSControlStateValueOn ? @YES : @NO,
        @"provider": @"ollama",
        @"model": selectedVisionModelName,
        @"auto_use_when_available": @YES
    }} toPath:@"/api/vision/settings"];
    if ([visionResult objectForKey:@"error"] != nil) {{
        [self showError:[visionResult objectForKey:@"error"]];
        return;
    }}
    if ([visionResult objectForKey:@"warning"] != nil) {{
        [self showInfo:[visionResult objectForKey:@"warning"]];
    }}
    [self refreshStatus:nil];
}}
- (void)quit:(id)sender {{ [NSApp terminate:nil]; }}
- (NSString *)safeText:(id)value fallback:(NSString *)fallback {{
    if (value == nil || value == [NSNull null]) {{ return fallback ?: @""; }}
    NSString *text = [NSString stringWithFormat:@"%@", value];
    text = [text stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    return [text length] > 0 ? text : (fallback ?: @"");
}}
- (NSString *)targetDetailText:(NSDictionary *)target {{
    for (NSString *key in @[@"window_title", @"title", @"target_label", @"process_id"]) {{
        NSString *value = [self safeText:[target objectForKey:key] fallback:@""];
        if ([value length] > 0) {{
            return [value length] > 36 ? [value substringToIndex:36] : value;
        }}
    }}
    return @"";
}}
- (NSArray *)titleBitsForTarget:(NSDictionary *)target {{
    if (![target isKindOfClass:[NSDictionary class]]) {{ return @[]; }}
    NSString *targetType = [self safeText:[target objectForKey:@"type"] fallback:@""];
    if ([targetType isEqualToString:@"screen"]) {{
        NSString *screenId = [self safeText:[target objectForKey:@"screen_id"] fallback:@"默认"];
        return @[@"全屏监控", [@"屏幕 " stringByAppendingString:screenId]];
    }}
    if ([targetType isEqualToString:@"process"]) {{
        NSMutableArray *bits = [NSMutableArray arrayWithObjects:@"进程监控", [self safeText:[target objectForKey:@"process_name"] fallback:@"未知进程"], nil];
        NSString *detail = [self targetDetailText:target];
        if ([detail length] > 0) {{ [bits addObject:detail]; }}
        return bits;
    }}
    if ([targetType isEqualToString:@"window"]) {{
        NSMutableArray *bits = [NSMutableArray arrayWithObject:@"窗口监控"];
        NSString *detail = [self targetDetailText:target];
        if ([detail length] == 0) {{ detail = [self safeText:[target objectForKey:@"window_id"] fallback:@""]; }}
        if ([detail length] > 0) {{ [bits addObject:detail]; }}
        return bits;
    }}
    return @[];
}}
- (NSString *)titleForTask:(NSDictionary *)task {{
    if (![task isKindOfClass:[NSDictionary class]]) {{ return @"未知任务"; }}
    NSString *taskId = [self safeText:[task objectForKey:@"task_id"] fallback:@"未知任务"];
    id rawTarget = [task objectForKey:@"target"];
    if (![rawTarget isKindOfClass:[NSDictionary class]]) {{
        id rawSpec = [task objectForKey:@"spec"];
        if ([rawSpec isKindOfClass:[NSDictionary class]]) {{ rawTarget = [rawSpec objectForKey:@"target"]; }}
    }}
    NSArray *targetBits = [self titleBitsForTarget:[rawTarget isKindOfClass:[NSDictionary class]] ? rawTarget : @{{}}];
    if ([targetBits count] > 0) {{
        NSMutableArray *parts = [NSMutableArray arrayWithObject:taskId];
        [parts addObjectsFromArray:targetBits];
        return [parts componentsJoinedByString:@" · "];
    }}
    NSString *mode = [self safeText:[task objectForKey:@"mode"] fallback:@""];
    return [mode length] > 0 ? [NSString stringWithFormat:@"%@ · %@", taskId, mode] : taskId;
}}
- (void)addTaskSubmenuWithTask:(NSDictionary *)task toMenu:(NSMenu *)menu allTasks:(NSArray *)allTasks {{
    NSString *taskId = [self safeText:[task objectForKey:@"task_id"] fallback:@""];
    if (taskId == nil || [taskId length] == 0) {{ return; }}
    NSString *taskTitle = [self titleForTask:task];
    NSMenuItem *taskItem = [[NSMenuItem alloc] initWithTitle:taskTitle action:nil keyEquivalent:@""];
    NSMenu *submenu = [[NSMenu alloc] init];
    NSMenuItem *startItem = [[NSMenuItem alloc] initWithTitle:@"启动 / 继续此任务" action:@selector(startTask:) keyEquivalent:@""];
    [startItem setTarget:self];
    [startItem setRepresentedObject:taskId];
    [submenu addItem:startItem];
    [submenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem *openItem = [[NSMenuItem alloc] initWithTitle:@"打开任务目录" action:@selector(openTaskDir:) keyEquivalent:@""];
    [openItem setTarget:self];
    [openItem setRepresentedObject:taskId];
    [submenu addItem:openItem];
    NSMenuItem *settingsItem = [[NSMenuItem alloc] initWithTitle:@"专属设置..." action:@selector(openTaskSettings:) keyEquivalent:@""];
    [settingsItem setTarget:self];
    [settingsItem setRepresentedObject:taskId];
    [submenu addItem:settingsItem];
    BOOL isRoiTask = [[self safeText:[task objectForKey:@"parent_task_id"] fallback:@""] length] > 0;
    if (!isRoiTask) {{
        NSMenuItem *roiEditorItem = [[NSMenuItem alloc] initWithTitle:@"设定 ROI..." action:@selector(openRoiEditor:) keyEquivalent:@""];
        [roiEditorItem setTarget:self];
        [roiEditorItem setRepresentedObject:taskId];
        [submenu addItem:roiEditorItem];
        NSMutableArray *children = [NSMutableArray array];
        if ([allTasks isKindOfClass:[NSArray class]]) {{
            for (NSDictionary *candidate in allTasks) {{
                if (![candidate isKindOfClass:[NSDictionary class]]) {{ continue; }}
                NSString *parentId = [self safeText:[candidate objectForKey:@"parent_task_id"] fallback:@""];
                if ([parentId isEqualToString:taskId]) {{ [children addObject:candidate]; }}
            }}
        }}
        if ([children count] > 0) {{
            NSMenuItem *roiRootItem = [[NSMenuItem alloc] initWithTitle:@"ROI 子任务" action:nil keyEquivalent:@""];
            NSMenu *roiMenu = [[NSMenu alloc] init];
            for (NSDictionary *child in children) {{
                NSString *childId = [self safeText:[child objectForKey:@"task_id"] fallback:@""];
                if ([childId length] == 0) {{ continue; }}
                NSDictionary *roi = [[child objectForKey:@"roi"] isKindOfClass:[NSDictionary class]] ? [child objectForKey:@"roi"] : @{{}};
                BOOL enabled = ![[roi objectForKey:@"enabled"] respondsToSelector:@selector(boolValue)] || [[roi objectForKey:@"enabled"] boolValue];
                NSString *childTitle = [NSString stringWithFormat:@"%@ %@", enabled ? @"✓" : @"○", [self titleForTask:child]];
                NSMenuItem *childItem = [[NSMenuItem alloc] initWithTitle:childTitle action:nil keyEquivalent:@""];
                NSMenu *childMenu = [[NSMenu alloc] init];
                NSMenuItem *childStart = [[NSMenuItem alloc] initWithTitle:@"启动 / 继续此 ROI" action:@selector(startTask:) keyEquivalent:@""];
                [childStart setTarget:self];
                [childStart setRepresentedObject:childId];
                [childMenu addItem:childStart];
                NSMenuItem *childOpen = [[NSMenuItem alloc] initWithTitle:@"打开 ROI 目录" action:@selector(openTaskDir:) keyEquivalent:@""];
                [childOpen setTarget:self];
                [childOpen setRepresentedObject:childId];
                [childMenu addItem:childOpen];
                NSMenuItem *childSettings = [[NSMenuItem alloc] initWithTitle:@"专属设置..." action:@selector(openTaskSettings:) keyEquivalent:@""];
                [childSettings setTarget:self];
                [childSettings setRepresentedObject:childId];
                [childMenu addItem:childSettings];
                [childItem setSubmenu:childMenu];
                [roiMenu addItem:childItem];
            }}
            [roiRootItem setSubmenu:roiMenu];
            [submenu addItem:roiRootItem];
        }}
    }}
    [taskItem setSubmenu:submenu];
    [menu addItem:taskItem];
}}
- (void)rebuildMenu {{
    [self.menu removeAllItems];
    BOOL running = [self statusBoolForKey:@"is_running"];
    BOOL paused = [self statusBoolForKey:@"is_paused"];
    NSDictionary *statusPayload = [self jsonForPath:@"/api/control/status"];
    NSString *currentTaskId = [self safeText:[statusPayload objectForKey:@"task_id"] fallback:@""];
    NSDictionary *tasksPayload = [self jsonForPath:@"/api/tasks?limit=5"];
    NSArray *tasks = [tasksPayload objectForKey:@"items"];
    NSDictionary *currentTask = nil;
    if ([tasks isKindOfClass:[NSArray class]]) {{
        for (NSDictionary *task in tasks) {{
            if (![task isKindOfClass:[NSDictionary class]]) {{ continue; }}
            NSString *taskId = [self safeText:[task objectForKey:@"task_id"] fallback:@""];
            if ([taskId isEqualToString:[self safeText:currentTaskId fallback:@""]]) {{
                currentTask = task;
                break;
            }}
        }}
    }}
    if (currentTask == nil && [currentTaskId length] > 0) {{
        id rawStatusTarget = [statusPayload objectForKey:@"target"];
        NSDictionary *statusTarget = [rawStatusTarget isKindOfClass:[NSDictionary class]] ? rawStatusTarget : @{{}};
        currentTask = @{{@"task_id": currentTaskId, @"target": statusTarget, @"mode": [self safeText:[statusPayload objectForKey:@"mode"] fallback:@""]}};
    }}
    NSMenuItem *title = [[NSMenuItem alloc] initWithTitle:(paused ? @"Ayes 已暂停" : (running ? @"Ayes 监控中" : @"Ayes 未监控")) action:nil keyEquivalent:@""];
    [title setEnabled:NO];
    [self.menu addItem:title];
    if ((running || paused) && currentTask != nil) {{
        [self addTaskSubmenuWithTask:currentTask toMenu:self.menu allTasks:tasks];
    }}
    [self.menu addItem:[NSMenuItem separatorItem]];
    [self addItem:@"刷新状态" action:@selector(refreshStatus:) toMenu:self.menu];
    [self addItem:(paused ? @"继续上次的监控" : (running ? @"暂停监控" : @"继续上次的监控")) action:(paused ? @selector(resume:) : (running ? @selector(pause:) : @selector(resume:))) toMenu:self.menu];
    [self addItem:@"打开当前任务目录" action:@selector(openDataDir:) toMenu:self.menu];
    [self.menu addItem:[NSMenuItem separatorItem]];
    if ([tasks isKindOfClass:[NSArray class]] && [tasks count] > 0) {{
        NSMenuItem *tasksTitle = [[NSMenuItem alloc] initWithTitle:@"最近任务" action:nil keyEquivalent:@""];
        [tasksTitle setEnabled:NO];
        [self.menu addItem:tasksTitle];
        for (NSDictionary *task in tasks) {{
            if (![task isKindOfClass:[NSDictionary class]]) {{ continue; }}
            NSString *parentId = [self safeText:[task objectForKey:@"parent_task_id"] fallback:@""];
            if ([parentId length] > 0) {{ continue; }}
            [self addTaskSubmenuWithTask:task toMenu:self.menu allTasks:tasks];
        }}
        [self.menu addItem:[NSMenuItem separatorItem]];
    }}
    [self addItem:@"设置..." action:@selector(openSettings:) toMenu:self.menu];
    [self addItem:@"退出控制面" action:@selector(quit:) toMenu:self.menu];
}}
- (void)openTaskDir:(NSMenuItem *)sender {{
    NSString *taskId = [sender representedObject];
    if (taskId == nil) {{ [self openDataDir:sender]; return; }}
    NSString *encoded = [taskId stringByAddingPercentEncodingWithAllowedCharacters:[NSCharacterSet URLQueryAllowedCharacterSet]];
    NSDictionary *payload = [self jsonForPath:[@"/api/control/open-data-dir?task_id=" stringByAppendingString:encoded]];
    NSString *path = [payload objectForKey:@"task_dir"] ?: [payload objectForKey:@"data_dir"] ?: self.runtimeDir;
    [[NSWorkspace sharedWorkspace] openURL:[NSURL fileURLWithPath:path isDirectory:YES]];
}}
- (void)startTask:(NSMenuItem *)sender {{
    NSString *taskId = [sender representedObject];
    if (taskId == nil || [taskId length] == 0) {{ return; }}
    NSDictionary *switchResult = [self postJsonSync:@{{@"task_id": taskId}} toPath:@"/api/watch/switch-task"];
    if ([switchResult objectForKey:@"error"] != nil) {{
        [self showError:[switchResult objectForKey:@"error"]];
        return;
    }}
    NSDictionary *startResult = [self postPathSync:@"/api/watch/start"];
    if ([startResult objectForKey:@"error"] != nil) {{
        [self showError:[startResult objectForKey:@"error"]];
        return;
    }}
    [self refreshStatus:nil];
}}
- (void)openRoiEditor:(NSMenuItem *)sender {{
    NSString *taskId = [sender representedObject];
    if (taskId == nil || [taskId length] == 0) {{ return; }}
    NSString *queryTaskId = [taskId stringByAddingPercentEncodingWithAllowedCharacters:[NSCharacterSet URLQueryAllowedCharacterSet]];
    NSDictionary *screenshotPayload = [self jsonForPath:[@"/api/screenshot?task_id=" stringByAppendingString:queryTaskId ?: @""]];
    NSString *rawPath = [self safeText:[screenshotPayload objectForKey:@"path"] fallback:@""];
    NSString *imagePath = [self absolutePathForRuntimePath:rawPath];
    NSImage *image = [[NSImage alloc] initWithContentsOfFile:imagePath];
    if (image == nil) {{
        [NSApp activateIgnoringOtherApps:YES];
        [self showError:@"无法读取当前任务最新截图，不能创建 ROI。请先启动或运行一次该任务。"];
        return;
    }}
    CGFloat maxWidth = 760.0;
    CGFloat maxHeight = 520.0;
    CGFloat scale = MIN(maxWidth / image.size.width, maxHeight / image.size.height);
    if (scale > 1.0) {{ scale = 1.0; }}
    NSRect viewFrame = NSMakeRect(0, 0, MAX(360.0, image.size.width * scale + 24.0), MAX(260.0, image.size.height * scale + 24.0));
    RoiSelectionView *selectionView = [[RoiSelectionView alloc] initWithImage:image frame:viewFrame];

    NSAlert *selectAlert = [[NSAlert alloc] init];
    selectAlert.messageText = @"创建 ROI";
    selectAlert.informativeText = @"请拖拽框选 ROI 区域。进程任务会按当前截图目标坐标保存；全屏任务会按屏幕截图坐标保存。";
    selectAlert.accessoryView = selectionView;
    [selectAlert addButtonWithTitle:@"下一步"];
    [selectAlert addButtonWithTitle:@"取消"];
    [NSApp activateIgnoringOtherApps:YES];
    if ([selectAlert runModal] != NSAlertFirstButtonReturn) {{ return; }}

    NSRect pixelRect = [selectionView imagePixelRectFromDisplayedSelection];
    if (pixelRect.size.width < 3 || pixelRect.size.height < 3) {{
        [self showError:@"ROI 框选区域太小或为空，请重新框选。"];
        return;
    }}

    NSTextField *nameField = [[NSTextField alloc] initWithFrame:NSMakeRect(0, 0, 320, 28)];
    nameField.placeholderString = @"例如：价格监控、播放器区域、弹幕区";
    RoiPreviewView *previewView = [[RoiPreviewView alloc] initWithImage:image pixelRect:pixelRect frame:NSMakeRect(0, 42, 360, 180)];
    NSTextField *nameLabel = [NSTextField labelWithString:@"ROI 名称"];
    nameLabel.frame = NSMakeRect(0, 222, 80, 22);
    NSTextField *coordLabel = [NSTextField labelWithString:[NSString stringWithFormat:@"保存坐标：x=%ld y=%ld w=%ld h=%ld coordinate_space=target", (long)pixelRect.origin.x, (long)pixelRect.origin.y, (long)pixelRect.size.width, (long)pixelRect.size.height]];
    coordLabel.frame = NSMakeRect(0, 28, 360, 18);
    NSView *confirmView = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 360, 244)];
    nameField.frame = NSMakeRect(82, 218, 278, 28);
    [confirmView addSubview:nameLabel];
    [confirmView addSubview:nameField];
    [confirmView addSubview:previewView];
    [confirmView addSubview:coordLabel];

    NSAlert *confirmAlert = [[NSAlert alloc] init];
    confirmAlert.messageText = @"ROI 预览确认";
    confirmAlert.informativeText = @"确认预览区域和坐标无误后再创建。";
    confirmAlert.accessoryView = confirmView;
    [confirmAlert addButtonWithTitle:@"创建 ROI"];
    [confirmAlert addButtonWithTitle:@"取消"];
    if ([confirmAlert runModal] != NSAlertFirstButtonReturn) {{ return; }}
    NSString *roiName = [self safeText:nameField.stringValue fallback:@""];
    if ([roiName length] == 0) {{
        [self showError:@"ROI 名称不能为空。"];
        return;
    }}

    NSString *regionIdBase = [roiName stringByAddingPercentEncodingWithAllowedCharacters:[NSCharacterSet alphanumericCharacterSet]];
    if ([regionIdBase length] == 0) {{ regionIdBase = @"custom"; }}
    NSString *regionId = [@"roi_" stringByAppendingString:regionIdBase];
    NSString *encodedPathTaskId = [taskId stringByAddingPercentEncodingWithAllowedCharacters:[NSCharacterSet URLPathAllowedCharacterSet]];
    NSString *roiPath = [@"/api/tasks/" stringByAppendingFormat:@"%@/roi", encodedPathTaskId ?: @""];
    NSDictionary *payload = @{{
        @"roi_name": roiName,
        @"region": @{{
            @"region_id": regionId,
            @"name": roiName,
            @"x": @((NSInteger)pixelRect.origin.x),
            @"y": @((NSInteger)pixelRect.origin.y),
            @"w": @((NSInteger)pixelRect.size.width),
            @"h": @((NSInteger)pixelRect.size.height),
            @"coordinate_space": @"target",
            @"enabled": @YES
        }},
        @"enabled": @YES
    }};
    NSDictionary *result = [self postJsonSync:payload toPath:roiPath];
    if ([result objectForKey:@"error"] != nil) {{
        [self showError:[result objectForKey:@"error"]];
        return;
    }}
    [self showInfo:[NSString stringWithFormat:@"ROI 已创建：%@", roiName]];
    [self refreshStatus:nil];
}}
- (void)openTaskSettings:(NSMenuItem *)sender {{
    NSString *taskId = [sender representedObject];
    @try {{
        [self openSettingsForTaskId:taskId];
    }} @catch (NSException *exception) {{
        [NSApp activateIgnoringOtherApps:YES];
        [self showError:[exception reason] ?: @"专属设置面板打开失败"];
    }}
}}
@end

int main(int argc, const char * argv[]) {{
    @autoreleasepool {{
        NSApplication *app = [NSApplication sharedApplication];
        AyesDelegate *delegate = [[AyesDelegate alloc] init];
        app.delegate = delegate;
        [app run];
    }}
    return 0;
}}
'''


def _compile_native_menubar_app(*, output_path: Path, source_path: Path) -> bool:
    clang = shutil.which("clang")
    if not clang:
        return False
    result = subprocess.run(
        [clang, str(source_path), "-framework", "AppKit", "-framework", "Foundation", "-o", str(output_path)],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    output_path.chmod(0o755)
    return True


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _build_query_path(path: str, **query: Any) -> str:
    filtered = {key: value for key, value in query.items() if value is not None}
    if not filtered:
        return path
    return f"{path}?{urlencode(filtered, doseq=True)}"


def _path_segment(value: Any) -> str:
    return quote(str(value or "").strip(), safe="")


def _request_json(base_url: str, path: str, *, method: str = "GET", payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    normalized_base_url = _normalize_base_url(base_url)
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(f"{normalized_base_url}{path}", data=body, method=method, headers=headers)
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"请求失败: {method} {path} -> HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"请求失败: {method} {path} -> {exc.reason}") from exc
    except OSError as exc:
        raise RuntimeError(f"请求失败: {method} {path} -> {exc}") from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"响应不是合法 JSON: {method} {path}") from exc


def ensure_local_service_started(base_url: str) -> Dict[str, Any]:
    normalized_base_url = _normalize_base_url(base_url)
    if normalized_base_url != DEFAULT_BASE_URL:
        payload = _request_json(normalized_base_url, "/api/status")
        return {
            "status": "service_ready",
            "base_url": normalized_base_url,
            "service": "remote_checked",
            "status_payload": payload,
        }
    config = default_service_config()
    result = ensure_service_started(config)
    status_payload = _request_json(normalized_base_url, "/api/status")
    return {
        "status": "service_ready",
        "base_url": normalized_base_url,
        "service": result,
        "status_payload": status_payload,
    }


def ensure_local_menubar_started() -> Dict[str, Any]:
    if os.environ.get("AYES_AUTO_MENUBAR", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"status": "disabled"}
    if sys.platform != "darwin":
        return {"status": "skipped", "reason": "not_macos"}
    config = default_service_config()
    config.runtime_dir.mkdir(parents=True, exist_ok=True)
    pid_file = config.runtime_dir / "ayes-menubar.pid"
    existing_pid = None
    if pid_file.exists():
        try:
            existing_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing_pid = None
    if _is_native_menubar_pid(existing_pid):
        return {"status": "reused", "pid": existing_pid}
    discovered = _find_running_menubar_pid()
    if discovered is not None:
        pid_file.write_text(str(discovered), encoding="utf-8")
        return {"status": "reused", "pid": discovered, "source": "pgrep"}
    log_file = config.runtime_dir / "ayes-menubar.log"
    try:
        app_path = build_menubar_app_bundle(
            root_dir=config.root_dir,
            runtime_dir=config.runtime_dir,
            python_bin=config.python_bin,
            base_url=DEFAULT_BASE_URL,
        )
        subprocess.run(["open", "-g", str(app_path)], check=True)
        return {"status": "started", "launch": "app", "app_path": str(app_path), "log_file": str(log_file)}
    except Exception as exc:  # pragma: no cover - defensive startup path
        return {"status": "failed", "error": str(exc), "launch": "app", "log_file": str(log_file)}


def _find_running_menubar_pid() -> Optional[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "AyesMenubar|Ayes 菜单栏.app"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    for raw in result.stdout.splitlines():
        try:
            pid = int(raw.strip())
        except ValueError:
            continue
        if pid != os.getpid():
            return pid
    return None


def _is_native_menubar_pid(pid: Optional[int]) -> bool:
    if pid is None:
        return False
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    command = result.stdout.strip()
    return result.returncode == 0 and ("AyesMenubar" in command or "Ayes 菜单栏.app" in command)


def _build_target_payload(args: argparse.Namespace) -> Dict[str, Any]:
    target_type = args.target_type
    if target_type == "screen":
        return {"type": "screen", "screen_id": args.screen_id}
    if target_type == "window":
        if args.window_id is None:
            raise RuntimeError("target_type=window 时必须提供 --window-id")
        return {"type": "window", "window_id": args.window_id}
    if target_type == "process":
        if not args.process_name:
            raise RuntimeError("target_type=process 时必须提供 --process-name")
        return {"type": "process", "process_name": args.process_name}
    raise RuntimeError(f"不支持的 target_type: {target_type}")


def _build_optional_target_payload(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    target_type = getattr(args, "target_type", None)
    if not target_type:
        return None
    return _build_target_payload(args)


def _build_load_spec_payload(args: argparse.Namespace) -> Dict[str, Any]:
    queries = [item for item in (args.query or []) if str(item).strip()]
    payload: Dict[str, Any] = {
        "task_id": args.task_id,
        "spec_version": args.spec_version,
        "mode": args.mode,
        "target": _build_target_payload(args),
        "sampling": {
            "screenshot_interval_ms": args.screenshot_interval_ms,
            "ocr_interval_ms": args.ocr_interval_ms,
            "change_detection_interval_ms": args.change_detection_interval_ms,
            "max_fps": args.max_fps,
            "skip_ocr_when_no_change": bool(args.skip_ocr_when_no_change),
            "quality": args.quality,
            "save_ocr_screenshots": _parse_optional_bool(args.save_ocr_screenshots),
        },
        "watch_intent": {
            "enabled": bool(queries),
            "queries": queries,
        },
    }
    if args.long_term_hours is not None:
        payload["memory"] = {"long_term_hours": args.long_term_hours}
    if args.webhook_url:
        payload["alert"] = {
            "enabled": True,
            "channel": "wecom_webhook",
            "webhook_url": args.webhook_url,
        }
    if args.enable_vision:
        payload["vision"] = {"enabled": True, "provider": args.vision_provider, "model": args.vision_model}
    return payload


def _build_plan_spec_payload(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_id": args.task_id,
        "prompt": args.prompt,
    }
    target = _build_optional_target_payload(args)
    if target is not None:
        payload["target"] = target
    if args.webhook_url:
        payload["webhook_url"] = args.webhook_url
    return payload


def _load_json_file(path_str: str, *, label: str) -> Dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        raise RuntimeError(f"{label} 不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} 不是合法 JSON: {path}") from exc


def _build_region_bind_capture_ref(*, base_url: str, args: argparse.Namespace, plan: Dict[str, Any]) -> Dict[str, Any]:
    if args.capture_id and args.image_path and args.image_width is not None and args.image_height is not None:
        return {
            "capture_id": args.capture_id,
            "image_path": args.image_path,
            "image_width": args.image_width,
            "image_height": args.image_height,
        }
    task_id = str(plan.get("task_id") or "").strip() or None
    screenshot_path = _build_query_path("/api/screenshot", task_id=task_id)
    screenshot_payload = _request_json(base_url, screenshot_path)
    image_path = str(screenshot_payload.get("path") or "").strip()
    image_width = screenshot_payload.get("image_width")
    image_height = screenshot_payload.get("image_height")
    if not image_path or image_width is None or image_height is None:
        raise RuntimeError("缺少 region-bind 所需截图信息，请先执行 run-once/observe-live 生成最近截图，或显式提供 --capture-id --image-path --image-width --image-height")
    capture_id = str(args.capture_id or f"cap_{task_id or 'latest'}").strip()
    return {
        "capture_id": capture_id,
        "image_path": image_path,
        "image_width": int(image_width),
        "image_height": int(image_height),
    }


def _parse_optional_bool(raw: Optional[str]) -> Optional[bool]:
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise RuntimeError(f"无法识别布尔值: {raw}")


def _build_confirm_plan_payload(args: argparse.Namespace) -> Dict[str, Any]:
    plan_path = Path(args.plan_file)
    if not plan_path.exists():
        raise RuntimeError(f"plan_file 不存在: {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"plan_file 不是合法 JSON: {plan_path}") from exc
    confirmations: Dict[str, Any] = {}
    if args.webhook_url:
        confirmations["webhook_url"] = args.webhook_url
    if args.alert_message_title:
        confirmations["alert_message_title"] = str(args.alert_message_title).strip()
    if args.alert_message_template:
        confirmations["alert_message_template"] = str(args.alert_message_template).strip()
    target = _build_optional_target_payload(args)
    if target is not None:
        confirmations["target"] = target
    if args.use_entire_target:
        confirmations["use_entire_target"] = True
    if args.region_intent:
        confirmations["region_intents"] = [_parse_region_intent(item) for item in args.region_intent]
    if args.region_binding:
        confirmations["region_bindings"] = [_parse_region_binding(item) for item in args.region_binding]
    if args.refresh_click_enabled:
        confirmations["refresh_click_enabled"] = True
    if args.refresh_click_interval_sec is not None:
        confirmations["refresh_click_interval_sec"] = args.refresh_click_interval_sec
    if args.refresh_click_coordinate_space is not None:
        confirmations["refresh_click_coordinate_space"] = args.refresh_click_coordinate_space
    if args.refresh_click_point:
        confirmations["refresh_click_point"] = _parse_point(args.refresh_click_point, field_name="refresh_click_point")
    return {"plan": plan, "confirmations": confirmations}


def _parse_region_intent(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        raise RuntimeError("region_intent 不能为空")
    if ":" in text:
        name, purpose = text.split(":", 1)
    elif "：" in text:
        name, purpose = text.split("：", 1)
    else:
        name, purpose = text, ""
    name = name.strip()
    purpose = purpose.strip()
    if not name:
        raise RuntimeError("region_intent 名称不能为空")
    return {"name": name, "purpose": purpose, "required": True, "status": "needs_binding"}


def _parse_region_binding(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    parts = text.split("|")
    if len(parts) != 9:
        raise RuntimeError("region_binding 必须是 region_intent_id|region_id|name|x|y|w|h|coordinate_space|source")
    region_intent_id, region_id, name, x, y, w, h, coordinate_space, source = [item.strip() for item in parts]
    if not region_intent_id or not region_id or not name:
        raise RuntimeError("region_binding 的 region_intent_id、region_id、name 不能为空")
    return {
        "region_intent_id": region_intent_id,
        "region_id": region_id,
        "name": name,
        "x": int(x),
        "y": int(y),
        "w": int(w),
        "h": int(h),
        "coordinate_space": coordinate_space or "target",
        "source": source or "manual_coordinates",
    }


def _parse_roi_region(raw: str) -> Dict[str, Any]:
    text = str(raw or "").strip()
    parts = [item.strip() for item in text.split("|")]
    if len(parts) != 7:
        raise RuntimeError("region 必须是 region_id|name|x|y|w|h|coordinate_space")
    region_id, name, x, y, w, h, coordinate_space = parts
    if not region_id or not name:
        raise RuntimeError("region_id 和 name 不能为空")
    try:
        return {
            "region_id": region_id,
            "name": name,
            "x": int(x),
            "y": int(y),
            "w": int(w),
            "h": int(h),
            "coordinate_space": coordinate_space or "target",
        }
    except ValueError as exc:
        raise RuntimeError("region 坐标必须是整数") from exc


def _parse_point(raw: str, *, field_name: str) -> Dict[str, int]:
    text = str(raw or "").strip()
    parts = [item.strip() for item in text.split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RuntimeError(f"{field_name} 必须是 x,y 形式")
    try:
        x = int(parts[0])
        y = int(parts[1])
    except ValueError as exc:
        raise RuntimeError(f"{field_name} 必须是整数坐标") from exc
    return {"x": x, "y": y}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ayes-agent", description="Ayes 面向智能体的本地薄工具")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="本地 Ayes HTTP 服务地址")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("ensure-service", help="确保本地 Ayes 服务可达")
    subparsers.add_parser("contracts", help="读取智能体接口契约")
    subparsers.add_parser("status", help="读取当前监控状态")
    subparsers.add_parser("targets", help="读取目标候选摘要")
    tasks_parser = subparsers.add_parser("tasks", help="读取已持久化任务列表")
    tasks_parser.add_argument("--limit", type=int, default=100)
    roi_parser = subparsers.add_parser("roi", help="读取或修改任务 ROI 子任务")
    roi_subparsers = roi_parser.add_subparsers(dest="roi_command", required=True)
    roi_list_parser = roi_subparsers.add_parser("list", help="列出某个主任务下的 ROI 子任务")
    roi_list_parser.add_argument("--task-id", required=True)
    roi_create_parser = roi_subparsers.add_parser("create", help="创建命名 ROI 子任务")
    roi_create_parser.add_argument("--task-id", required=True)
    roi_create_parser.add_argument("--roi-task-id", default=None)
    roi_create_parser.add_argument("--roi-name", required=True)
    roi_create_parser.add_argument("--region", required=True, help="region_id|name|x|y|w|h|coordinate_space")
    roi_create_parser.add_argument("--enabled", default="true")
    roi_update_parser = roi_subparsers.add_parser("update", help="更新 ROI 子任务名称、启用状态或区域")
    roi_update_parser.add_argument("--task-id", required=True)
    roi_update_parser.add_argument("--roi-task-id", required=True)
    roi_update_parser.add_argument("--roi-name", default=None)
    roi_update_parser.add_argument("--region", default=None, help="region_id|name|x|y|w|h|coordinate_space")
    roi_update_parser.add_argument("--enabled", default=None)
    roi_delete_parser = roi_subparsers.add_parser("delete", help="删除 ROI 子任务及其目录")
    roi_delete_parser.add_argument("--task-id", required=True)
    roi_delete_parser.add_argument("--roi-task-id", required=True)
    task_alert_parser = subparsers.add_parser("task-alert", help="读取或更新任务/ROI 的企业微信 webhook 通知配置")
    task_alert_parser.add_argument("--task-id", required=True)
    task_alert_parser.add_argument("--enabled", default=None)
    task_alert_parser.add_argument("--webhook-url", default=None)
    task_alert_parser.add_argument("--message-title", default=None)
    task_alert_parser.add_argument("--message-template", default=None)
    task_alert_parser.add_argument("--priority-threshold", choices=["low", "medium", "high"], default=None)
    task_alert_parser.add_argument("--cooldown-sec", type=int, default=None)
    task_alert_parser.add_argument("--dedupe-window-sec", type=int, default=None)
    memory_policy_parser = subparsers.add_parser("memory-policy", help="读取或更新指定任务的记忆保留策略")
    memory_policy_parser.add_argument("--task-id", required=True)
    memory_policy_parser.add_argument("--short-term-days", type=int, default=None)
    memory_policy_parser.add_argument("--long-term-days", type=int, default=None)
    memory_policy_parser.add_argument("--disable-auto-cleanup", default=None)
    memory_cleanup_parser = subparsers.add_parser("memory-cleanup", help="按指定任务策略执行一次记忆清理")
    memory_cleanup_parser.add_argument("--task-id", required=True)
    sampling_parser = subparsers.add_parser("sampling", help="读取或更新当前任务采样策略")
    sampling_parser.add_argument("--task-id", default=None)
    sampling_parser.add_argument("--interval-sec", type=float, default=None)
    sampling_parser.add_argument("--interval-ms", type=float, default=None)
    sampling_parser.add_argument("--quality", choices=["original", "standard", "space_saver", "ultra_saver"], default=None)
    sampling_parser.add_argument("--save-ocr-screenshots", default=None)
    subparsers.add_parser("start", help="启动当前已装载的持续监控")
    subparsers.add_parser("run-once", help="执行一次即时采样")
    subparsers.add_parser("stop", help="停止当前持续监控")
    switch_task_parser = subparsers.add_parser("switch-task", help="切换并恢复指定历史任务")
    switch_task_parser.add_argument("--task-id", required=True)
    delete_task_parser = subparsers.add_parser("delete-task", help="删除指定任务及其长短期记忆")
    delete_task_parser.add_argument("--task-id", required=True)
    plan_parser = subparsers.add_parser("plan-spec", help="根据自然语言生成 watch spec 草案")
    plan_parser.add_argument("--task-id", required=True)
    plan_parser.add_argument("--prompt", required=True)
    plan_parser.add_argument("--target-type", choices=["screen", "window", "process"], default=None)
    plan_parser.add_argument("--screen-id", type=int, default=1)
    plan_parser.add_argument("--window-id", type=int, default=None)
    plan_parser.add_argument("--process-name", default=None)
    plan_parser.add_argument("--webhook-url", default=None)

    confirm_plan_parser = subparsers.add_parser("confirm-plan", help="确认任务草案并装载监控任务")
    confirm_plan_parser.add_argument("--plan-file", required=True)
    confirm_plan_parser.add_argument("--target-type", choices=["screen", "window", "process"], default=None)
    confirm_plan_parser.add_argument("--screen-id", type=int, default=1)
    confirm_plan_parser.add_argument("--window-id", type=int, default=None)
    confirm_plan_parser.add_argument("--process-name", default=None)
    confirm_plan_parser.add_argument("--webhook-url", default=None)
    confirm_plan_parser.add_argument("--alert-message-title", default=None)
    confirm_plan_parser.add_argument("--alert-message-template", default=None)
    confirm_plan_parser.add_argument("--use-entire-target", action="store_true")
    confirm_plan_parser.add_argument("--region-intent", action="append", default=[])
    confirm_plan_parser.add_argument("--region-binding", action="append", default=[])
    confirm_plan_parser.add_argument("--refresh-click-enabled", action="store_true")
    confirm_plan_parser.add_argument("--refresh-click-interval-sec", type=int, default=None)
    confirm_plan_parser.add_argument("--refresh-click-coordinate-space", choices=["window", "screen"], default=None)
    confirm_plan_parser.add_argument("--refresh-click-point", default=None, help="刷新点击点，格式 x,y")

    task_parser = subparsers.add_parser("task", help="读取指定任务快照")
    task_parser.add_argument("--task-id", required=True, help="任务 ID")

    recent_parser = subparsers.add_parser("recent", help="读取近期时间线事件")
    recent_parser.add_argument("--task-id", default=None)
    recent_parser.add_argument("--minutes", type=int, default=5)
    recent_parser.add_argument("--limit", type=int, default=20)

    observe_live_parser = subparsers.add_parser("observe-live", help="读取面向 agent 的实时屏幕观察上下文")
    observe_live_parser.add_argument("--task-id", default=None)
    observe_live_parser.add_argument("--minutes", type=int, default=5)
    observe_live_parser.add_argument("--limit", type=int, default=20)

    activity_parser = subparsers.add_parser("activity", help="读取轻量近期活动摘要，默认用于回答最近在做什么")
    activity_parser.add_argument("--task-id", default=None)
    activity_parser.add_argument("--minutes", type=int, default=5)

    alerts_parser = subparsers.add_parser("alerts", help="读取最近告警审计结果")
    alerts_parser.add_argument("--task-id", default=None)
    alerts_parser.add_argument("--minutes", type=int, default=15)
    alerts_parser.add_argument("--limit", type=int, default=20)

    control_parser = subparsers.add_parser("control", help="读取或变更后台控制状态")
    control_subparsers = control_parser.add_subparsers(dest="control_command", required=True)
    control_subparsers.add_parser("status", help="读取后台控制状态")
    control_subparsers.add_parser("pause-all", help="暂停全部监控任务")
    control_subparsers.add_parser("resume-all", help="恢复全部监控任务")
    control_subparsers.add_parser("open-data-dir", help="读取运行数据目录信息")
    control_subparsers.add_parser("menubar", help="启动 macOS 原生菜单栏控制面")
    cleanup_reminder_parser = control_subparsers.add_parser("cleanup-reminder", help="更新清理提醒状态")
    cleanup_reminder_parser.add_argument("--suppress-forever", default=None)
    cleanup_reminder_parser.add_argument("--snoozed-until", type=float, default=None)
    cleanup_reminder_parser.add_argument("--last-prompt-at", type=float, default=None)
    cleanup_reminder_parser.add_argument("--next-check-after-days", type=int, default=None)
    cleanup_reminder_check_parser = control_subparsers.add_parser("cleanup-reminder-check", help="执行一次清理提醒到期检查")
    cleanup_reminder_check_parser.add_argument("--now", type=float, default=None)

    vision_parser = subparsers.add_parser("vision", help="读取或变更本地视觉增强状态")
    vision_subparsers = vision_parser.add_subparsers(dest="vision_command", required=True)
    vision_subparsers.add_parser("models", help="读取本地视觉模型与 Ollama 可达性")
    vision_prepare_parser = vision_subparsers.add_parser("prepare", help="仅在用户明确要求启用本地视觉增强时执行就绪检查")
    vision_prepare_parser.add_argument("--requested-by", default="agent_enable_local_vision")
    vision_subparsers.add_parser("status", help="读取本地视觉增强配置")
    vision_enable_parser = vision_subparsers.add_parser("enable", help="启用本地视觉增强")
    vision_enable_parser.add_argument("--provider", default="ollama")
    vision_enable_parser.add_argument("--model", required=True)
    vision_enable_parser.add_argument("--auto-use-when-available", default=None)
    vision_subparsers.add_parser("disable", help="关闭本地视觉增强")

    subparsers.add_parser("region-bind-contract", help="读取正式 region-bind 合同")

    region_bind_request_parser = subparsers.add_parser("region-bind-request", help="生成正式 region-bind request")
    region_bind_request_parser.add_argument("--plan-file", required=True)
    region_bind_request_parser.add_argument("--capture-id", default=None)
    region_bind_request_parser.add_argument("--image-path", default=None)
    region_bind_request_parser.add_argument("--image-width", type=int, default=None)
    region_bind_request_parser.add_argument("--image-height", type=int, default=None)

    region_bind_result_parser = subparsers.add_parser("region-bind-result", help="提交正式 region-bind result")
    region_bind_result_parser.add_argument("--result-file", required=True)

    long_term_parser = subparsers.add_parser("long-term", help="读取长期摘要")
    long_term_parser.add_argument("--task-id", default=None)
    long_term_parser.add_argument("--hours", type=int, default=None)
    long_term_parser.add_argument("--limit", type=int, default=20)

    screenshot_parser = subparsers.add_parser("screenshot", help="读取最近截图与 ROI 覆盖信息")
    screenshot_parser.add_argument("--task-id", default=None)

    ask_parser = subparsers.add_parser("ask", help="对近期或长期记忆发起提问")
    ask_parser.add_argument("--task-id", default=None)
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument("--minutes", type=int, default=5)
    ask_parser.add_argument("--hours", type=int, default=None)

    memory_items_parser = subparsers.add_parser("memory-items", help="读取短期记忆明细")
    memory_items_parser.add_argument("--task-id", default=None)
    memory_items_parser.add_argument("--minutes", type=int, default=5)
    memory_items_parser.add_argument("--limit", type=int, default=20)
    memory_items_parser.add_argument("--keyword", default=None)
    memory_items_parser.add_argument("--compact", action="store_true", help="兼容旧用法；memory-items 默认已启用紧凑输出")
    memory_items_parser.add_argument("--raw", action="store_true", help="显式读取完整原始事件结构，仅用于排障或位置证据")

    logs_parser = subparsers.add_parser("logs", help="读取近期日志")
    logs_parser.add_argument("--task-id", default=None)
    logs_parser.add_argument("--minutes", type=int, default=15)
    logs_parser.add_argument("--category", default=None)

    load_spec_parser = subparsers.add_parser("load-spec", help="装载最小 watch spec")
    load_spec_parser.add_argument("--task-id", required=True)
    load_spec_parser.add_argument("--spec-version", default="1.0")
    load_spec_parser.add_argument("--mode", default="observe", choices=["observe", "triggered"])
    load_spec_parser.add_argument("--target-type", required=True, choices=["screen", "window", "process"])
    load_spec_parser.add_argument("--screen-id", type=int, default=1)
    load_spec_parser.add_argument("--window-id", type=int, default=None)
    load_spec_parser.add_argument("--process-name", default=None)
    load_spec_parser.add_argument("--query", action="append", default=[])
    load_spec_parser.add_argument("--screenshot-interval-ms", type=int, default=DEFAULT_SAMPLING_INTERVAL_MS)
    load_spec_parser.add_argument("--ocr-interval-ms", type=int, default=DEFAULT_SAMPLING_INTERVAL_MS)
    load_spec_parser.add_argument("--change-detection-interval-ms", type=int, default=DEFAULT_SAMPLING_INTERVAL_MS)
    load_spec_parser.add_argument("--max-fps", type=int, default=2)
    load_spec_parser.add_argument("--skip-ocr-when-no-change", action="store_true")
    load_spec_parser.add_argument("--quality", choices=["original", "standard", "space_saver", "ultra_saver"], default="standard")
    load_spec_parser.add_argument("--save-ocr-screenshots", default="false")
    load_spec_parser.add_argument("--long-term-hours", type=int, default=None)
    load_spec_parser.add_argument("--webhook-url", default=None)
    load_spec_parser.add_argument("--enable-vision", action="store_true")
    load_spec_parser.add_argument("--vision-provider", default="ollama")
    load_spec_parser.add_argument("--vision-model", default=None)
    return parser


def _dispatch(args: argparse.Namespace) -> Dict[str, Any]:
    base_url = _normalize_base_url(args.base_url)
    if args.command == "ensure-service":
        result = ensure_local_service_started(base_url)
        if isinstance(result, dict):
            return result
        return {"status": "service_ready", "base_url": base_url}
    if args.command == "contracts":
        return _request_json(base_url, "/api/agent/contracts")
    if args.command == "status":
        return _request_json(base_url, "/api/watch/status")
    if args.command == "targets":
        return _request_json(base_url, "/api/targets")
    if args.command == "tasks":
        path = _build_query_path("/api/tasks", limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "roi":
        encoded_task_id = _path_segment(args.task_id)
        if args.roi_command == "list":
            return _request_json(base_url, f"/api/tasks/{encoded_task_id}/roi")
        if args.roi_command == "create":
            payload = {
                "roi_task_id": args.roi_task_id,
                "roi_name": args.roi_name,
                "region": _parse_roi_region(args.region),
                "enabled": _parse_optional_bool(args.enabled),
            }
            payload = {key: value for key, value in payload.items() if value is not None}
            return _request_json(base_url, f"/api/tasks/{encoded_task_id}/roi", method="POST", payload=payload)
        if args.roi_command == "update":
            payload = {
                "roi_name": args.roi_name,
                "region": _parse_roi_region(args.region) if args.region else None,
                "enabled": _parse_optional_bool(args.enabled),
            }
            payload = {key: value for key, value in payload.items() if value is not None}
            return _request_json(base_url, f"/api/tasks/{encoded_task_id}/roi/{_path_segment(args.roi_task_id)}", method="PATCH", payload=payload)
        if args.roi_command == "delete":
            return _request_json(base_url, f"/api/tasks/{encoded_task_id}/roi/{_path_segment(args.roi_task_id)}", method="DELETE")
        raise RuntimeError(f"未知 roi 命令: {args.roi_command}")
    if args.command == "task-alert":
        payload = {
            "enabled": _parse_optional_bool(args.enabled),
            "webhook_url": args.webhook_url,
            "message_title": args.message_title,
            "message_template": args.message_template,
            "priority_threshold": args.priority_threshold,
            "cooldown_sec": args.cooldown_sec,
            "dedupe_window_sec": args.dedupe_window_sec,
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        if payload:
            return _request_json(base_url, f"/api/tasks/{_path_segment(args.task_id)}/alert", method="POST", payload=payload)
        return _request_json(base_url, f"/api/tasks/{_path_segment(args.task_id)}/alert")
    if args.command == "memory-policy":
        path = f"/api/tasks/{_path_segment(args.task_id)}/memory-policy"
        payload = {
            "short_term_retain_days": args.short_term_days,
            "long_term_retain_days": args.long_term_days,
            "disable_auto_cleanup": _parse_optional_bool(args.disable_auto_cleanup),
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        if payload:
            return _request_json(base_url, path, method="POST", payload=payload)
        return _request_json(base_url, path)
    if args.command == "memory-cleanup":
        return _request_json(base_url, f"/api/tasks/{_path_segment(args.task_id)}/memory-cleanup", method="POST", payload={})
    if args.command == "sampling":
        if args.interval_sec is not None and args.interval_ms is not None:
            raise RuntimeError("--interval-sec 和 --interval-ms 只能选择一个")
        payload = {}
        if args.interval_sec is not None:
            payload["interval_ms"] = args.interval_sec * 1000
        if args.interval_ms is not None:
            payload["interval_ms"] = args.interval_ms
        if args.task_id is not None:
            payload["task_id"] = args.task_id
        if args.quality is not None:
            payload["quality"] = args.quality
        save_ocr_screenshots = _parse_optional_bool(args.save_ocr_screenshots)
        if save_ocr_screenshots is not None:
            payload["save_ocr_screenshots"] = save_ocr_screenshots
        if payload:
            return _request_json(base_url, "/api/control/sampling", method="POST", payload=payload)
        return _request_json(base_url, _build_query_path("/api/control/sampling", task_id=args.task_id))
    if args.command == "plan-spec":
        return _request_json(base_url, "/api/agent/plan-watch-spec", method="POST", payload=_build_plan_spec_payload(args))
    if args.command == "confirm-plan":
        return _request_json(base_url, "/api/watch/confirm-plan", method="POST", payload=_build_confirm_plan_payload(args))
    if args.command == "switch-task":
        return _request_json(base_url, "/api/watch/switch-task", method="POST", payload={"task_id": args.task_id})
    if args.command == "delete-task":
        return _request_json(base_url, f"/api/watch/task/{_path_segment(args.task_id)}", method="DELETE")
    if args.command == "start":
        result = _request_json(base_url, "/api/watch/start", method="POST", payload={})
        if base_url == DEFAULT_BASE_URL:
            result = dict(result)
            result["menubar"] = ensure_local_menubar_started()
        return result
    if args.command == "run-once":
        return _request_json(base_url, "/api/watch/run-once", method="POST", payload={})
    if args.command == "stop":
        return _request_json(base_url, "/api/watch/stop", method="POST", payload={})
    if args.command == "task":
        return _request_json(base_url, f"/api/watch/task/{_path_segment(args.task_id)}")
    if args.command == "recent":
        path = _build_query_path("/api/timeline/recent", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "observe-live":
        path = _build_query_path("/api/agent/observe-live", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "activity":
        path = _build_query_path("/api/activity", task_id=args.task_id, minutes=args.minutes)
        return _request_json(base_url, path)
    if args.command == "alerts":
        path = _build_query_path("/api/alerts/recent", task_id=args.task_id, minutes=args.minutes, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "control":
        if args.control_command == "status":
            return _request_json(base_url, "/api/control/status")
        if args.control_command == "pause-all":
            return _request_json(base_url, "/api/control/pause-all", method="POST", payload={})
        if args.control_command == "resume-all":
            return _request_json(base_url, "/api/control/resume-all", method="POST", payload={})
        if args.control_command == "open-data-dir":
            return _request_json(base_url, "/api/control/open-data-dir")
        if args.control_command == "menubar":
            return ensure_local_menubar_started()
        if args.control_command == "cleanup-reminder":
            payload = {
                "suppress_forever": _parse_optional_bool(args.suppress_forever),
                "snoozed_until": args.snoozed_until,
                "last_prompt_at": args.last_prompt_at,
                "next_check_after_days": args.next_check_after_days,
            }
            payload = {key: value for key, value in payload.items() if value is not None}
            return _request_json(base_url, "/api/control/cleanup-reminder", method="POST", payload=payload)
        if args.control_command == "cleanup-reminder-check":
            payload = {"now": args.now} if args.now is not None else {}
            return _request_json(base_url, "/api/control/cleanup-reminder/check", method="POST", payload=payload)
        raise RuntimeError(f"未知 control 命令: {args.control_command}")
    if args.command == "vision":
        if args.vision_command == "models":
            return _request_json(base_url, "/api/vision/models")
        if args.vision_command == "prepare":
            return _request_json(
                base_url,
                "/api/vision/prepare",
                method="POST",
                payload={"requested_by": args.requested_by},
            )
        if args.vision_command == "status":
            return _request_json(base_url, "/api/vision/settings")
        if args.vision_command == "enable":
            payload = {
                "enabled": True,
                "provider": args.provider,
                "model": args.model,
            }
            auto_use_when_available = _parse_optional_bool(args.auto_use_when_available)
            if auto_use_when_available is not None:
                payload["auto_use_when_available"] = auto_use_when_available
            return _request_json(base_url, "/api/vision/settings", method="POST", payload=payload)
        if args.vision_command == "disable":
            return _request_json(base_url, "/api/vision/settings", method="POST", payload={"enabled": False})
        raise RuntimeError(f"未知 vision 命令: {args.vision_command}")
    if args.command == "region-bind-contract":
        return _request_json(base_url, "/api/agent/region-bind-contract")
    if args.command == "region-bind-request":
        plan = _load_json_file(args.plan_file, label="plan_file")
        payload = {
            "plan": plan,
            "capture_ref": _build_region_bind_capture_ref(base_url=base_url, args=args, plan=plan),
        }
        return _request_json(base_url, "/api/agent/region-bind-request", method="POST", payload=payload)
    if args.command == "region-bind-result":
        payload = _load_json_file(args.result_file, label="result_file")
        return _request_json(base_url, "/api/agent/region-bind-result", method="POST", payload=payload)
    if args.command == "long-term":
        path = _build_query_path("/api/timeline/long-term", task_id=args.task_id, hours=args.hours, limit=args.limit)
        return _request_json(base_url, path)
    if args.command == "screenshot":
        path = _build_query_path("/api/screenshot", task_id=args.task_id)
        return _request_json(base_url, path)
    if args.command == "ask":
        path = _build_query_path("/api/ask", task_id=args.task_id, question=args.question, minutes=args.minutes, hours=args.hours)
        return _request_json(base_url, path)
    if args.command == "memory-items":
        compact = False if args.raw else True
        path = _build_query_path("/api/memory/items", task_id=args.task_id, minutes=args.minutes, limit=args.limit, keyword=args.keyword, compact=compact)
        return _request_json(base_url, path)
    if args.command == "logs":
        path = _build_query_path("/api/logs", task_id=args.task_id, category=args.category, minutes=args.minutes)
        return _request_json(base_url, path)
    if args.command == "load-spec":
        payload = _build_load_spec_payload(args)
        return _request_json(base_url, "/api/watch/load-configured", method="POST", payload=payload)
    raise RuntimeError(f"未知命令: {args.command}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = _dispatch(args)
    except RuntimeError as exc:
        print(to_pretty_json({"error": str(exc)}))
        return 1
    if payload is None:
        payload = {"status": "service_ready", "base_url": _normalize_base_url(args.base_url)}
    print(to_pretty_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
