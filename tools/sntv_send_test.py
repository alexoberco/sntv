#!/usr/bin/env python3
"""Reference SNTV sender: a moving test pattern, no simulator or GPU needed.

Use it to bring up a receiver (a headset app, sntv_receive.py) before wiring a
real source. Encodes with libx264 through PyAV in a low-latency configuration
(no B-frames, one slice, Annex-B), serves one receiver at a time and starts every
connection with an IDR. The pattern is a grid with a moving bar and a frame
counter per view, so you can see orientation, tearing and left/right swaps.

    python3 tools/sntv_send_test.py --port 8766 --size 1024 --stereo --fps 60

Copyright 2026 Alejandro Bermúdez Fajardo (alexoberco)
SPDX-License-Identifier: Apache-2.0
"""

import argparse
import fractions
import math
import os
import socket
import sys
import time

import av
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sntv  # noqa: E402


def pattern(view_size, n_views, i):
    """RGB test image: grid, a bar moving left to right, the view index as stripes."""
    w = view_size * n_views
    img = np.full((view_size, w, 3), 24, np.uint8)
    img[::64, :, :] = 90
    img[:, ::64, :] = 90
    for v in range(n_views):
        x0 = v * view_size
        bar = x0 + int((i * 4) % view_size)
        img[:, bar:bar + 8, 0] = 230
        # One stripe for the left view, two for the right: swaps are obvious.
        for s in range(v + 1):
            img[16 + s * 24:32 + s * 24, x0 + 16:x0 + view_size // 4, 1] = 220
        # Frame counter as a binary row of squares along the bottom.
        for b in range(16):
            if (i >> b) & 1:
                img[-40:-24, x0 + 16 + b * 24:x0 + 32 + b * 24, :] = 255
    return img


def make_encoder(width, height, fps, bitrate):
    enc = av.CodecContext.create('libx264', 'w')
    enc.width, enc.height = width, height
    enc.pix_fmt = 'yuv420p'
    enc.time_base = fractions.Fraction(1, fps)
    enc.framerate = fractions.Fraction(fps, 1)
    enc.bit_rate = bitrate
    enc.options = {'preset': 'ultrafast', 'tune': 'zerolatency', 'bframes': '0',
                   'repeat-headers': '1', 'keyint': '600', 'annexb': '1'}
    return enc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--size', type=int, default=1024, help='pixels per side of each (square) view')
    ap.add_argument('--stereo', action='store_true')
    ap.add_argument('--fps', type=int, default=60)
    ap.add_argument('--bitrate', type=int, default=20_000_000)
    ap.add_argument('--frames', type=int, default=0, help='stop after N frames per connection (0 = never)')
    args = ap.parse_args()

    n_views = 2 if args.stereo else 1
    width, height = args.size * n_views, args.size
    header = sntv.Header(width, height, sntv.CODEC_H264, float(args.fps),
                         sntv.LAYOUT_STEREO_SBS if args.stereo else sntv.LAYOUT_MONO,
                         sntv.PROJ_PERSPECTIVE, 90.0, 1.0, sntv.FLAG_VIEW_POSES)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.bind, args.port))
    srv.listen(1)
    print(f'SNTV test sender on {args.bind}:{args.port}: {width}x{height} H.264 {args.fps} fps')
    while True:
        conn, peer = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f'receiver connected from {peer[0]}')
        # A fresh encoder per connection: its first frame is an IDR with SPS/PPS.
        enc = make_encoder(width, height, args.fps, args.bitrate)
        period = 1.0 / args.fps
        t0 = time.monotonic()
        i = 0
        try:
            conn.sendall(header.pack())
            while not args.frames or i < args.frames:
                img = pattern(args.size, n_views, i)
                frame = av.VideoFrame.from_ndarray(img, format='rgb24').reformat(format='yuv420p')
                frame.pts = i
                ts = int(i * period * 1e9)
                # A rig turning slowly around Z, with the views 64 mm apart.
                yaw = 0.2 * math.sin(i * period)
                q = (math.cos(yaw / 2), 0.0, 0.0, math.sin(yaw / 2))
                poses = [sntv.ViewPose((0.0, 0.032 - 0.064 * v, 1.5), q) for v in range(n_views)]
                meta = sntv.pack_view_poses(poses)
                for pkt in enc.encode(frame):
                    conn.sendall(sntv.pack_frame(ts, bytes(pkt), meta))
                i += 1
                sleep = t0 + i * period - time.monotonic()
                if sleep > 0:
                    time.sleep(sleep)
        except (BrokenPipeError, ConnectionResetError):
            pass
        conn.close()
        print(f'receiver gone after {i} frames')
        if args.frames:
            return 0


if __name__ == '__main__':
    sys.exit(main())
