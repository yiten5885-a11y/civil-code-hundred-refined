# 法律专业复核交接

当前 `rules/approved/` 中没有真实通过的规则，全部场景保持关闭。模型自评、另一个模型评价、程序结构测试和网页安全扫描均不能替代法律专业人员对规则的审核。

复核人员应按每条候选规则及其三轮示例逐项确认：引用的正式文件和现行效力；公布与施行时间；涉及 2021 年前事实时的时间效力；条文、款项、例外和司法解释是否完整；普通话术是否改变法律含义；哪些事实缺失时只能追问；哪些结论不能推出。记录具体审核范围、身份类型或专业资质、日期、意见、退回原因。来源变化后重新审核受影响规则。

工程上，仅在复核真实完成后创建 `rules/approved/<rule-id>.json` 与 `review/<rule-id>.json`。规则至少包含 `id`、`status: approved`、`scenario`、已审核的固定 `approved_text`、`conditions`、`exceptions`、`required_facts`、`unsupported_conclusions`、`time_boundary`、`region`、`references`。引用记录必须含来源 ID、条号或定位、原文片段；民法典引用还需对应规范化条文哈希。

审核记录须写入 `decision: approved`、`reviewer`、`reviewer_role`、`scope`、`review_date`，以及审核时规则文件的 `rule_sha256` 和来源台账的 `source_manifest_sha256`。程序校验这些字段与当前文件能否对应，**不验证审核者真实资质，也不证明其法律判断正确**。不得为了让程序通过而填写虚构的审核者或“已核验有效”状态。

完成复核后，重新跑来源比对、程序故障注入、法律与事实验收、多轮对话和普通读者理解测试；只有实际通过的场景可列为对外开放。
