#!/usr/bin/env python3
"""Offline mock of the generative-media providers. Zero network, zero credentials.

Validates a media job, resolves its provider route from configs/provider-routing.default.json,
and writes deterministic placeholder outputs (PNG poster, animated SVG, plan, QA stub,
checksums) to out/<job-id>/. It never reads API keys and never contacts a provider.
The QA report says "not-evaluated": a mock cannot judge motion quality.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import zlib
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
SIZES = {"16:9": (640, 360), "9:16": (360, 640), "1:1": (480, 480), "4:5": (384, 480), "3:2": (540, 360), "custom": (480, 270)}


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_json", ROOT / "scripts" / "validate-json.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def palette(job_id, seed):
    digest = hashlib.sha256(f"{job_id}:{seed}".encode()).digest()
    return [tuple(digest[i:i + 3]) for i in (0, 3, 6)]


def png(width, height, colors):
    (r1, g1, b1), (r2, g2, b2), (ra, ga, ba) = colors
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            t = (x / max(width - 1, 1) + y / max(height - 1, 1)) / 2
            pixel = (int(r1 + (r2 - r1) * t), int(g1 + (g2 - g1) * t), int(b1 + (b2 - b1) * t))
            if abs(x - width * 0.72) < 3 and y > height * 0.2:  # one sharp accent line
                pixel = (ra, ga, ba)
            rows.extend(pixel)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")


def svg(job, width, height, colors):
    c1, c2, ca = ("#%02x%02x%02x" % c for c in colors)
    seconds = max(float(job["output"]["durationSeconds"]) or 4.0, 2.0)
    label = escape(f"{job['id']} - {job['taskType']} (mock)")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient></defs>
  <rect width="100%" height="100%" fill="url(#g)"/>
  <rect x="{width * 0.72:.0f}" y="{height * 0.2:.0f}" width="6" height="{height * 0.6:.0f}" fill="{ca}">
    <animate attributeName="height" values="0;{height * 0.6:.0f};0" dur="{seconds}s" repeatCount="indefinite"/>
  </rect>
  <text x="24" y="{height - 24}" font-family="sans-serif" font-size="14" fill="#ffffff" opacity="0.85">{label}</text>
</svg>
"""


def resolve_route(job, config):
    chain = [job["routing"]["primaryProvider"]] + list(job["routing"]["fallbackProviders"])
    needs = config.get("credentialPolicy", {}).get("requiredForApiSubmit", {})
    return [{"provider": p, "credentialsNormallyRequired": needs.get(p, []), "used": False, "note": "simulated by mock-local"} for p in chain]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--out", type=Path, default=ROOT / "out")
    parser.add_argument("--seed", default="0")
    args = parser.parse_args()

    validator = load_validator()
    job = json.loads(args.job.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas/media-job.schema.json").read_text(encoding="utf-8"))
    errors = validator.validate(job, schema)
    if errors:
        print("Job rejected by schema:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    config = json.loads((ROOT / "configs/provider-routing.default.json").read_text(encoding="utf-8"))

    folder = args.out / job["id"]
    folder.mkdir(parents=True, exist_ok=True)
    width, height = SIZES[job["output"]["aspectRatios"][0]]
    colors = palette(job["id"], args.seed)
    route = resolve_route(job, config)
    route[0]["used"] = True

    files = {
        "poster.png": png(width, height, colors),
        "preview.svg": svg(job, width, height, colors).encode(),
        "resolved-job.json": (json.dumps(job, indent=2, sort_keys=True) + "\n").encode(),
        "plan.json": (json.dumps({
            "jobId": job["id"], "requestedMode": job["routing"]["mode"], "executedMode": "mock-local",
            "route": route, "networkCalls": 0, "credentialsRead": [],
            "wouldProduce": job["output"]["formats"], "realProviderOutputs": [],
        }, indent=2) + "\n").encode(),
        "qa-report.json": (json.dumps({
            "jobId": job["id"], "evaluated": False,
            "checks": {check: "not-evaluated (mock)" for check in job["qa"]["checks"]},
            "note": "Run the real checks on real output; a mock cannot assess motion quality.",
        }, indent=2) + "\n").encode(),
    }
    for name, data in files.items():
        (folder / name).write_bytes(data)
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}
    (folder / "manifest.json").write_text(json.dumps({"seed": args.seed, "sha256": manifest}, indent=2) + "\n", encoding="utf-8")
    print(f"mock job '{job['id']}': {len(files) + 1} files in {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
