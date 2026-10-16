#!/usr/bin/env python3
"""Reference SNTV receiver: connect, decode, measure.

Prints the stream header, then every few seconds the received and decoded frame
rate, bitrate, inter-arrival jitter and (if present) the pose of the first view.
With --save it writes the last decoded frame to a PNG, which is the quickest way
to check orientation, projection and colour of a new sender.

    python3 tools/sntv_receive.py --host 127.0.0.1 --port 8766 --seconds 10 --save /tmp/frame.png

Needs PyAV (pip install av) to decode; with --no-decode it only parses.

Copyright 2026 Alejandro Bermúdez Fajardo (alexoberco)
SPDX-License-Identifier: Apache-2.0
"""

import argparse
import os
import socket
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'python'))
import sntv  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8766)
    ap.add_argument('--seconds', type=float, default=10.0, help='0 = until interrupted')
    ap.add_argument('--save', help='PNG to write the last decoded frame to')
    ap.add_argument('--no-decode', action='store_true', help='parse only, do not decode')
    ap.add_argument('--report', type=float, default=2.0, help='seconds between reports')
    args = ap.parse_args()

    sock = socket.create_connection((args.host, args.port), timeout=10)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
    reader = sntv.Reader(sock)
    h = reader.header
    print(f'SNTV v{h.version}: {h.width}x{h.height} {sntv.CODEC_NAMES.get(h.codec, h.codec)}, '
          f'{h.fps:g} fps, {"stereo" if h.views == 2 else "mono"}, '
          f'{sntv.PROJECTION_NAMES.get(h.projection, h.projection)} {h.fov_deg:g} deg'
          f'{f" c2={h.lens_c2:g}" if h.projection == sntv.PROJ_FISHEYE_SINE else ""}, '
          f'view poses: {"yes" if h.flags & sntv.FLAG_VIEW_POSES else "no"}')

    decoder = None
    if not args.no_decode:
        import av
        decoder = av.CodecContext.create(sntv.CODEC_NAMES[h.codec], 'r')

    t_start = last_report = time.monotonic()
    n_recv = n_dec = nbytes = 0
    arrivals = []
    last_img = None
    last_frame = None
    total_recv = total_dec = 0
    while True:
        try:
            frame = reader.next_frame()
        except EOFError as e:
            print(e)
            break
        now = time.monotonic()
        arrivals.append(now)
        n_recv += 1
        total_recv += 1
        nbytes += len(frame.au)
        last_frame = frame
        if decoder is not None:
            for pic in decoder.decode(av.Packet(frame.au)):
                n_dec += 1
                total_dec += 1
                last_img = pic
        if now - last_report >= args.report:
            dt = now - last_report
            gaps = [1000 * (b - a) for a, b in zip(arrivals, arrivals[1:])]
            jitter = f'{statistics.mean(gaps):.1f} +- {statistics.pstdev(gaps):.1f} ms' if len(gaps) > 1 else '-'
            pose = ''
            if frame.view_poses:
                p = frame.view_poses[0]
                pose = ' | view0 at ({:.3f}, {:.3f}, {:.3f})'.format(*p.position)
            print(f'{n_recv / dt:5.1f} fps received, {n_dec / dt:5.1f} decoded, '
                  f'{nbytes * 8 / dt / 1e6:6.1f} Mbit/s, interval {jitter}{pose}')
            n_recv = n_dec = nbytes = 0
            arrivals = arrivals[-1:]
            last_report = now
        if args.seconds and now - t_start >= args.seconds:
            break
    sock.close()

    print(f'total: {total_recv} received, {total_dec} decoded')
    if last_frame is not None and last_frame.view_poses:
        for i, p in enumerate(last_frame.view_poses):
            print(f'view {i}: position {tuple(round(v, 4) for v in p.position)}, '
                  f'orientation wxyz {tuple(round(v, 4) for v in p.orientation)}')
    if args.save and last_img is not None:
        last_img.to_image().save(args.save)
        print(f'saved {args.save}')
    return 0 if total_recv else 1


if __name__ == '__main__':
    sys.exit(main())
