# YETONG 健身教练小红书内容技能组

这套 Skill 帮助健身教练围绕**自己实际服务区域的线下潜在会员**，先建立经本人确认的人物档案，再做小红书选题与单篇文案。它不教同行获客，不面向全国线上招生，也不承诺播放量、咨询量或训练效果。

项目采用 [MIT 许可证](LICENSE)，作者已同意公开本项目自行提炼的内容框架地图。原课程 PDF 及右侧完整示例文案不在项目或许可证范围内。

## 四个能力

- [`yetong-fitness-xhs`](yetong-fitness-xhs/SKILL.md)：主入口，按需求和材料状态选择已登记模块。
- [`yetong-fitness-xhs-profile`](yetong-fitness-xhs-profile/SKILL.md)：用简短访谈建立、确认和更新教练本人的人物 DNA。
- [`yetong-fitness-xhs-topic`](yetong-fitness-xhs-topic/SKILL.md)：把本地会员顾虑与本人真实素材转为选题，并标注四大内容类型。
- [`yetong-fitness-xhs-copy`](yetong-fitness-xhs-copy/SKILL.md)：根据已选题、本人资料和四类内容框架写单篇稿或改稿。

四个 Skill 应一起提供。主入口从[能力登记表](yetong-fitness-xhs/references/capability-registry.json)读取可用模块；新增模块需先登记、验证并一同交付，仅放入目录不会自动生效。DBS Skill Maker 可以作为维护者自己的制作工具，但不是使用本技能组的前置依赖，也不在运行包中。

## 安装

需要 Node.js／`npx` 和能运行 Python 3.9 或更新版本的 Agent。安装四个 Skill：

```bash
npx -y skills add yetongzhu463-stack/yetong-fitness-xhs -g --all
```

`-g --all` 会安装到本机支持的各 Agent 的全局 Skill 目录；若只想安装到 Codex，可运行：

```bash
npx -y skills add yetongzhu463-stack/yetong-fitness-xhs -g -a codex --skill '*' -y
```

## 首次使用

以下是在四个 Skill 均已可用之后，对主入口说的话；Codex 中可显式调用 `$yetong-fitness-xhs`。

1. 尚未建档时，说：“我在〔城市／区域〕做线下健身，主要服务〔本地会员〕。先帮我建立人物档案。”访谈先问最少的业务、客户问题和服务动作；无需一开始讲完整人生。
2. 首次保存档案时，指定一个**在 Skill 安装目录之外、仅自己可访问**的位置。档案文件名为 `person-dna.md`。教练核对事实与公开边界并明确确认后，档案才会变为 `active`。
3. 建档后，可以说：“这是我的 `person-dna.md` 路径：〔实际路径〕。我今天不知道发什么，帮我找面向本地会员的选题。”有具体问题时也可以直接说：“我确定写〔会员真实顾虑〕，帮我写一篇。”
4. 需要更新城市、服务、产品或公开权限时，先改同一份档案并重新确认受影响的内容，再继续出题或写稿。

主入口不会搜索私人目录猜档案位置。没有已激活档案时，不能生成声称“像这位教练本人”的个性化内容；用户明确要求通用版本时，也不得套用别人的经历、城市或口吻。

## 发布与资料边界

MIT 允许使用、修改、分发和商业复用，但再分发时须保留版权和许可证声明。每个 Skill 的 `references/LICENSE` 都随其目录一起安装，以便单独安装后仍附有授权文本。

人物档案、会员记录、原课程 PDF、真人试稿和开发评测不属于可分发文件。会员姓名、照片、聊天记录与健康信息应分别取得相应公开授权；匿名数据也需要检查小城市和场馆信息组合后的反向识别风险。课程权益、价格和效果数字在具体发布前仍需核对原始依据。

本地结构、行为冒烟与隔离安装测试不等于跨平台运行或另一位教练的真人验证。已从本仓库远端发现并在临时 Codex 项目中复制安装四个 Skill，安装文件与发布版本一致；这不代表已安装到你的全局目录，也不承诺实际流量、咨询或成交结果。
