# legacy/skill-alpha —— 早期五文件 alpha（仅作历史）

这是**被取代的**早期技能实现：单个 `scripts/answer.py` 加三份 Markdown 参考，
回答出口统一返回 `PENDING_REVIEW`，覆盖借贷、租房、婚姻财产等十二个计划场景。

它**不是**当前公开发布的技能。当前发布的技能在
[`skill/civil-code-plain-answers/`](../../skill/civil-code-plain-answers/)，
范围收窄为 `rent_deposit` 一个场景的公开材料导航（D1）。

保留此目录的原因：仓库里早期更大范围的工程材料（`scripts/`、`tests/`、`reports/`、`plan/`）
仍在引用这套实现，删掉会让那些测试和脚本失去目标。

- 不要把它打进任何发布包。
- 它没有任何专业法律复核记录，也不提供法律解释。
- 相关测试：`tests/test_answer_exit.py`、`tests/run_case_catalog.py`。
