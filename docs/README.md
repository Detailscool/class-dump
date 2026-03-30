# 修复总览

本目录记录了 class-dump 为支持现代 arm64 二进制（Xcode 13+）所做的修复。

## 修复文档列表

| 文档 | 问题 | 影响范围 |
|------|------|----------|
| [01-modern-macho-support.md](01-modern-macho-support.md) | 新 Load Command 不认识 + Chained Fixup Pointer 解码 | `CDLoadCommand.m`, `CDMachOFile.m`, `CDLCSegment.m` |
| [02-relative-method-lists.md](02-relative-method-lists.md) | iOS 14+ Relative Method Lists 解析 | `CDObjectiveC2Processor.m` |
| [03-atomic-type-modifier.md](03-atomic-type-modifier.md) | `_Atomic`（`A`）类型修饰符不认识 | `CDTypeParser.m`, `CDType.m` |
| [04-robustness-fixes.md](04-robustness-fixes.md) | assert/exit 导致崩溃，nil/空字符串未保护 | 多处 |
| [05-null-filename-fix.md](05-null-filename-fix.md) | Category 头文件名出现 `(null)` | `CDMultiFileVisitor.m` |
| [06-segment-fileoffset-fix.md](06-segment-fileoffset-fix.md) | 地址落在 section 间隙时偏移计算错误 | `CDLCSegment.m` |

---

## 核心问题根源

```mermaid
graph TD
    A[Xcode 13+ 编译产物] --> B[LC_DYLD_CHAINED_FIXUPS]
    B --> C[__DATA 指针槽存储编码值而非原始 VM 地址]
    C --> D1[dataOffsetForAddress 找不到 segment → exit]
    C --> D2[ivar/method 指针解码错误 → 垃圾类型字符串]
    C --> D3[category.class 是 bind 引用 → className=nil]
    A --> E[Relative Method Lists bit31=1]
    E --> F[entsize 断言失败 → 崩溃]
    A --> G[_Atomic 类型修饰符 A]
    G --> H[类型解析器不认识 A → warning/断言]
    style A fill:#2d6a4f,color:#fff
    style D1 fill:#9b2226,color:#fff
    style D2 fill:#9b2226,color:#fff
    style D3 fill:#9b2226,color:#fff
    style F fill:#9b2226,color:#fff
    style H fill:#9b2226,color:#fff
```

---


## 编译方法

```bash
# 仅 arm64
xcodebuild -scheme class-dump -configuration Release \
  -derivedDataPath build ARCHS=arm64 ONLY_ACTIVE_ARCH=YES

# arm64 + x86_64 Fat Binary
xcodebuild -scheme class-dump -configuration Release \
  -derivedDataPath build ARCHS='arm64 x86_64' ONLY_ACTIVE_ARCH=NO

# 产物路径
build/Build/Products/Release/class-dump
```
