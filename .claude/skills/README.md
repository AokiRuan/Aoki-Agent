# Skills

本目录存放本项目的 Claude Code skill。每个 skill 一个子目录，**必须**包含 `SKILL.md`：

```
.claude/skills/
└── <skill-name>/
    └── SKILL.md
```

`SKILL.md` 的 frontmatter 格式：

```markdown
---
name: skill-name
description: 一句话说明这个 skill 做什么、什么时候该用它。Claude 靠这句话判断是否加载。
---

（这里写具体指令：步骤、约定、注意事项）
```

关键点：

- **`description` 决定加载时机**。Claude 在会话中只看得到 `name` + `description`，据此决定要不要读取正文。所以描述要写清"触发条件"，而不只是"功能是什么"。
- **正文是延迟加载的**。只有 skill 被调用时正文才进入上下文，因此可以写得详细，不用担心占用 token。
- 用 `/<skill-name>` 可以手动触发。

参考：[项目计划](../docs/project-vision.md)。
