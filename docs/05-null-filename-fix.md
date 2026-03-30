# (null) 文件名修复

## 问题背景

输出目录中出现 `(null)-Aspects.h`、`(null)-BgExtraView.h` 等以 `(null)` 开头的头文件。

## 原因分析

`CDMultiFileVisitor.m` 中 category 头文件名生成逻辑：

```objc
NSString *filename = [NSString stringWithFormat:@"%@-%@.h", category.className, category.name];
```

当 `category.className` 为 nil 时，`%@` 格式化输出 `(null)`。

### 为什么 className 为 nil？

调用链：
1. `loadCategoryAtAddress:` 读取 `objc2Category.class` 指针
2. 该指针是 chained fixup 的 **bind 引用**（bit63=1，外部符号）
3. `decodeChainedFixupAddress:` 返回 0
4. `classRef` 未被设置，保持 nil
5. `CDOCCategory.className` 调用 `[_classRef className]`，返回 nil

## 修改

**`CDMultiFileVisitor.m`**：

```objc
NSString *categoryClassName = category.className ?: @"UnknownClass";
NSString *filename = [NSString stringWithFormat:@"%@-%@.h", categoryClassName, category.name];
```

## 测试用例

| className | 旧文件名 | 新文件名 |
|-----------|---------|----------|
| `NSObject` | `NSObject-Aspects.h` | `NSObject-Aspects.h`（不变） |
| nil（外部 bind） | `(null)-Aspects.h` | `UnknownClass-Aspects.h` |
