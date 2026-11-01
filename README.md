# Prompt Previz · 用代码预演检查 AI 视频提示词

A Claude skill for AI video creators: **rehearse your prompt in code before you spend credits on a generation.**

把提示词拆成结构化的镜头规格，用脚本在"纸面上"把镜头演一遍——时长够不够、台词说不说得完、人物站在哪、拳打不打得到、镜头有没有跳轴、焦段会不会拉脸、背景到底虚不虚、光斑颜色对不对、措辞会不会反向召唤——然后给出修正后的提示词。

![report](docs/report-preview.png)

## 能查什么

| 类别 | 例子 |
|---|---|
| ⏱ 时间 | 5 秒塞 6 个动作；台词 7.5 词/秒；台词超出镜头结尾；超过模型单镜最大时长 |
| 📐 空间 | 跨 180° 轴线；人物在画框外却有动作；两人相距 2.6 m 却直接出拳 |
| 🔭 镜头 | 24 mm 拍脸；要虚化却没写对焦点；按景深公式算出背景其实是清晰的 |
| 💡 光 | 蓝色拉丝光斑挂在 3000K 暖灯上；画内没有光源却有光斑；胶片平衡与光线不符 |
| ✍️ 措辞 | 否定句（"no high kicks" 会召唤高踢腿）；品牌名；情绪副词；面部动作编排；武术术语 |
| 🎭 表演 | 说话的人没有表演任务 → 眼神死；倾听者没任务 |
| 🥋 打戏 | 高位踢；没有截击；出招过多；没有静止节拍 |
| 🎬 结构 | 反转没有带来观众对角色的评价转变（INERT）；整段没有反转 |

输出一份 HTML 预演报告：俯视走位图（机位 FOV 楔形 + 180° 轴线 + 人物朝向与移动）、节拍/台词时间线、问题清单与修法。

## 内置模块

| 模块 | 内容 |
|---|---|
| `anamorphic` | 变形宽银幕质感：焦段选择、强虚化的物理锚点、椭圆光斑与拉丝光斑、胶片描述、技术尾句 |
| `acting` | 表演任务（ACTING TASK）写法：场景方向 → 动机 → 目标 → 障碍 → 战术，让 AI 演员的眼睛"活"起来 |
| `fight` | 截拳道 / 咏春打戏编排：招式库（几何描述而非术语）、节拍套路、FIGHT STYLE LOCK |
| `scene-engine` | 场景引擎：目标 / 障碍 / 战术 / 反转 / 价值转变，用于写戏和审戏 |

## 安装

**Claude（claude.ai / Claude 桌面端）**：在 [Releases](../../releases) 下载 `prompt-previz.skill`，到 Settings → Capabilities → Skills 上传。

**Claude Code**：

```bash
git clone https://github.com/<you>/ai-video-prompt-previz
cp -r ai-video-prompt-previz/prompt-previz ~/.claude/skills/
```

然后直接对 Claude 说："帮我预演检查一下这段视频提示词" 并贴上提示词。

## 单独使用脚本

只需要 Python 3（无第三方依赖）：

```bash
cd prompt-previz
python3 scripts/previz.py check examples/alley-fight.json -o out   # 完整预演 → out/report.html
python3 scripts/previz.py lint my_prompt.txt --style jkd           # 只检查措辞
python3 scripts/previz.py schema                                   # 查看规格格式
```

镜头规格格式见 [`prompt-previz/references/shot-spec.md`](prompt-previz/references/shot-spec.md)。

## 结构

```
prompt-previz/
├── SKILL.md                     # 工作流与检查项速查
├── scripts/previz.py            # 预演 + 检查 + HTML 报告
├── examples/alley-fight.json    # 示例（故意埋了一堆问题）
└── references/
    ├── shot-spec.md
    └── modules/
        ├── anamorphic.md
        ├── acting.md
        ├── scene-engine.md
        └── fight/ (fight.md, jkd-core.md, moves-catalog.md, techniques.md, choreography-patterns.md, styles/wing-chun.md)
```
