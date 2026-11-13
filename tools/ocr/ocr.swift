// Offline OCR with Apple's Vision framework (on-device; no network, no model download).
// Usage: ocr <image> [<image> ...]  -> JSON lines: {"file", "width", "height", "items":[{"text","conf","x","y","w","h"}]}
// Coordinates are pixels, origin top-left.
import Foundation
import Vision
import AppKit

func recognize(_ path: String) -> [String: Any] {
    guard let img = NSImage(contentsOfFile: path),
          let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return ["file": path, "error": "cannot read image"]
    }
    let W = Double(cg.width), H = Double(cg.height)
    var items: [[String: Any]] = []
    let req = VNRecognizeTextRequest { r, _ in
        for obs in (r.results as? [VNRecognizedTextObservation]) ?? [] {
            guard let top = obs.topCandidates(1).first else { continue }
            let b = obs.boundingBox
            items.append(["text": top.string, "conf": Double(top.confidence),
                          "x": b.minX * W, "y": (1 - b.maxY) * H, "w": b.width * W, "h": b.height * H])
        }
    }
    req.recognitionLevel = .accurate
    req.usesLanguageCorrection = false          // brand names, prices and URLs must be read literally
    req.recognitionLanguages = ["en-US"]
    do { try VNImageRequestHandler(cgImage: cg, options: [:]).perform([req]) }
    catch { return ["file": path, "error": "\(error)"] }
    return ["file": path, "width": W, "height": H, "items": items]
}

for p in CommandLine.arguments.dropFirst() {
    let data = try! JSONSerialization.data(withJSONObject: recognize(p), options: [])
    print(String(data: data, encoding: .utf8)!)
}
