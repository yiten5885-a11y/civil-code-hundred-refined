# 民法典百炼白话问答

面向中国大陆**住宅租赁押金**场景的开源 Agent Skill。用户用自己的话描述情况，得到：先核对什么、合同里哪几句话要紧、相关官方条文原文与位置，以及一段可以自己修改后再发送的中性沟通文字。

**当前公开版本：D1 —— 只做材料导航。** 本技能**不给法律结论**。法律解释能力（`LEGAL01` / `LEGAL02`）**未开放**，因为没有真实的专业法律复核记录。范围只有 `rent_deposit` 一个场景；这不等于覆盖了中国租房法律，也不等于原计划的十二个场景。

[English](README.md)

## 现在能做什么

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| NAV01–NAV03 | 开放 | 定位押金条款；整理退房交接事实；把扣款项目与材料对应起来 |
| DRAFT01 | 开放 | 中性沟通草稿，是否发送由用户决定 |
| SOURCE01 | 开放 | 指向官方条文（只给原文与位置，不作解释） |
| DIALOG01 | 开放 | 多轮补充与纠正；旧前提失效后重新判断 |
| LEGAL01 / LEGAL02 | **未开放** | 需要真实法律专业复核；当前返回 `PENDING_REVIEW` |

## 运行

只需要 Python 3 标准库。路径相对模块位置解析，从任意工作目录都可运行。

```sh
python3 skill/civil-code-plain-answers/scripts/answer.py --question "押金还没退，我该先看什么？"
python3 skill/civil-code-plain-answers/tests/run_tests.py
```

`stdout` 只输出一个 JSON envelope。用户可见文字是 `text` 字段，必须整段原样展示（`render_contract.allow_host_append` 为 `false`）。退出码：`0` 正常结束（含适当的有限答复）；`2` 请求或运行故障；`3` 输出校验失败。退出码 `0` **不等于**问答验收通过。

模型后端是可选项。把 `skill/civil-code-plain-answers/config/example.json` 复制为 `config/local.json` 即可指向本机 Ollama。没有可用本地模型时，流程降级到 `heuristic-no-model`——一条确定性的、只用已核对模板的路径，不产生自由法律文本——并在 `reason_codes` 里如实给出 `MODEL_UNAVAILABLE`。它不会静默改用云端模型。

## 不做什么

不预测胜诉率或裁判结果，不给可退金额、扣款比例、全国统一退款天数、诉讼时效结论、诉讼费或管辖法院结论，不代为起诉或提交材料，不向第三方发送消息。用户要求这些时，继续提供当前能支持的材料帮助。

## 目录

- `skill/civil-code-plain-answers/` —— 技能本体：`SKILL.md`、`LICENSE.txt`、`config/`、`references/`（规则、模板、来源、审核、发布清单）、`scripts/`，以及开发用的 `sources/`（官方快照）、`tests/`、`tools/`。
- `scripts/`、`tests/`、`reports/`、`plan/`、`sources/SOURCE_MANIFEST.json` —— **早期**更大范围的工程材料（自然人借贷、住房租赁、婚姻财产，原计划十二个场景）。仅作历史保留：其中没有任何能力被启用，规则从未取得专业复核，也不再驱动当前发布的技能。
- `docs/法律专业复核交接.md` —— 交给法律专业人员复核的交接说明。

## 打包

```sh
python3 scripts/package.py          # 生成 dist/ 下的压缩包与 dist/PACKAGE_MANIFEST.json
python3 tests/smoke_package.py      # 解压 SkillHub 包并检查运行契约
```

SkillHub 上架包只含运行时子集；`tests/`、`tools/`、`sources/`、`evidence/` 不进公开包。

## 状态与门禁

`skill/civil-code-plain-answers/references/release-manifest.json` 是"哪些能力被启用"的唯一依据。当前如实状态：

- 程序测试 33/33 通过；1 项未运行（需要真实本地模型）。
- 没有任何专业法律复核记录，因此 `LEGAL01`/`LEGAL02` 保持停用。
- 收紧技能指令后，宿主最终展示文字尚未重新实测。

## 许可

本项目自有代码与文档采用 MIT 许可（见 `LICENSE` 与 `skill/civil-code-plain-answers/LICENSE.txt`）。`references/sources.json` 中引用的官方法条来自政府公开页面，仅用于引用与定位；第三方评注、出版物与图片不在此分发，也不在 MIT 授权范围内。

请勿把真实身份、账号或保密案卷放进本仓库或其 Issue。
