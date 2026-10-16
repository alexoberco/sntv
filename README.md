# SNTV — Sentinel Video

A minimal protocol for sending **already-encoded H.264/HEVC video** from a GPU
encoder to a **VR headset** (or any receiver) over one TCP connection, with the
**pose of the camera** that took each frame riding along with it.

It was born in [Sentinel](https://github.com/alexoberco), a hobby project to
teleoperate a simulated humanoid robot from a Meta Quest. The robot's stereo
fisheye eyes are rendered, composed and encoded **inside Gazebo on the GPU** and
decoded on the headset **without a single CPU copy**, at 2880 px per eye and
45–60 fps over a USB cable.

| Repo | What it is | Runs on |
|---|---|---|
| **sntv** (this one) | The wire protocol: [spec](SPEC.md), a C header, a Python module, a reference sender and receiver | Anywhere |
| [sntv_gazebo](https://github.com/alexoberco/sntv_gazebo) | Gazebo Sim system plugin: renders a mono or stereo camera rig (perspective or fisheye), encodes it with NVENC on the GPU and serves it over SNTV | Linux, NVIDIA GPU, Gazebo Harmonic |
| [sntv_unity](https://github.com/alexoberco/sntv_unity) | Unity package: receives SNTV on Android/Meta Quest and decodes it in hardware straight into a texture | Unity 6, Android (Quest), OpenGL ES 3 |

## Why not WebRTC?

WebRTC is the right tool across the internet. On a cable or a LAN, for one
sender and one receiver, its machinery gets in the way:

- On Android, Unity's WebRTC decodes in hardware but **uploads every frame
  through the CPU** (~9 ms per frame at 2×1280 px, measured), which caps the
  resolution you can use.
- Jitter buffers, pacing and congestion control add latency you do not need
  when the link is a USB cable with 3 ms round trip.
- There is nowhere standard to put **the pose the frame was rendered from**,
  which is what a headset needs to reproject the image against the current head
  pose and hide latency.

SNTV is the opposite trade-off: one TCP stream, Annex-B access units, a 20-byte
frame header with a timestamp and optional metadata, and nothing else. When
the receiver falls behind, the sender drops frames and sends an IDR rather than
queueing.

## The protocol in one screen

```
connection:  stream header (48 bytes), then frames until either side closes

stream header  "SNTV" | version=4 | header_size | width | height | codec (1 H.264, 2 HEVC)
               | fps | layout (0 mono, 1 stereo side by side)
               | projection (0 perspective, 1 fisheye equidistant, 2 fisheye sine)
               | fov_deg | lens_c2 | flags (bit 0: frames carry view poses)

frame          "FRAM" | au_size | timestamp_ns | meta_size | meta | access unit (Annex-B)
meta           records of  type:u16 | length:u16 | payload
               type 1 = view poses: per view, position xyz + quaternion wxyz (f32)
```

Everything little endian. The full definition, including the projection
formulas, is in [SPEC.md](SPEC.md).

## Try it in one minute

No simulator or GPU needed (Python 3 and `pip install av numpy`):

```bash
python3 tools/sntv_send_test.py --stereo --size 1024 --fps 60     # terminal 1
python3 tools/sntv_receive.py --seconds 10 --save frame.png        # terminal 2
```

The receiver prints the stream header and, every two seconds, received and
decoded fps, bitrate, inter-arrival jitter and the pose of the first view.
`frame.png` shows the test pattern: one green stripe on the left view, two on
the right, a moving red bar and a binary frame counter.

## Using it from your own code

- **C / C++**: `#include <sntv/sntv.h>` (header-only, C99). `sntv_write_header`,
  `sntv_write_frame_header`, `sntv_write_view_poses` to send;
  `sntv_header_size` + `sntv_parse_header`, `sntv_parse_frame_header`,
  `sntv_read_view_poses` to receive. Socket I/O is yours.
- **Python**: `python/sntv.py`. `Header(...).pack()`, `pack_frame()`,
  `pack_view_poses()` to send; `Reader(sock)` to receive.

`tests/test_protocol.py` checks that both write the same bytes.

## Versions

Version 4 is SNTV 1.0, the first public one. Versions 1–3 were used inside
Sentinel before it was published; the parsers here still read them.

## License and credit

[Apache License 2.0](LICENSE). You can use it, modify it and build commercial
products on it. In exchange, any redistribution must keep the copyright notices
and ship the [NOTICE](NOTICE) file (or its text in your credits or
documentation): that is how the author gets credited wherever SNTV ends up.
