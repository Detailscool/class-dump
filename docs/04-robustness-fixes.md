# 类型解析器健壮性修复

## 问题背景

多处 `NSParameterAssert` 和 `exit()` 调用导致 class-dump 在遇到现代二进制时崩溃或异常退出，无法输出任何头文件。

## 修复列表

---

### 1. CDObjectiveC2Processor.m — assert 改为优雅返回

所有 `NSParameterAssert([cursor offset] != 0)` 在现代二进制中会因 chained fixup pointer 解码失败而触发。

**修改**：改为检查后提前返回空结果：

```objc
// protocolAtAddress:
CDMachOFileDataCursor *cursor = [[CDMachOFileDataCursor alloc] initWithFile:self.machOFile address:address];
if ([cursor offset] == 0) return protocol;

// loadCategoryAtAddress:
if ([cursor offset] == 0) return nil;

// loadClassAtAddress: / loadMethodsOfMetaClassAtAddress:
if ([cursor offset] == 0) return nil;

// loadMethodsAtAddress:
if ([cursor offset] == 0) return methods;

// loadPropertiesAtAddress:
if ([cursor offset] == 0) return properties;

// loadIvarsAtAddress:
if ([cursor offset] == 0) return ivars;
```

同时 `extendedMethodTypesCursor` 的 assert 改为：

```objc
if ([extendedMethodTypesCursor offset] == 0)
    extendedMethodTypesCursor = nil;
```

---

### 2. CDMachOFile.m — exit() 改为返回 0/nil

```objc
// dataOffsetForAddress: 找不到 segment
if (segment == nil) {
    return 0;  // 原来是 exit(5)
}
if ([segment isProtected]) {
    return 0;  // 原来是 exit(5)
}

// stringAtAddress: 找不到 segment
if (segment == nil) {
    return nil;  // 原来是 exit(5)
}
```

---

### 3. CDTypeParser.m — nil/空字符串保护

`initWithString:` 接收 nil 或空字符串时 `_lexer` 为 nil，后续解析发消息给 nil 导致崩溃。

```objc
- (id)initWithString:(NSString *)string {
    if ((self = [super init])) {
        if (string.length == 0)
            return self;  // _lexer 保持 nil
        // ...
    }
    return self;
}

- (NSArray *)parseMethodType:(NSError **)error {
    if (_lexer == nil) return nil;  // 新增保护
    // ...
}

- (CDType *)parseType:(NSError **)error {
    if (_lexer == nil) return nil;  // 新增保护
    // ...
}
```

---

### 4. CDTypeFormatter.m — 空 typeString 保护

```objc
- (NSDictionary *)formattedTypesForMethodName:(NSString *)name type:(NSString *)type {
    if (type.length == 0) return nil;  // 新增
    // ...
}

- (NSString *)formatMethodName:(NSString *)methodName typeString:(NSString *)typeString {
    if (typeString.length == 0) return nil;  // 新增
    // ...
}
```

---

### 5. CDOCInstanceVariable.m — typeString nil 兜底

```objc
NSString *typeStr = self.typeString.length > 0 ? self.typeString : @"?";
CDTypeParser *parser = [[CDTypeParser alloc] initWithString:typeStr];
```

---

### 6. CDOCMethod.m — nil typeString 处理

```objc
NSString *typeStr = self.typeString.length > 0 ? self.typeString : nil;
CDTypeParser *parser = [[CDTypeParser alloc] initWithString:typeStr];
_parsedMethodTypes = [parser parseMethodType:&error];
_hasParsedType = YES;  // 无论成功失败都标记已尝试
```

---

## 根本原因

这些 assert/exit 是原作者在 2010 年代写的防御性代码，当时 Mach-O 格式简单、指针都是原始 VM 地址。Xcode 13+ 的 chained fixup 格式让很多地址在解码前无法直接查找 segment，触发了这些防御。

## 测试用例

| 场景 | 旧行为 | 新行为 |
|------|--------|--------|
| bind pointer 地址（bit63=1） | exit(5) | 跳过，返回 nil/0 |
| cursor offset = 0 | NSParameterAssert 崩溃 | 返回空结果 |
| typeString = nil | NSScanner nil 警告 + 崩溃 | 用 `@"?"` 兜底 |
| typeString = "" | 解析失败 warning | 提前返回 nil |
