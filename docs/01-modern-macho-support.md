# 现代 Mach-O 二进制支持修复

## 问题背景

Xcode 13+ 编译的 arm64 二进制使用了新的链接格式，旧版 class-dump 无法处理，运行时报错：

```
Unknown load command: 0x80000034
Unknown load command: 0x80000033
Unknown load command: 0x00000032
Error: Cannot find offset for address 0x1000000173eaf0 in dataOffsetForAddress:
```

## 涉及文件

- `Source/CDLoadCommand.m`
- `Source/CDMachOFile.h`
- `Source/CDMachOFile.m`
- `Source/CDLCSegment.m`

---

## 修复 1：识别新 Load Command

### 原因

三个新的 load command 未被识别，导致打印 `Unknown load command` 并跳过处理：

| 值 | 名称 | 结构 |
|---|---|---|
| `0x00000032` | `LC_BUILD_VERSION` | 自定义结构 |
| `0x80000033` | `LC_DYLD_EXPORTS_TRIE` | `linkedit_data_command` |
| `0x80000034` | `LC_DYLD_CHAINED_FIXUPS` | `linkedit_data_command` |

### 修改

**`CDLoadCommand.m`** switch 语句中新增三个 case：

```objc
case LC_BUILD_VERSION:         targetClass = [CDLCUnknown class]; break;
case LC_DYLD_EXPORTS_TRIE:     targetClass = [CDLCLinkeditData class]; break;
case LC_DYLD_CHAINED_FIXUPS:   targetClass = [CDLCLinkeditData class]; break;
```

---

## 修复 2：Chained Fixup Pointer 解码

### 原因

Xcode 13+ 使用 `LC_DYLD_CHAINED_FIXUPS`，`__DATA` 段中的指针槽存储的是**编码值**而非原始 VM 地址。class-dump 直接把编码值当 VM 地址去查找 segment，导致 `Cannot find offset` 错误。

### Pointer 格式

**DYLD_CHAINED_PTR_64_OFFSET（32-bit offset 格式）：**
```
bits[31: 0] = runtimeOffset（相对于 __TEXT 基址的偏移）
bits[39:32] = high8（通常为 0）
bit [63]    = bind（1=外部符号，0=本地）
```

**DYLD_CHAINED_PTR_64（format=6，36-bit 绝对地址格式）：**
```
bits[35: 0] = target（绝对 VM 地址）
bits[39:32] = high8
bit [63]    = bind
```

### 修改

**`CDMachOFile.h`** 新增三个方法声明：

```objc
- (NSUInteger)decodeChainedFixupAddress:(NSUInteger)rawValue;
- (NSUInteger)fileOffsetToAddress:(NSUInteger)fileOffset;
- (NSUInteger)ptrValueAtAddress:(NSUInteger)vmAddress;
```

**`CDMachOFile.m`** 实现 `decodeChainedFixupAddress:`：

```objc
- (NSUInteger)decodeChainedFixupAddress:(NSUInteger)rawValue {
    if (rawValue >> 63) return 0;  // bind = 外部符号，无法本地解析

    uint64_t high8 = (rawValue >> 32) & 0xFF;

    // 先尝试 36-bit 绝对地址（format=6），跳过 __PAGEZERO（filesize=0）
    uint64_t target36 = rawValue & 0xFFFFFFFFFULL;
    NSUInteger decoded36 = (NSUInteger)(target36 | (high8 << 56));
    CDLCSegment *seg36 = [self segmentContainingAddress:decoded36];
    if (seg36 != nil && seg36.filesize > 0)
        return decoded36;

    // fallback：32-bit offset + preferredLoadAddress
    uint64_t runtimeOffset = rawValue & 0xFFFFFFFF;
    NSUInteger preferredLoadAddress = 0;
    for (CDLCSegment *seg in _segments) {
        if (seg.vmaddr != 0) { preferredLoadAddress = seg.vmaddr; break; }
    }
    if (preferredLoadAddress != 0) {
        NSUInteger decoded32 = preferredLoadAddress + runtimeOffset + (high8 << 56);
        if ([self segmentContainingAddress:decoded32] != nil)
            return decoded32;
    }
    return 0;
}
```

> **关键细节**：36-bit 尝试必须过滤 `filesize == 0` 的 segment（即 `__PAGEZERO`）。`__PAGEZERO` 的 vmaddr=0、vmsize=0x100000000，会错误匹配 36-bit 解码出的小地址，必须排除。

**`CDLCSegment.m`** `fileOffsetForAddress:` 加 segment 级 fallback：

```objc
- (NSUInteger)fileOffsetForAddress:(NSUInteger)address {
    CDSection *section = [self sectionContainingAddress:address];
    if (section)
        return [section fileOffsetForAddress:address];
    // 地址在 section 之间时的兜底
    if ([self containsAddress:address])
        return self.fileoff + (address - self.vmaddr);
    return 0;
}
```

**`CDMachOFile.m`** `stringAtAddress:` 和 `dataOffsetForAddress:` 找不到 segment 时改为优雅返回（不 exit）：

```objc
// 找不到 segment 时返回 nil / 0，不再 exit(5)
if (segment == nil) return nil;   // stringAtAddress:
if (segment == nil) return 0;     // dataOffsetForAddress:
```

---

## 测试用例

| 场景 | 预期结果 |
|------|----------|
| bind pointer（bit63=1） | 返回 0，跳过 |
| 36-bit 绝对地址落在有效 segment | 直接返回 decoded36 |
| 36-bit 地址落在 __PAGEZERO（filesize=0） | 跳过，fallback 32-bit |
| 32-bit offset + preferredLoadAddress 有效 | 返回 decoded32 |
| 两种解码均失败 | 返回 0，字段输出为空 |
| LC_BUILD_VERSION / LC_DYLD_EXPORTS_TRIE / LC_DYLD_CHAINED_FIXUPS | 不再打印 Unknown log |
