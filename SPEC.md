# SNTV wire protocol — version 4 (SNTV 1.0)

SNTV ("Sentinel Video") carries an already-encoded H.264 or HEVC video stream
from a sender (a simulator, a robot, a GPU encoder) to a single receiver (a VR
headset, a monitoring tool) over one TCP connection, with as little in between
as possible: no RTP, no jitter buffer, no SDP. Each frame travels with its
capture timestamp and, optionally, the pose of the camera that rendered it, so
the receiver can reproject the image against the viewer's current head pose.

It was designed for teleoperating a robot from a VR headset over a USB cable or
a LAN, where WebRTC's machinery (pacing, jitter buffers, upload of every frame
through the CPU on mobile) added latency and capped resolution. If you need to
cross the internet, NAT or lossy Wi-Fi, use WebRTC instead.

All integers and floats are **little endian**. `f32` is IEEE-754 single
precision.

## Connection

1. The sender listens on a TCP port; the receiver connects. The receiver
   should set `TCP_NODELAY` and a large receive buffer (several MB).
2. The sender writes one **stream header**, then **frames** until either side
   closes the connection. There is no back-channel: the receiver never writes.
3. The first frame after the header is an IDR and carries the parameter sets
   (VPS/SPS/PPS) in band, so the decoder needs no out-of-band configuration.
4. A sender serves one receiver at a time. When the receiver cannot keep up, the
   sender drops queued frames and sends an IDR next, instead of buffering:
   late video is worse than skipped video for teleoperation.

## Stream header

| Offset | Type | Field | Meaning |
|---:|---|---|---|
| 0 | 4 bytes | `magic` | ASCII `SNTV` |
| 4 | u32 | `version` | `4` for this document |
| 8 | u32 | `header_size` | Total header size in bytes, from `magic` on. `48` in 4.0. A receiver reads `header_size` bytes and ignores the ones it does not know, so fields can be appended without a new version. |
| 12 | u32 | `width` | Encoded picture width in pixels |
| 16 | u32 | `height` | Encoded picture height in pixels |
| 20 | u32 | `codec` | `1` H.264, `2` HEVC |
| 24 | f32 | `fps` | Nominal frame rate; `0` if unknown. Headsets use it to pick a display refresh that is a whole multiple of it. |
| 28 | u32 | `layout` | `0` mono, `1` stereo side by side (left view in the left half) |
| 32 | u32 | `projection` | `0` perspective, `1` fisheye equidistant, `2` fisheye sine |
| 36 | f32 | `fov_deg` | Field of view across the full width of **one view**, in degrees |
| 40 | f32 | `lens_c2` | Parameter of the sine lens (see below); `1.0` otherwise |
| 44 | u32 | `flags` | Bit 0: frames carry view poses (metadata record type 1). Other bits reserved, sent as 0. |

Each view is `width / views` × `height` pixels, where `views` is 1 for mono and
2 for stereo. Views are square in every sender written so far, but receivers
must not assume it.

## Frame

| Offset | Type | Field | Meaning |
|---:|---|---|---|
| 0 | 4 bytes | `magic` | ASCII `FRAM` |
| 4 | u32 | `au_size` | Size of the access unit in bytes |
| 8 | u64 | `timestamp_ns` | Capture time in nanoseconds. Senders in a simulator use simulation time; others use a monotonic clock. Only differences between frames are meaningful. |
| 16 | u32 | `meta_size` | Size of the metadata block in bytes (may be 0) |
| 20 | `meta_size` bytes | `meta` | Metadata records, see below |
| 20 + `meta_size` | `au_size` bytes | `au` | One access unit, Annex-B byte stream (start codes) |

A receiver must reject frames with an absurd `au_size` (the reference receivers
cap it at 64 MiB) and reconnect.

### Metadata records

`meta` is a sequence of records, each:

| Type | Field |
|---|---|
| u16 | `type` |
| u16 | `length` of the payload in bytes |
| `length` bytes | payload |

Receivers skip records whose type they do not know. Types `0x8000`–`0xFFFF`
are free for applications.

**Type 1 — view poses.** One entry per view, in view order (left, then right):

| Type | Field |
|---|---|
| f32 × 3 | position `x, y, z` (m) |
| f32 × 4 | orientation quaternion `w, x, y, z` |

The pose of each view's optical frame **at the instant it was rendered**, in the
sender's world frame. Optical frame convention (Gazebo/ROS body frame): **X
forward, Y left, Z up**. 28 bytes per view.

## Projections

For a view, let `(u, v)` be a pixel centre normalised to `[0, 1]`, `u` to the
right and `v` downwards, and `d = (u − 0.5, v − 0.5)`, `r = |d|`,
`n = d / r`. The ray through that pixel, in the optical frame, is

    dir = (cos θ, −sin θ · n.x, −sin θ · n.y)

for the fisheye projections, with θ the angle from the optical axis:

- **Equidistant** (`projection = 1`): `θ = (r / 0.5) · fov/2`. Equal pixels
  per degree everywhere.
- **Sine** (`projection = 2`): `θ = c2 · asin((r / 0.5) · sin(fov / (2·c2)))`.
  With `c2 = 1` and a 150° lens the centre gets 1.355× the pixels per degree
  of an equidistant lens of the same size, at the cost of the periphery —
  where a headset user rarely looks.

The formulas hold beyond the inscribed circle: the corners (`r > 0.5`) carry
rays wider than `fov/2`. A sender may paint black the rays beyond its own limit
(the Gazebo plugin stops at 90°, or where the sine lens runs out,
`(r/0.5)·sin(fov/(2·c2)) ≥ 1`); receivers just display those pixels.

- **Perspective** (`projection = 0`): pinhole, `t = tan(fov/2)`,
  `dir = normalize(1, −(2u − 1)·t, −(2v − 1)·t·h/w)` with `w, h` the view size.

## Versions

| Version | Status |
|---|---|
| 1–3 | Pre-release, used inside the Sentinel project. Fixed-size headers without `header_size`, frame without metadata. Receivers may support them; see `include/sntv/sntv.h`. |
| 4 | This document (SNTV 1.0). |
