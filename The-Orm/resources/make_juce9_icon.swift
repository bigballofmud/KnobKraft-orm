// Adds a small "9" badge to the KnobKraft Orm icon.
// Usage: swift badge.swift <input.png> <output.png>
import AppKit

let args = CommandLine.arguments
guard args.count == 3, let src = NSImage(contentsOfFile: args[1]),
      let srcRep = src.representations.first as? NSBitmapImageRep ?? NSBitmapImageRep(data: src.tiffRepresentation!) else {
    fputs("usage: badge.swift in.png out.png\n", stderr); exit(1)
}
let w = srcRep.pixelsWide, h = srcRep.pixelsHigh
let s = CGFloat(w) / 256.0   // design units are for a 256 px icon

// Sample the outer ring's blue so the badge matches the artwork.
let ringColour = srcRep.colorAt(x: Int(22 * s), y: h / 2) ?? NSColor(red: 0.29, green: 0.35, blue: 0.55, alpha: 1)
print("ring colour:", ringColour)

let out = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8,
                           samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                           colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: out)
let full = NSRect(x: 0, y: 0, width: w, height: h)
srcRep.draw(in: full)

// Badge in the empty bottom-right corner (AppKit origin is bottom-left).
let r = 30 * s
let centre = NSPoint(x: CGFloat(w) - 33 * s, y: 33 * s)
let badge = NSRect(x: centre.x - r, y: centre.y - r, width: 2 * r, height: 2 * r)

let shadow = NSShadow()
shadow.shadowColor = NSColor.black.withAlphaComponent(0.35)
shadow.shadowOffset = NSSize(width: 0, height: -2 * s)
shadow.shadowBlurRadius = 4 * s
NSGraphicsContext.saveGraphicsState()
shadow.set()
let disc = NSBezierPath(ovalIn: badge)
let gradient = NSGradient(starting: ringColour.blended(withFraction: 0.25, of: .white)!,
                          ending: ringColour.blended(withFraction: 0.2, of: .black)!)!
gradient.draw(in: disc, angle: -90)
NSGraphicsContext.restoreGraphicsState()

// Thin silver rim, echoing the knob.
NSColor(white: 0.85, alpha: 1).setStroke()
let rim = NSBezierPath(ovalIn: badge.insetBy(dx: 2 * s, dy: 2 * s))
rim.lineWidth = 4 * s
rim.stroke()

// The "9".
let font = NSFont.systemFont(ofSize: 40 * s, weight: .semibold)
let para = NSMutableParagraphStyle(); para.alignment = .center
let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: NSColor.white, .paragraphStyle: para]
let text = NSAttributedString(string: "9", attributes: attrs)
let size = text.size()
text.draw(in: NSRect(x: badge.minX, y: centre.y - size.height / 2 + 1 * s, width: badge.width, height: size.height))

NSGraphicsContext.restoreGraphicsState()
try! out.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: args[2]))
print("wrote", args[2], w, "x", h)
