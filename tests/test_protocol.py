#!/usr/bin/env python3
"""Conformance: the C header and the Python module write the same bytes, and the
Python parser reads both v4 and legacy (v1-3) headers.

    python3 tests/test_protocol.py        (needs a C compiler)

Copyright 2026 Alejandro Bermúdez Fajardo (alexoberco)
SPDX-License-Identifier: Apache-2.0
"""
import os
import struct
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python'))
import sntv  # noqa: E402


def python_bytes():
    h = sntv.Header(4320, 2160, sntv.CODEC_HEVC, 45.0, sntv.LAYOUT_STEREO_SBS, sntv.PROJ_FISHEYE_SINE,
                    150.0, 1.0, sntv.FLAG_VIEW_POSES)
    meta = sntv.pack_view_poses([sntv.ViewPose((0.1, 0.0315, 1.2), (1, 0, 0, 0)),
                                 sntv.ViewPose((0.1, -0.0315, 1.2), (0.7071, 0, 0, 0.7071))])
    frame = b'FRAM' + struct.pack('<IQI', 1234, 987654321, len(meta)) + meta
    return h.pack() + frame


def main():
    with tempfile.TemporaryDirectory() as d:
        exe = os.path.join(d, 't')
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-I', os.path.join(ROOT, 'include'),
                        os.path.join(ROOT, 'tests', 'test_c_header.c'), '-o', exe], check=True)
        c_hex = subprocess.run([exe], check=True, capture_output=True, text=True).stdout.strip()
    py = python_bytes()
    assert c_hex == py.hex(), f'C and Python differ:\n{c_hex}\n{py.hex()}'

    h = sntv.parse_header(py[:sntv.HEADER_SIZE])
    assert (h.width, h.height, h.codec, h.fps, h.views) == (4320, 2160, 2, 45.0, 2)
    poses = sntv.parse_view_poses(py[sntv.HEADER_SIZE + 20:])
    assert len(poses) == 2 and abs(poses[1].orientation[3] - 0.7071) < 1e-6

    # Legacy v3: SNTV | 3 | w | h | codec | lens | c2 | fov | fps
    v3 = b'SNTV' + struct.pack('<IIIIIfff', 3, 5760, 2896, 2, 1, 1.0, 150.0, 45.0)
    assert sntv.header_size(v3[:12]) == 36
    h3 = sntv.parse_header(v3)
    assert (h3.projection, h3.fps, h3.views, h3.frame_header_size) == (sntv.PROJ_FISHEYE_SINE, 45.0, 2, 16)
    # Unknown trailing header bytes are skipped (forward compatibility).
    longer = bytearray(py[:sntv.HEADER_SIZE]) + b'\0' * 8
    struct.pack_into('<I', longer, 8, sntv.HEADER_SIZE + 8)
    assert sntv.header_size(bytes(longer[:12])) == sntv.HEADER_SIZE + 8
    assert sntv.parse_header(bytes(longer)).width == 4320
    print(f'OK: C and Python agree ({len(py)} bytes), legacy and extended headers parse')


if __name__ == '__main__':
    main()
