# 安装、更新与发布

当前版本为0.9.0.dev4开发预发布；版本号由 `pyproject.toml` 和包内 `__version__` 同步维护。

## 使用者

从GitHub Releases下载Mac或Windows安装包。先安装Python 3.12（包含Tk，Windows还需Python Launcher）和Docker，再在解压目录运行 `docker compose up -d` 启动GROBID。已有兼容服务可复用。

双击 `Install-macOS.command` 或 `Install-Windows.cmd`。安装需要联网；首次解析可能下载Docling模型。Mac安装到 `~/Tracking-Citation`，Windows安装到 `%LOCALAPPDATA%/Tracking-Citation`。模板、文档和配置示例复制到其中的 `resources/0.9.0.dev4/`。

更新前退出程序，再运行新版安装脚本。已有论文、编号和项目模板保留在原数据目录；新模板放在版本资源目录供选择。台账升级另见[队列版本迁移说明](central-ledger.md)。

安装包不是内嵌Python/GROBID的独立.app或.exe，未签名或公证。Windows完整PDF端到端解析尚未实机验证。

## 维护者

```sh
python -m pip install '.[ledger,dev]'
PYTHONPATH=src:src/paper_citation_pipeline/engine/runtime python -m unittest discover -s tests
python scripts/build_release.py
```

构建输出位于 `release/<版本>/`，包含wheel、源码、两个平台安装ZIP、模板ZIP和SHA256SUMS.txt。检查内容后推送提交与对应版本标签，并上传到GitHub预发布页。

本次手工测试、构建和发布。当前凭据只有repo权限，没有workflow权限，GitHub Actions工作流未上传；不宣称自动发布或跨平台CI通过。

不得发布PDF、已填写采集表、项目编号档案、API密钥、台账数据库或运行日志。
