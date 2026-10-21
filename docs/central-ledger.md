# 中央文献台账与两路流水线

适用版本：0.9.0.dev4。SQLite WAL由中央服务独占访问，工作节点通过带访问密钥的HTTP接口领取任务、续租和提交结果。默认仅监听本机；远程使用SSH通道或配置鉴权及TLS的反向代理。

## 安装与启动

```sh
python -m pip install '.[full,ledger]'
paper-citations-ledger --db /path/to/data/ledger.sqlite3
```

默认地址为 `http://127.0.0.1:8765`。访问密钥从 `CITATION_LEDGER_TOKEN` 读取，未设置时在数据库目录生成 `ledger.token`。模型密钥使用 `PAPER_CITATIONS_API_KEY`，两者不能混用，也不要提交至仓库。

导入格式见 [CSV模板](../examples/ledger-import-template.csv)。导入后登记PDF路径及SHA256，再按目标组织、程序版本和配置指纹建任务。工作节点只读取允许目录内且哈希一致的PDF。

## 节点配置

建立运行配置，沿用已有编号档案；模板目录可用 [UNEP模板](../templates/UNEP)。模型配置示例见 [GLM-5.3-Flash](../examples/glm-5.3-flash.json)，在运行配置中通过 `api_config` 引用。模型不自动替换已有设置。

`profiles.json` 示例（替换为自己的绝对路径）：

```json
[{"name":"UNEP","config":"/path/to/run.json","pdf_roots":["/path/to/papers"]}]
```

启用两路流水线的启动示例：

```sh
export PAPER_PIPELINE_LANES=2
export PAPER_MIN_AVAILABLE_MB=768
export PAPER_STOP_AVAILABLE_MB=500
paper-citations-worker --url http://127.0.0.1:8765 \
  --token-file /path/to/data/ledger.token \
  --profiles /path/to/profiles.json --work-dir /path/to/runs
```

500 MiB为暂停阈值，768 MiB为重新领取阈值，两者留出恢复余量。不设置时资源保护默认值更保守；操作系统或容器的硬内存限制仍然独立生效。资源配置应结合Docling和GROBID占用调整。

解析路完成一篇后保存缓存并退出子进程，审查路随后进行GLM核查及导出；此时解析路可处理下一篇。最多同时持有两篇任务，审查与编号写入保持串行。解析路只验证编号快照，不占用审查路写锁。两篇任务各自续租，缓存与日志按任务和尝试次数隔离。

## 监测与失败处理

台账页面显示最近一小时落账论文及模型输入、输出token曲线，约每10秒刷新。token来自实际调用usage记录并去重；缺少usage时不能据此推定为零消耗。落账数量表示处理完成，不表示引用已经确认。

任务、失败原因和历史事件可在台账查看。内存压力、服务不可用、PDF或模型错误应分别处理。失败不应直接归因于内存不足；先查阶段日志和系统OOM事件。显式失败不自动重试模型；确认原因和缓存后再重排。租约过期可能触发重新领取，不能据此承诺外部API恰好调用一次。

## 版本升级与备份

停止领取并等正在处理的任务完成，备份SQLite（使用SQLite backup API，不能只复制运行中的主文件）、编号档案、配置与结果。安装新版后重新计算配置指纹，并检查待处理任务绑定的程序版本：旧版本任务不会被新版本节点自动领取。迁移时只调整尚未处理的任务，保留已完成任务的原版本与结果追踪信息。

不要删除或重置编号档案。发布GitHub新版本不会自动升级正在运行的服务器。

当前实现为单中央服务、共享访问密钥的部署方案；文件传输、多用户角色、PostgreSQL及高可用不在本版范围。

## 单篇超时自动处理

解析整篇论文默认最多10分钟（`PAPER_PARSE_TIMEOUT_SECONDS=600`），GLM审查及导出默认最多15分钟（`PAPER_REVIEW_TIMEOUT_SECONDS=900`）。这是单篇阶段的最长处理时间，不是根据日志静默时间猜测卡死；复杂论文也可能被标记超时，需另行复查。

达到上限后终止该篇进程组、释放资源，记录`stage_timeout`并继续其他论文。原文、阶段文件和日志保留；不自动重试超时论文或重复调用模型。连续多篇超时不会触发原有“连续三篇一般错误”全队列锁定。其他系统错误仍保留原有保护。台账显示每个通道已用时间及上限。

服务器的MemoryHigh软限制与整机500 MiB保护是两项独立设置；本部署将MemoryHigh固定为2700M，MemoryMax保留2800M。不要以容器仍在线推断解析已有进展。
