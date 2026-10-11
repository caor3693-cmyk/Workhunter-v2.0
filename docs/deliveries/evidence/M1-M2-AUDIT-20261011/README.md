# M1/M2 对抗审查隔离反例

审查应用为 b6300f4991d4c9a36ecf8f425a6de578c0106275，资料基线为 b17f67d13321bb236728baf51198221f1b58e366。

这些脚本是**失败行为复现材料**，不是修复后的通过测试。前端使用手工 DOM 和可控 Promise；来源测试使用生产 ScutAdapter、服务、SQLite 与 HTTP MockTransport；材料测试使用生产写入/查询和临时 fixture 库。脚本不读取真实业务库、不访问官方来源、不修改应用文件，结果写标准输出；临时数据库自动清理。

在仓库根目录、已安装仓库开发依赖的环境执行：

~~~bash
node docs/deliveries/evidence/M1-M2-AUDIT-20261011/reproduce_frontend.mjs
python docs/deliveries/evidence/M1-M2-AUDIT-20261011/reproduce_sources.py
python docs/deliveries/evidence/M1-M2-AUDIT-20261011/reproduce_material_scope.py
~~~

结果摘要见 [机器可读审查证据](../M1-M2-AUDIT-20261011.json)；环境差异和证据边界见 [审查报告](../../M1-M2-AUDIT-20261011.md)。前端 logical_ms 为人工事件序号，不是现场毫秒/远端 p95。合成来源 URL 由 MockTransport 截获，不能计作官方覆盖。

本材料适用于审查时的应用实现。修复会使部分“复现旧错误”的断言失败；实施者应把必要案例转换到正常测试目录，断言修复后的合同，而不是继续要求错误存在。
