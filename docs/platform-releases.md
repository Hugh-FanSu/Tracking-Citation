# Mac 和 Windows 安装、更新与发布

同一份 Python 源码同时维护两个平台，版本以 `pyproject.toml` 和包内 `__version__` 为准。

## 使用者

先安装 Python 3.12（包含 Tk；Windows 需要 Python Launcher）、Docker Desktop，再启动仓库的 GROBID：`docker compose up -d`。默认只开放本机8070端口。已有兼容GROBID服务时可复用。

从 GitHub Releases 获取对应平台压缩包，解压后双击 `Install-macOS.command` 或 `Install-Windows.cmd`。安装需要联网下载依赖，首次解析还可能下载Docling模型；完成后打开图形工作台。

安装位置：Mac 为 `~/Tracking-Citation`，Windows 为 `%LOCALAPPDATA%/Tracking-Citation`。图形启动器在该目录。更新时解压新版并再次执行安装脚本，升级相同环境；论文、模板和编号文件保留在用户自己的数据目录。运行更新前先退出应用。

这些是带安装脚本的分平台发行包，不是内嵌Python/GROBID的独立.app/.exe；目前未做签名或公证，未承诺Windows完整PDF端到端验证。Mac的Apple Silicon和Intel共用安装脚本，依赖会按本机平台安装。

## 维护者

当前Actions工作流尚未上传：推送凭据缺少GitHub的`workflow`权限。以下自动测试/发布步骤需先上传`.github/workflows/test.yml`和`release.yml`才生效；当前仓库尚不会自动生成平台ZIP。

1. 修改代码并同步两个版本号，更新说明。
2. 推送分支，查看Mac/Windows测试结果。CI使用合成数据，不上传研究论文、不调用付费API；不安装Docling大模型，不代表完整解析验证。
3. 需要正式发布时，创建与版本一致的标签，例如 `v0.8.1` 并推送。
4. Release workflow在两个平台运行测试、构建wheel和源码包，并组装平台ZIP。两个任务成功后创建GitHub草稿Release；检查产物后手动发布。
5. 不发标签也可手动运行workflow检查打包，Actions产物可下载。

无自动应用内更新；新版安装脚本负责覆盖升级工具依赖。不要提交PDF、已填写Excel、编号档案、API Key或本地运行输出。
