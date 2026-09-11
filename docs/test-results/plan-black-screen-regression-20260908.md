# Plan black-screen regression — 8 September 2026

## Reported case

- Capture: `573949f1-d2c6-429b-a279-1f7c0a8ee333`
- Floor: Roof 2 (`c3f680ae-4925-4a88-b717-4970c951e411`)
- View: `mode=track`

The plan file and proxy response were valid. The intermittent black rectangle was
caused by the plan image, SVG progress overlays, and loading state sharing one
large GPU-composited `translate3d` layer. A retained zoom also enlarged the
loading indicator inside that same layer. Cached-image completion could
additionally leave the image at zero opacity during a route transition.

## Fix

- Removed the GPU-promoting `translate3d` and `will-change` plan layer.
- Zoom/pan now uses explicit sheet dimensions and offsets while keeping the
  plan image and all normalized SVG overlays in the same coordinate space.
- Moved loading/error UI outside the zoomable sheet.
- The decoded plan is no longer hidden with an opacity gate.
- Added DOM reconciliation for cached images and a 15-second recoverable error
  state with a retry action.
- Changing floors resets loading, error, zoom, and pan state.

## Verification

All seven configured plans rendered with opacity `1`, no CSS transform, valid
natural dimensions, and no page/request errors:

- Floor 1: 2482 × 1755
- Floors 2–4: 2978 × 2105 each
- Roof 1–3: 2978 × 2105 each

The reported Roof 2 case also passed at 2.12× zoom without a transformed GPU
layer. A forced failed plan request showed the explicit error state; clicking
retry restored the 2978 × 2105 image. ESLint, TypeScript, and the Next.js
production build passed.
