# Relative Method Lists 支持

## 问题背景

iOS 14+ / Xcode 13+ 编译的二进制使用了 **Relative Method Lists**（相对方法列表），运行时报错：

```
*** Terminating app due to uncaught exception 'NSInternalInconsistencyException',
reason: 'Invalid parameter not satisfying: listHeader.entsize == 3 * [self.machOFile ptrSize]'
```

`listHeader.entsize = 2147483660`（`0x8000000C`），bit31 被置为 1。

## 原因分析

旧格式（绝对方法列表）：每个 method entry 是 3 个指针（name/types/imp），64-bit 下 24 字节。

新格式（相对方法列表，bit31=1）：每个 method entry 是 3 个 **int32_t 相对偏移**，共 12 字节：

```
nameOffset  – 相对于自身字段地址，指向 __objc_selrefs 中的 SEL ref 槽
typesOffset – 相对于自身字段地址，直接指向类型字符串（nullable，0 表示 null）
impOffset   – 相对于自身字段地址，是 IMP 的相对偏移
```

## 修改

**`CDObjectiveC2Processor.m`** `loadMethodsAtAddress:extendedMethodTypesCursor:`：

```objc
uint32_t rawFlags  = [cursor readInt32];
BOOL isRelative    = (rawFlags & 0x80000000) != 0;
listHeader.entsize = rawFlags & ~(uint32_t)0xffff0003;  // 匹配 objc4 源码
listHeader.count   = [cursor readInt32];

if (isRelative) {
    for (uint32_t index = 0; index < listHeader.count; index++) {
        NSUInteger nameFieldAddr  = [self.machOFile fileOffsetToAddress:cursor.offset];
        int32_t nameRelOffset     = (int32_t)[cursor readInt32];
        NSUInteger typesFieldAddr = [self.machOFile fileOffsetToAddress:cursor.offset];
        int32_t typesRelOffset    = (int32_t)[cursor readInt32];
        NSUInteger impFieldAddr   = [self.machOFile fileOffsetToAddress:cursor.offset];
        int32_t impRelOffset      = (int32_t)[cursor readInt32];

        // Name: nameField + offset → SEL ref 槽 → 选择子字符串
        NSUInteger nameRefAddr = nameFieldAddr + nameRelOffset;
        NSUInteger nameStrAddr = [self.machOFile ptrValueAtAddress:nameRefAddr];
        if (nameStrAddr == 0) continue;
        NSString *name = [self.machOFile stringAtAddress:nameStrAddr];
        if (name == nil) continue;

        // Types: typesRelOffset == 0 表示 null（类型信息被 strip）
        NSString *types = nil;
        if (typesRelOffset != 0) {
            NSUInteger typesAddr = typesFieldAddr + typesRelOffset;
            types = [self.machOFile stringAtAddress:typesAddr];
        }

        NSUInteger impAddr = impFieldAddr + impRelOffset;
        CDOCMethod *method = [[CDOCMethod alloc] initWithName:name typeString:types address:impAddr];
        [methods addObject:method];
    }
} else {
    // 原有绝对方法列表逻辑
    NSParameterAssert(listHeader.entsize == 3 * [self.machOFile ptrSize]);
    // ...
}
```

## 关键细节

1. **entsize 掩码**：应用 `~0xffff0003`（匹配 objc4 源码），而非 `~3`
2. **typesRelOffset == 0 是 nullable null**：Apple 的 RelativePointer 约定，offset=0 表示空指针，不能直接加到 typesFieldAddr 上（否则读到下一个字段的数据）
3. **nameOffset 指向 SEL ref 槽**：需要再解引用一次才能得到选择子字符串

## 测试用例

| 场景 | 预期结果 |
|------|----------|
| 普通绝对方法列表（bit31=0） | 原有逻辑正常处理 |
| 相对方法列表（bit31=1） | 正确解析 name/types/imp |
| typesRelOffset == 0 | types = nil，方法签名用 id 兜底 |
| nameStrAddr == 0（外部 bind） | 跳过该方法 |
