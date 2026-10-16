/* Writes a v4 header, a frame header and a view-pose record with sntv.h, so
 * test_protocol.py can check them byte for byte against the Python module.
 * Copyright 2026 Alejandro Bermúdez Fajardo (alexoberco)
 * SPDX-License-Identifier: Apache-2.0 */
#include <stdio.h>
#include "sntv/sntv.h"

int main(void)
{
  sntv_header h = {0};
  h.width = 4320; h.height = 2160; h.codec = SNTV_CODEC_HEVC; h.fps = 45.0f;
  h.layout = SNTV_LAYOUT_STEREO_SBS; h.projection = SNTV_PROJ_FISHEYE_SINE;
  h.fov_deg = 150.0f; h.lens_c2 = 1.0f; h.flags = SNTV_FLAG_VIEW_POSES;
  uint8_t buf[256];
  sntv_write_header(buf, &h);
  sntv_view_pose poses[2] = {{0.1f, 0.0315f, 1.2f, 1, 0, 0, 0}, {0.1f, -0.0315f, 1.2f, 0.7071f, 0, 0, 0.7071f}};
  uint32_t meta = sntv_write_view_poses(buf + SNTV_HEADER_SIZE + SNTV_FRAME_HEADER_SIZE, poses, 2);
  sntv_frame_header f = {1234, 987654321ull, meta};
  sntv_write_frame_header(buf + SNTV_HEADER_SIZE, &f);
  const uint32_t n = SNTV_HEADER_SIZE + SNTV_FRAME_HEADER_SIZE + meta;
  /* Round trip through the parser before printing. */
  sntv_header back;
  if (sntv_header_size(buf) != SNTV_HEADER_SIZE || sntv_parse_header(buf, &back) != 0 ||
      back.width != 4320 || back.projection != SNTV_PROJ_FISHEYE_SINE || back.fps != 45.0f) return 1;
  sntv_frame_header fb;
  if (sntv_parse_frame_header(buf + SNTV_HEADER_SIZE, &back, &fb) != 0 || fb.timestamp_ns != 987654321ull) return 2;
  sntv_view_pose pb[2];
  if (sntv_read_view_poses(buf + SNTV_HEADER_SIZE + SNTV_FRAME_HEADER_SIZE, meta, pb, 2) != 2 || pb[1].qz != 0.7071f) return 3;
  for (uint32_t i = 0; i < n; ++i) printf("%02x", buf[i]);
  printf("\n");
  return 0;
}
