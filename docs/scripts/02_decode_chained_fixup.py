#!/usr/bin/env python3
"""
用途：验证 chained fixup pointer 的解码逻辑，对比两种解码方式的结果：
  1. DYLD_CHAINED_PTR_64（format=6）：36-bit 绝对 VM 地址
  2. DYLD_CHAINED_PTR_64_OFFSET：32-bit runtime offset + preferredLoadAddress

同时验证 __PAGEZERO 过滤逻辑（filesize=0 的 segment 不能作为解码目标）。

输入：若干已知 raw pointer 值（从 class-dump debug log 中提取）
输出：每个 raw 值的解码结果和所在 segment

用法：
  python3 02_decode_chained_fixup.py /path/to/binary
"""

import struct
import sys

def load_segments(data):
    segs = []
    ncmds = struct.unpack_from('<I', data, 16)[0]
    off = 32
    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            name = data[off+8:off+24].rstrip(b'\x00').decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', data, off+24)
            segs.append((name, vmaddr, vmsize, fileoff, filesize))
        off += cmdsize
    return segs

def vmaddr_to_fileoff(vmaddr, segs):
    for name, va, vsz, fo, fsz in segs:
        if fsz > 0 and va <= vmaddr < va + vsz:
            return fo + (vmaddr - va)
    return 0

def read_cstr(data, fileoff):
    if fileoff == 0:
        return ''
    end = data.find(b'\x00', fileoff)
    if end == -1:
        return ''
    return data[fileoff:end].decode('utf-8', errors='replace')

def decode(raw, segs):
    """
    解码 chained fixup pointer。
    返回 (decoded_vmaddr, method_name, segment_name)
    """
    if raw >> 63:
        return 0, 'bind (external symbol)', None

    high8 = (raw >> 32) & 0xFF

    # 方法1: 36-bit 绝对地址，跳过 filesize==0 的 segment（__PAGEZERO）
    target36 = raw & 0xFFFFFFFFF
    decoded36 = target36 | (high8 << 56)
    for name, va, vsz, fo, fsz in segs:
        if fsz > 0 and va <= decoded36 < va + vsz:
            return decoded36, '36-bit absolute', name

    # 方法2: 32-bit offset + preferredLoadAddress
    preferred = next((va for name, va, vsz, fo, fsz in segs if va != 0), 0)
    if preferred:
        t32 = raw & 0xFFFFFFFF
        decoded32 = preferred + t32 + (high8 << 56)
        for name, va, vsz, fo, fsz in segs:
            if fsz > 0 and va <= decoded32 < va + vsz:
                return decoded32, '32-bit offset', name

    return 0, 'unresolved', None

def main(path):
    with open(path, 'rb') as f:
        data = f.read()

    segs = load_segments(data)
    print('Segments:')
    for name, va, vsz, fo, fsz in segs:
        print(f'  {name}: vmaddr={hex(va)} fileoff={hex(fo)} filesize={hex(fsz)}')
    print()

    # 从 class-dump debug log 中提取的典型 raw 值，按需修改
    test_values = [
        (0x10000001856be2, 'name ptr (should be in __RODATA)'),
        (0x2000000198b8ab, 'type ptr (should be in __RODATA)'),
        (0x100000018acee7, 'name ptr 2'),
        (0x2000000198b8c4, 'type ptr 2'),
        (0x8010000000000d43, 'bind ref (should return 0)'),
        (0x200000015ac300, 'ivar list addr'),
    ]

    print('Decoding test values:')
    for raw, label in test_values:
        vmaddr, method, segname = decode(raw, segs)
        if vmaddr:
            fo = vmaddr_to_fileoff(vmaddr, segs)
            s = read_cstr(data, fo)
            print(f'  [{label}]')
            print(f'    raw={hex(raw)} -> {hex(vmaddr)} via {method} (seg: {segname})')
            print(f'    string: {repr(s[:64])}')
        else:
            print(f'  [{label}]')
            print(f'    raw={hex(raw)} -> {method}')
        print()

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <mach-o binary>')
        sys.exit(1)
    main(sys.argv[1])
