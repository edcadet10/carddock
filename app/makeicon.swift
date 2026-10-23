import Cocoa

// Renders the app icon (rounded blue square with an SD-card glyph) at every size iconutil needs.
let outDir = CommandLine.arguments[1]
try? FileManager.default.createDirectory(atPath: outDir, withIntermediateDirectories: true)

func render(_ px: Int) -> Data {
  let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
    samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
    bytesPerRow: 0, bitsPerPixel: 0)!
  rep.size = NSSize(width: px, height: px)
  NSGraphicsContext.saveGraphicsState()
  NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
  let s = CGFloat(px)
  let inset = s * 0.10
  let rect = NSRect(x: inset, y: inset, width: s - 2 * inset, height: s - 2 * inset)
  let shape = NSBezierPath(
    roundedRect: rect, xRadius: rect.width * 0.225, yRadius: rect.width * 0.225)
  NSGradient(
    starting: NSColor(calibratedRed: 0.16, green: 0.60, blue: 0.98, alpha: 1),
    ending: NSColor(calibratedRed: 0.04, green: 0.26, blue: 0.62, alpha: 1))!.draw(
      in: shape, angle: -90)
  if let sym = NSImage(systemSymbolName: "sdcard.fill", accessibilityDescription: nil) {
    let cfg = NSImage.SymbolConfiguration(pointSize: max(8, s * 0.40), weight: .medium)
    let img = (sym.withSymbolConfiguration(cfg) ?? sym).copy() as! NSImage
    img.isTemplate = false
    img.lockFocus()
    NSColor.white.set()
    NSRect(origin: .zero, size: img.size).fill(using: .sourceAtop)
    img.unlockFocus()
    let scale = (rect.width * 0.54) / max(img.size.width, img.size.height)
    let dsz = NSSize(width: img.size.width * scale, height: img.size.height * scale)
    let drect = NSRect(
      x: rect.midX - dsz.width / 2, y: rect.midY - dsz.height / 2, width: dsz.width,
      height: dsz.height)
    img.draw(in: drect, from: .zero, operation: .sourceOver, fraction: 1)
  }
  NSGraphicsContext.restoreGraphicsState()
  return rep.representation(using: .png, properties: [:])!
}

let sizes: [(Int, String)] = [
  (16, "icon_16x16"), (32, "icon_16x16@2x"), (32, "icon_32x32"), (64, "icon_32x32@2x"),
  (128, "icon_128x128"), (256, "icon_128x128@2x"), (256, "icon_256x256"),
  (512, "icon_256x256@2x"), (512, "icon_512x512"), (1024, "icon_512x512@2x"),
]
for (px, name) in sizes {
  try! render(px).write(to: URL(fileURLWithPath: outDir).appendingPathComponent(name + ".png"))
}
print("icons written to \(outDir)")
