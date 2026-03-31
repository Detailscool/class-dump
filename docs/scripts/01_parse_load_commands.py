#!/usr/bin/env python3
"""
用途：解析 Mach-O 二进制的 Load Commands，重点找出 LC_DYLD_CHAINED_FIXUPS 的
      pointer format（决定 chained fixup pointer 的解码方式）。

输出：
  - LC_DYLD_CHAINED_FIXUPS 的 dataoff / datasize
  - dyld_chained_starts_in_image 中每个 segment 的 pointer_format

常见 pointer_format 值：
  4  = DYLD_CHAINED_PTR_ARM64E
  6  = DYLD_CHAINED_PTR_64          (36-bit absolute VM address)
  7  = DYLD_CHAINED_PTR_64_OFFSET   (32-bit runtime offset)
  12 = DYLD_CHAINED_PTR_64_KERNEL_CACHE

用法：
  python3 01_parse_load_commands.py /path/to/binary
"""

import struct
import sys

def main(path):
    with open(path, 'rb') as f:
        data = f.read()

    magic = struct.unpack_from('<I', data, 0)[0]
    if magic != 0xFEEDFACF:  # MH_MAGIC_64
        print(f'Not a 64-bit Mach-O (magic={hex(magic)})')
        return

    ncmds = struct.unpack_from('<I', data, 16)[0]
    off = 32  # sizeof(mach_header_64)

    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)

        if cmd == 0x80000034:  # LC_DYLD_CHAINED_FIXUPS
            dataoff, datasize = struct.unpack_from('<II', data, off + 8)
            print(f'LC_DYLD_CHAINED_FIXUPS: dataoff={hex(dataoff)} datasize={hex(datasize)}')

            # Parse dyld_chained_fixups_header
            hdr = data[dataoff:dataoff + 28]
            (fixups_version, starts_offset, imports_offset,
             symbols_offset, imports_count, imports_format,
             symbols_format) = struct.unpack_from('<IIIIIII', hdr)
            print(f'  fixups_version={fixups_version}')
            print(f'  starts_offset={hex(starts_offset)}')
            print(f'  imports_count={imports_count}')

            # Parse dyld_chained_starts_in_image
            starts_base = dataoff + starts_offset
            seg_count = struct.unpack_from('<I', data, starts_base)[0]
            print(f'  seg_count={seg_count}')

            seg_info_offsets = struct.unpack_from('<' + 'I' * seg_count, data, starts_base + 4)
            for si, seg_off in enumerate(seg_info_offsets):
                if seg_off == 0:
                    print(f'  seg[{si}]: (no fixups)')
                    continue
                seg_info_base = starts_base + seg_off
                size, page_size, pointer_format = struct.unpack_from('<IHH', data, seg_info_base)
                print(f'  seg[{si}]: pointer_format={pointer_format} ({hex(pointer_format)})')

        off += cmdsize

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <mach-o binary>')
        sys.exit(1)
    main(sys.argv[1])
