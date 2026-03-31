#!/usr/bin/env python3
"""
用途：追踪 Mach-O 二进制中第一个 ObjC 类的完整结构，验证 class → class_ro → ivar_list
      的指针解析链是否正确。用于调试 ivar typeString 读取错误的问题。

输出：
  - 第一个类的 class_ptr 原始值和解码后地址
  - class_ro_t 结构体字段
  - 前几个 ivar 的原始指针值和解码后字符串

用法：
  python3 03_trace_class_ivar.py /path/to/binary
"""

import struct
import sys

def load_segments(data):
    segs = []
    ncmds = struct.unpack_from('<I', data, 16)[0]
    off = 32
    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == 0x19:
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

def read_cstr(data, fileoff, maxlen=64):
    if fileoff == 0:
        return '<null>'
    end = data.find(b'\x00', fileoff)
    if end == -1:
        return '<no null terminator>'
    return data[fileoff:min(end, fileoff+maxlen)].decode('utf-8', errors='replace')

def decode_ptr(raw, segs):
    """解码 chained fixup pointer，返回 VM 地址（0 表示失败）"""
    if raw >> 63:
        return 0  # bind
    high8 = (raw >> 32) & 0xFF
    # 36-bit absolute（跳过 filesize=0 的 segment）
    t36 = raw & 0xFFFFFFFFF
    decoded36 = t36 | (high8 << 56)
    for name, va, vsz, fo, fsz in segs:
        if fsz > 0 and va <= decoded36 < va + vsz:
            return decoded36
    # 32-bit offset
    preferred = next((va for name, va, vsz, fo, fsz in segs if va != 0), 0)
    if preferred:
        t32 = raw & 0xFFFFFFFF
        decoded32 = preferred + t32 + (high8 << 56)
        for name, va, vsz, fo, fsz in segs:
            if fsz > 0 and va <= decoded32 < va + vsz:
                return decoded32
    return 0

def find_section(data, seg_name, sect_name):
    """查找指定 section 的 vmaddr 和 fileoff"""
    ncmds = struct.unpack_from('<I', data, 16)[0]
    off = 32
    for i in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == 0x19:
            nsects = struct.unpack_from('<I', data, off+64)[0]
            for j in range(nsects):
                s = off + 72 + j*80
                sn = data[s:s+16].rstrip(b'\x00').decode()
                gn = data[s+16:s+32].rstrip(b'\x00').decode()
                addr, size, fo = struct.unpack_from('<QQI', data, s+32)
                if sn == sect_name and gn == seg_name:
                    return addr, size, fo
        off += cmdsize
    return 0, 0, 0

def main(path):
    with open(path, 'rb') as f:
        data = f.read()

    segs = load_segments(data)

    # 找 __objc_classlist
    cl_addr, cl_size, cl_fo = find_section(data, '__DATA_CONST', '__objc_classlist')
    if cl_fo == 0:
        cl_addr, cl_size, cl_fo = find_section(data, '__DATA', '__objc_classlist')
    if cl_fo == 0:
        print('Cannot find __objc_classlist')
        return

    print(f'__objc_classlist: addr={hex(cl_addr)} fileoff={hex(cl_fo)} size={hex(cl_size)}')
    print()

    # 读取第一个类指针
    class_ptr_raw = struct.unpack_from('<Q', data, cl_fo)[0]
    class_vmaddr = decode_ptr(class_ptr_raw, segs)
    print(f'class_ptr raw={hex(class_ptr_raw)} -> vmaddr={hex(class_vmaddr)}')

    class_fo = vmaddr_to_fileoff(class_vmaddr, segs)
    if not class_fo:
        print('Cannot resolve class fileoff')
        return

    # class_t: isa, superclass, cache, vtable, data
    isa, superclass, cache, vtable, data_raw = struct.unpack_from('<QQQQQ', data, class_fo)
    print(f'class_t.data raw={hex(data_raw)}')

    # data 低3位是 Swift 标志，mask 掉
    data_vmaddr = decode_ptr(data_raw & ~7, segs)
    if data_vmaddr == 0:
        data_vmaddr = data_raw & ~7
    data_fo = vmaddr_to_fileoff(data_vmaddr, segs)
    print(f'class_ro vmaddr={hex(data_vmaddr)} fileoff={hex(data_fo)}')
    print()

    if not data_fo:
        print('Cannot resolve class_ro fileoff')
        return

    # class_ro_t: flags, instanceStart, instanceSize, reserved, ivarLayout, name, baseMethods, baseProtocols, ivars
    flags, istart, isize, reserved = struct.unpack_from('<IIII', data, data_fo)
    ivar_layout_raw, name_raw, methods_raw, protos_raw, ivars_raw = struct.unpack_from('<QQQQQ', data, data_fo+16)
    print(f'class_ro_t:')
    print(f'  flags={hex(flags)} instanceStart={istart} instanceSize={isize}')
    print(f'  name_raw={hex(name_raw)}')
    name_vmaddr = decode_ptr(name_raw, segs)
    name_fo = vmaddr_to_fileoff(name_vmaddr, segs)
    print(f'  class name: {read_cstr(data, name_fo)}')
    print(f'  ivars_raw={hex(ivars_raw)}')
    print()

    if ivars_raw == 0:
        print('No ivars')
        return

    # ivar_list_t
    ivars_vmaddr = decode_ptr(ivars_raw, segs)
    ivars_fo = vmaddr_to_fileoff(ivars_vmaddr, segs)
    print(f'ivar_list vmaddr={hex(ivars_vmaddr)} fileoff={hex(ivars_fo)}')

    if not ivars_fo:
        print('Cannot resolve ivar_list fileoff')
        return

    entsize, count = struct.unpack_from('<II', data, ivars_fo)
    print(f'ivar_list: entsize={entsize} count={count}')
    print()

    # 打印前 5 个 ivar
    for i in range(min(count, 5)):
        ivar_off = ivars_fo + 8 + i * entsize
        o_raw, n_raw, t_raw = struct.unpack_from('<QQQ', data, ivar_off)
        align, size = struct.unpack_from('<Ii', data, ivar_off + 24)

        n_vmaddr = decode_ptr(n_raw, segs)
        t_vmaddr = decode_ptr(t_raw, segs)
        n_fo = vmaddr_to_fileoff(n_vmaddr, segs)
        t_fo = vmaddr_to_fileoff(t_vmaddr, segs)

        name_str = read_cstr(data, n_fo)
        type_str = read_cstr(data, t_fo)
        print(f'ivar[{i}]: name={repr(name_str)} type={repr(type_str)}')
        print(f'  offset_raw={hex(o_raw)} name_raw={hex(n_raw)} type_raw={hex(t_raw)}')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <mach-o binary>')
        sys.exit(1)
    main(sys.argv[1])
