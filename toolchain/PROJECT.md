# plcforge — IEC 61131-3 工业控制工具链

对标 Siemens TIA Portal / Rockwell Studio 5000 的核心能力。这是一个**多模块系统**，不是单个引擎：
模块之间有明确契约，集成正确性与单模块正确性同等重要。

## 交付物

工作区根目录下必须存在这些入口，参数与语义严格按下面的约定：

| 入口 | 用途 |
|---|---|
| `bin/plc-compile <prog.st> <out.json>` | 把 ST 源码编译为中间表示（IR），输出 JSON |
| `bin/plc-run <prog.st> <stim.csv> <trace.csv> <cycle_ms>` | 编译并执行，逐扫描输出 VAR_OUTPUT 轨迹 |
| `bin/plc-ld2st <rungs.json> <out.st>` | 把梯形图（LD）转换为等价的 ST |
| `bin/plc-xml-export <prog.st> <out.xml>` | 导出 PLCopen XML |
| `bin/plc-xml-import <in.xml> <out.st>` | 从 PLCopen XML 还原 ST |
| `bin/plc-serve <prog.st> <stim.csv> <cycle_ms> <port> <map.json>` | 以 Modbus TCP 服务端运行，按映射表暴露变量 |
| `bin/plc-hist <trace.csv> <query.json> <out.json>` | 历史库查询（聚合、时间窗、状态变化） |

所有入口用 `bash` 可直接调用（可以是脚本包装 Python）。

## 模块与契约

### M1 前端：词法、语法、语义分析
输入 ST 源码，输出 IR。IR 必须是 JSON，且包含：
```json
{"program":"Name","vars":[{"name":"x","kind":"input|output|local","type":"BOOL|INT|DINT|REAL|TIME|<FB类型>","init":<值|null>}],
 "body":[<语句>], "fbs":[{"name":"t1","kind":"TON"}], "diagnostics":[{"severity":"error|warning","line":N,"msg":"..."}]}
```
语句节点用 `{"op":"assign|if|case|for|while|repeat|call|exit","...":...}` 表达，具体字段自定，但必须能被 M2 单独消费。
语义检查至少覆盖：未声明变量、类型不匹配、给 VAR_INPUT 赋值、FB 实例未声明、CASE 分支值重复。
发现错误时 `plc-compile` 退出码非零且 `diagnostics` 非空。

### M2 运行时：扫描周期执行
消费 M1 的 IR，按固定扫描周期执行：采样输入 → 执行程序体 → 锁存输出。
运行时钟为 `scan * cycle_ms`，无墙钟时间。标准功能块 TON/TOF/TP/CTU/CTD/R_TRIG/F_TRIG/SR/RS 必须严格符合 IEC 语义。
整数溢出按二进制补码回绕，整数除法向零截断。

### M3 梯形图前端
`rungs.json` 的格式：
```json
{"program":"Name","vars":[...同 IR...],
 "rungs":[{"comment":"...","elements":[[{"type":"contact","var":"Start","negated":false},
   {"type":"contact","var":"Stop","negated":true}],[{"type":"contact","var":"Motor","negated":false}]],
   "output":{"type":"coil","var":"Motor","mode":"normal|set|reset"}}]}
```
`elements` 是**串联组的列表**，每个串联组内部是并联支路（即：外层 AND，内层 OR）。
转换出的 ST 必须与该逻辑等价，且能被 M1/M2 正确执行。

### M4 PLCopen XML 互操作
导出的 XML 必须符合 PLCopen TC6 的基本结构（`<project>` / `<types>` / `<pous>` / `<pou>` / `<interface>` / `<body>` / `<ST>`），
可被通用 XML 解析器读取。导入必须是导出的逆操作：`import(export(P))` 与 `P` 在**语义上等价**
（变量声明集合相同、执行轨迹逐格相同），文本可以不同。

### M5 Modbus TCP 服务端
`map.json` 把 PLC 变量映射到 Modbus 地址：
```json
{"coils":{"0":"Motor","1":"Alarm"},"discrete_inputs":{"0":"Start"},
 "holding_registers":{"0":"Count","1":"Setpoint"},"input_registers":{"0":"Level"}}
```
服务端在指定端口监听，按扫描周期推进程序，客户端读到的值必须与当前扫描的变量值一致。
必须支持功能码 1/2/3/4（读线圈、读离散输入、读保持寄存器、读输入寄存器）与 5/6/15/16（写）。
写入 `discrete_inputs` 或 `input_registers` 应被拒绝（这两类只读）。
REAL 变量映射到保持寄存器时按 IEEE754 大端占两个寄存器。

### M6 历史库
`query.json` 支持：
```json
{"type":"aggregate","var":"Count","fn":"min|max|mean|last","from_scan":0,"to_scan":100}
{"type":"transitions","var":"Motor"}            → 状态变化点列表 [{"scan":N,"from":0,"to":1}]
{"type":"duty_cycle","var":"Motor","from_scan":0,"to_scan":200}   → 为真的扫描占比
{"type":"downsample","var":"Level","every":10}  → 抽样序列
```

## 验收方式

你的实现会被这些检查独立验证，全部对你隐藏：

1. **差分模糊测试**（权重最大）：随机生成的 ST 程序与激励，你的 `plc-run` 输出必须与参考实现逐格一致。
   数量不设上限，覆盖全部语言特性与功能块。
2. **既有回归集**：10 个人工编写的程序与轨迹。
3. **诊断测试**：一批含错误的 ST，必须报错且定位到正确行。
4. **梯形图等价性**：LD 规则集与其 ST 参考实现的轨迹比对。
5. **XML 往返**：`import(export(P))` 与 `P` 的轨迹逐格一致，且导出的 XML 结构合法。
6. **Modbus 一致性**：用标准 Modbus 客户端（pymodbus）连接你的服务端读写，与预期值比对，含只读拒绝与 REAL 编码。
7. **历史库**：查询结果与参考计算比对。
8. **契约测试**：M1 的 IR 能被独立消费；模块边界不得互相穿透。

## 硬性约束

- 纯 Python 标准库（可用 NumPy）。**不得使用任何现成的 IEC 61131-3 工具链**（MatIEC、OpenPLC、Beremiz 等），
  不得使用现成的 Modbus 库实现服务端（pymodbus 仅用于测试你的服务端，不得被你引入）。XML 可用标准库 `xml.etree`。
- 每个模块可独立测试；不要把所有逻辑塞进一个文件。
- 写 `ARCHITECTURE.md` 说明模块划分、IR 设计与关键取舍；写 `TESTING.md` 说明你自己跑了哪些测试及结果。
