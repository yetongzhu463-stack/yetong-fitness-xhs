# YETONG 四个 Skill：本地预发布验证

日期：2026-10-03。此记录只描述当前源码和本地预览包，不代表公开发布、远端安装或其他教练的真人效果。

## 可复现命令

在源码根目录运行：

```sh
python3 yetong-fitness-xhs/scripts/validate_registry.py
python3 -m unittest packaging/test_registry.py
python3 packaging/build_bundle.py
python3 packaging/test_local_install.py 'dist/替换为刚生成的预览包名.zip' --agent-smoke
```

本次另用维护者本机的 DBS Skill Maker 分别检查四个 Skill 的结构；它不进入运行包，也不是用户使用四个 Skill 的依赖。以上命令来自本源码；预览包名由构建指纹决定。

## 本次结果

- 四个 Skill 结构检查均通过，提醒数为 0；登记表五项单元测试通过。
- 最新 allowlist 预览包包含 28 个运行／文档文件及一份哈希清单；根目录和四个 Skill 目录都含相同的 MIT 许可证，不含人物档案、会员资料、原 PDF、真人试稿、评测文件或工作区绝对路径。
- 从解压后的本地目录使用 `npx skills add` 复制到临时 Codex 项目，四个 Skill 入口、各自的授权文件和登记资源齐全，安装后资源哈希与清单一致。人物档案模块的结构校验可读取合成 active 与 draft；选题、文案模块的门槛对 active 返回 0、对 draft 返回 2。临时目录自动清理，未写入全局 Skill 目录。
- 在该**安装后的临时目录**里，实际运行一次 Codex Agent：合成 active 档案收到“今天不知道发什么；先给两个题；授权代选一个再写短稿”的请求。主入口通过登记校验，顺序调用选题与文案；输出两个具体本地题，选择证据更完整的“午休只有半小时”问题并写测试稿，列出三个 YETONG Skill ID 和两次 active 预检结果。
- 同一隔离环境的合成 draft 档案收到“按我的经历写个性化文案”的请求。Agent 未生成个性化稿，给出固定未激活提示并引向人物底色访谈。
- 当前工作区中叶童已激活档案的非盲试跑另记于其私人目录：模糊请求进入选题，模拟选定题进入文案，未激活样本被拦截。试稿未经本人新一轮文风确认，不能视作可直接发布稿。

## 验证边界

本地目录安装和本地 Agent 端到端冒烟已验证；本记录**不证明**直接用 ZIP 路径安装、GitHub 远端安装、其他 Agent 环境兼容、第二位教练真人个性化效果或实际流量／到店转化。作者后来确认采用 MIT 并同意公开提炼后的框架地图；远端安装须单独验证。
