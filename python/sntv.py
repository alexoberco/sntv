"""SNTV wire protocol, version 4 (SNTV 1.0): encode and decode. See SPEC.md.

Pure Python, no dependencies. Mirrors include/sntv/sntv.h.

Copyright 2026 Alejandro Bermúdez Fajardo (alexoberco)
SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass, field

VERSION = 4
HEADER_SIZE = 48
FRAME_HEADER_SIZE = 20
MAX_AU_SIZE = 64 * 1024 * 1024

CODEC_H264, CODEC_HEVC = 1, 2
LAYOUT_MONO, LAYOUT_STEREO_SBS = 0, 1
PROJ_PERSPECTIVE, PROJ_FISHEYE_EQUIDISTANT, PROJ_FISHEYE_SINE = 0, 1, 2
FLAG_VIEW_POSES = 1
META_VIEW_POSES = 1

CODEC_NAMES = {CODEC_H264: 'h264', CODEC_HEVC: 'hevc'}
PROJECTION_NAMES = {PROJ_PERSPECTIVE: 'perspective', PROJ_FISHEYE_EQUIDISTANT: 'equidistant',
                    PROJ_FISHEYE_SINE: 'sine'}


@dataclass
class Header:
    width: int
    height: int
    codec: int = CODEC_HEVC
    fps: float = 0.0
    layout: int = LAYOUT_STEREO_SBS
    projection: int = PROJ_FISHEYE_EQUIDISTANT
    fov_deg: float = 150.0
    lens_c2: float = 1.0
    flags: int = 0
    version: int = VERSION
    header_size: int = HEADER_SIZE

    @property
    def views(self) -> int:
        return 2 if self.layout == LAYOUT_STEREO_SBS else 1

    @property
    def frame_header_size(self) -> int:
        return 16 if self.version <= 3 else FRAME_HEADER_SIZE

    def pack(self) -> bytes:
        return b'SNTV' + struct.pack('<IIIIIfIIffI', VERSION, HEADER_SIZE, self.width, self.height,
                                     self.codec, self.fps, self.layout, self.projection,
                                     self.fov_deg, self.lens_c2, self.flags)


@dataclass
class ViewPose:
    position: tuple[float, float, float]
    orientation: tuple[float, float, float, float]  # w, x, y, z


@dataclass
class Frame:
    timestamp_ns: int
    au: bytes
    meta: bytes = b''
    view_poses: list[ViewPose] = field(default_factory=list)


def header_size(prefix: bytes) -> int:
    """Total header size from its first 12 bytes; 0 if it is not an SNTV header."""
    if prefix[:4] != b'SNTV':
        return 0
    version = struct.unpack_from('<I', prefix, 4)[0]
    if version in (1, 2, 3):
        return {1: 20, 2: 32, 3: 36}[version]
    if version < 4:
        return 0
    size = struct.unpack_from('<I', prefix, 8)[0]
    return size if HEADER_SIZE <= size <= 4096 else 0


def parse_header(data: bytes) -> Header:
    version = struct.unpack_from('<I', data, 4)[0]
    if version <= 3:
        # Pre-release headers: always a 150-degree fisheye stereo pair.
        w, h, codec = struct.unpack_from('<III', data, 8)
        hdr = Header(w, h, codec, layout=LAYOUT_STEREO_SBS, projection=PROJ_FISHEYE_EQUIDISTANT,
                     version=version, header_size=len(data))
        if version >= 2:
            lens, hdr.lens_c2, hdr.fov_deg = struct.unpack_from('<Iff', data, 20)
            hdr.projection = PROJ_FISHEYE_SINE if lens == 1 else PROJ_FISHEYE_EQUIDISTANT
        if version >= 3:
            hdr.fps = struct.unpack_from('<f', data, 32)[0]
        return hdr
    (_, size, w, h, codec, fps, layout, proj, fov, c2, flags) = struct.unpack_from('<IIIIIfIIffI', data, 4)
    return Header(w, h, codec, fps, layout, proj, fov, c2, flags, version, size)


def pack_view_poses(poses: list[ViewPose]) -> bytes:
    payload = b''.join(struct.pack('<7f', *p.position, *p.orientation) for p in poses)
    return struct.pack('<HH', META_VIEW_POSES, len(payload)) + payload


def parse_view_poses(meta: bytes) -> list[ViewPose]:
    off = 0
    while off + 4 <= len(meta):
        rtype, length = struct.unpack_from('<HH', meta, off)
        if off + 4 + length > len(meta):
            return []
        if rtype == META_VIEW_POSES:
            out = []
            for i in range(length // 28):
                v = struct.unpack_from('<7f', meta, off + 4 + 28 * i)
                out.append(ViewPose(v[0:3], v[3:7]))
            return out
        off += 4 + length
    return []


def pack_frame(timestamp_ns: int, au: bytes, meta: bytes = b'') -> bytes:
    return b'FRAM' + struct.pack('<IQI', len(au), timestamp_ns, len(meta)) + meta + au


def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError('sender closed the connection')
        buf += chunk
    return bytes(buf)


class Reader:
    """Blocking reader over a connected socket: .header, then .next_frame() repeatedly."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        prefix = _read_exact(sock, 12)
        size = header_size(prefix)
        if not size:
            raise ValueError('not an SNTV stream')
        self.header = parse_header(prefix + _read_exact(sock, size - 12))

    def next_frame(self) -> Frame:
        fh = _read_exact(self.sock, self.header.frame_header_size)
        if fh[:4] != b'FRAM':
            raise ValueError('lost frame sync')
        au_size, ts = struct.unpack_from('<IQ', fh, 4)
        meta_size = struct.unpack_from('<I', fh, 16)[0] if self.header.version > 3 else 0
        if au_size > MAX_AU_SIZE or meta_size > 65536:
            raise ValueError(f'absurd frame size {au_size} / {meta_size}')
        meta = _read_exact(self.sock, meta_size) if meta_size else b''
        au = _read_exact(self.sock, au_size)
        return Frame(ts, au, meta, parse_view_poses(meta))
