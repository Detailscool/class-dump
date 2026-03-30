# CDLCSegment fileOffsetForAddress 修复

## 问题背景

`fileOffsetForAddress:` 依赖 `sectionContainingAddress:`，当地址落在 segment 内但不在任何 section 中时返回 0，导致 `dataOffsetForAddress:` 找不到正确偏移。

## 原因分析

Mach-O segment 可以包含多个 section，但 segment 的 fileoff/filesize 覆盖范围通常大于所有 section 之和。chained fixup decoded pointer 有时落在两个 section 之间的间隙（gap），导致 `sectionContainingAddress:` 返回 nil，进而 `fileOffsetForAddress:` 返回 0。

旧代码：

```objc
- (NSUInteger)fileOffsetForAddress:(NSUInteger)address {
    return [[self sectionContainingAddress:address] fileOffsetForAddress:address];
    // 若 sectionContainingAddress 返回 nil，则发消息给 nil，返回 0
}
```

## 修改

**`CDLCSegment.m`**：

```objc
- (NSUInteger)fileOffsetForAddress:(NSUInteger)address {
    CDSection *section = [self sectionContainingAddress:address];
    if (section)
        return [section fileOffsetForAddress:address];
    // Fallback: 直接从 segment 基址计算
    if ([self containsAddress:address])
        return self.fileoff + (address - self.vmaddr);
    return 0;
}
```

## 测试用例

| 地址位置 | 旧返回值 | 新返回值 |
|---------|---------|----------|
| 在某个 section 内 | 正确偏移 | 正确偏移（不变） |
| 在 section 间隙内 | 0（错误） | 正确偏移 |
| 不在 segment 内 | 0 | 0（不变） |
