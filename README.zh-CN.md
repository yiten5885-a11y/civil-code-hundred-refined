![民法典百炼白话问答封面：借贷、租房、婚姻财产；理清事实、查找法源、关键追问；工程内测](assets/cover.jpg)

# 民法典百炼白话问答（工程内测）

这是面向中国大陆自然人借贷、住房租赁和婚姻财产问题的开源 Agent Skill 工程原型。当前版本 **未开放法律解释**：候选规则没有法律专业复核记录，`rules/approved/` 为空。项目支持来源快照、民法典逐条完整性比对、候选与审核规则分离，以及受控回答出口的故障阻断。不要将它用于替代律师意见或宣称十二场景已经验收。

## 运行

需要 Python 3 标准库和 `curl` 下载官方资料，不依赖云端模型。开发用法：

```sh
python3 scripts/source_pipeline.py fetch
python3 scripts/source_pipeline.py build
python3 scripts/normalize_companions.py
python3 scripts/crosscheck_marriage_registration.py
python3 scripts/normalize_loan_lease.py
python3 scripts/crosscheck_private_lending.py
python3 scripts/check_source_hashes.py
python3 scripts/search_sources.py --term 押金 --source housing_lease  # 本地原文排查，须先抓取与建索引
python3 scripts/generate_all_candidates.py --host 'http://[::1]:11434'  # 仅用本机 Qwen，生成十二张未审候选
python3 scripts/generate_evidence_supplement.py rent_deposit --host 'http://[::1]:11434' --dry-run
python3 scripts/generate_evidence_supplement.py loan_no_note --host 'http://[::1]:11434' --dry-run
python3 scripts/generate_evidence_supplement.py loan_overdue --host 'http://[::1]:11434' --dry-run
python3 scripts/generate_evidence_supplement.py divorce_agreement_registration --host 'http://[::1]:11434' --dry-run
python3 scripts/generate_evidence_supplement.py rent_repair --host 'http://[::1]:11434' --dry-run
python3 scripts/generate_evidence_supplement.py rent_early_end --host 'http://[::1]:11434' --dry-run
python3 scripts/generate_evidence_supplement.py rent_deposit --host 'http://[::1]:11434'
python3 scripts/generate_evidence_supplement.py loan_no_note --host 'http://[::1]:11434'
python3 scripts/generate_evidence_supplement.py loan_overdue --host 'http://[::1]:11434'
python3 scripts/generate_evidence_supplement.py divorce_agreement_registration --host 'http://[::1]:11434'
python3 scripts/generate_evidence_supplement.py rent_repair --host 'http://[::1]:11434'
python3 scripts/generate_evidence_supplement.py rent_early_end --host 'http://[::1]:11434'
python3 scripts/package_review_candidates.py  # 私人专业复核包，不是发布包
printf '%s\n' '{"question":"押金还没退，我该先看什么？","scenario":"rent_deposit"}' | python3 skill/civil-code-plain-answers/scripts/answer.py
python3 -m unittest discover -s tests -v
```

原始法条快照与规范化全文只在本地生成，不包含在 MIT 发布内容中。`search_sources.py` 对所选来源的原始快照和分条索引核对清单哈希后返回条文、定位与来源网址；民法典检索结果还包含编、分编、章、节和附则定位；关键词命中不表示资料齐全、现行有效或适用于具体案件。九份单篇配套文件的程序提取数量见 `reports/COMPANION_EXTRACTION.json`；其中 2025 年《婚姻登记条例》的生态环境部转载和司法部行政法规库各提取 28 条，按条自动对照无实质文本差异，见 `reports/MARRIAGE_REGISTRATION_CROSSCHECK.json`。最高法合辑中的城镇房屋租赁和民间借贷解释分别提取为 16 条和 31 条，见 `reports/LOAN_LEASE_EXTRACTION.json`。民间借贷的第二份最高法网站文本逐条自动对照结果见 `reports/LENDING_CROSSCHECK.json`。`reports/SOURCE_HASH_AUDIT.json` 核对本地快照及分条索引与来源清单的哈希。分条复查曾发现三份司法解释的 16 个分节标题误并入前一条，解析器已按官方网页中的确切标题排除并重新计算索引哈希；条数和条号未变，差异见 `reports/COMPANION_EXTRACTION.json`。下载得到的法条文本仍须检查效力及适用条件；机器完整性报告不是法律正确性鉴定。

上例的 `--host` 是本机经检查有 Qwen 的 IPv6 回环地址；其他机器可改为其实际 Ollama 回环地址（默认 `127.0.0.1:11434`），生成脚本拒绝远端地址和代理转发。模型输出若截断或格式错误，会留下私人的 `.partial.txt` 并拒绝保存候选；再次运行前会归档已有片段。新生成的第三轮必须逐字引用并撤回前两轮用户说过的事实；程序只核对文本绑定，不能判断语义是否正确。`package_review_candidates.py` 将当前证据清单中的六份补充候选、旧版备份及机器审计状态一并送交复核；结构检查通过也不代表法律语义正确。

## 结构与状态

- `skill/`：可导入 Agent Skills 宿主的技能包。WorkBuddy 5.7.7 的两条合成问题已实测加载与执行脚本；第二条在脚本返回 `PENDING_REVIEW` 后，宿主仍自行补写了未审核的判断。技能指令已收紧，修订后宿主复测待完成；不能宣称任意输入都会受程序强制拦截。
- `sources/SOURCE_MANIFEST.json`：来源、下载时间和快照哈希；效力状态当前待核验。
- `rules/candidates/`：模型草稿，永不直接进入回答出口。
- `rules/approved/` 与 `review/`：只接收真实专业复核后的规则和记录。
- `tests/`：受控出口故障测试。法律答案验收和普通读者测试仍待进行。

当前未达到计划中的 80 组法律与对话验收、专业复核、读者理解测试和 SkillHub 宿主适配门槛。问题反馈可在未来公开仓库 Issue 中提交；请勿附带真实咨询中的身份、账户等个人信息。

### WorkBuddy 内测安装

运行 `python3 scripts/package.py` 生成 `dist/civil-code-plain-answers-skillhub-0.1.0-alpha.zip`。本机 WorkBuddy 5.7.7 的“上传技能”文件选择器虽能看到 ZIP，确认按钮却始终禁用。此次把 ZIP 解压后的 `civil-code-plain-answers/` 目录复制到 `~/.workbuddy/skills/`，宿主“已安装技能”显示该技能且开关为启用。押金和借款／投资两条合成问题中，宿主都运行 `answer.py` 并得到 `PENDING_REVIEW`；第二条最终答复却自行加入未审核推断，因此普通 Skill 宿主的最终文字不能视为受程序强制拦截。安装前请确认没有同名目录，避免覆盖已有技能。具体过程见 `reports/TEST_REPORT.md`。

十二个场景各已生成一张本地 Qwen 候选卡和连续三轮示例，通过机器结构与来源哈希绑定检查；这不代表法律内容通过审核。`plan/SUPPLEMENT_EVIDENCE.json` 显式列出多来源补充候选的暂定输入与必引条文；`generate_evidence_supplement.py` 只接受本机回环 Ollama 地址，输出仍留在私人候选区。私人复核包包含候选、重点复核提示、80 组验收空白工作表和本地规范化原文，位于 `dist/民法典百炼-专业复核候选包.zip`，不进入公开 Git 仓库或 SkillHub 安装包。工作表的开发集与最终保留集只记录合成输入，法律预期仍须专业人员独立填写。
押金场景的私人补充候选已用本地 Qwen 重生，当前四条必引来源及第三轮逐字更正通过结构检查；人工阅读却发现把“无正当理由不得扣减”倒写成“扣减仍须无正当理由”的硬性错误。已加入精确短语回归阻断并标记退回；结构通过不代表法律正确，不进入公开安装包。
无借条转账场景另有一份纳入民间借贷解释的私人补充候选；模型首次输出截断被拒，第二次保存后仍发现诉讼条件泛化和债务方向含糊等问题，已列入私人复核提示，不进入公开安装包。
离婚登记场景另有一份纳入 2025 年《婚姻登记条例》的私人补充候选；新检查发现对话引用条例第 14 条却漏列在引用清单，且“2024 年签协议”示例把签署时间直接用于判断 2025 年条例适用，结构与法律语义均待退回核查。押金补充稿也被新检查发现对话提及民法典第 733 条却未列入引用清单。两稿都留在私人候选区；押金稿后来重生虽补齐引用，仍因已知法律含义倒置被退回。审计结果见 `reports/SUPPLEMENT_AUDIT.json`。
十二张原始候选都只读取少量民法典条文，可能遗漏司法解释、特别规定和时间适用；下一轮资料排查范围见 `plan/SOURCE_COVERAGE.md`，不能凭候选数量宣称场景覆盖完成。

租房维修场景有一份输入民法典维修条款及《住房租赁条例》第 2、35、49、50 条的私人补充稿。它的第二稿通过条号与哈希检查，但新增加的逐字撤回前述事实检查未通过，当前结构审计为 `false`；内容还把自行维修费用泛化为“索赔”，并把条例适用前提与民法典维修规则混写。具体退回点见私人 `rent_repair.REVIEW.md`。

借款到期未还场景新增一份输入民法典、民间借贷规定和时间效力规定的私人补充稿。旧稿第三轮所谓“更正”只是新增展期事实，现由严格检查拦下并留在私人备份；重生稿逐字撤回先前用户原话，结构检查通过，但仍把逾期利息条件、LPR 上限与展期后的期限判断说得过满。私人 `loan_overdue.REVIEW.md` 已标记退回；不进入公开安装包。

提前退租场景新增一份输入民法典、合同编通则解释和时间效力规定的私人补充稿。它的第二次重生通过引用与第三轮撤回的字面检查，但遗漏不定期租赁的合理期限前通知条件，并在租期未核实时提前假定定期；更正后的事实也不能单凭“合同写了租期”直接给出确定结论。私人 `rent_early_end.REVIEW.md` 记录了退回点，不进入公开安装包。

## 回答流程

范围与事实识别 → 检索已核对原文和审定规则 → 依据与前提不足则追问或有限说明 → 充足时由模型准备候选 → 程序检查 → 通过才显示已审核文本，失败则停止相关法律结论。详见 `skill/civil-code-plain-answers/references/workflow.md`。受控程序现要求已审核规则写明日期、地区和具体事实模式，并在用户更正结构化事实后重新匹配；宿主是否能可靠整理自由文本中的事实仍需实测。当前没有已审定规则，因此法律解释分支保持关闭。

## 许可

项目自有代码和文档采用 MIT 许可。第三方官方法条网页、出版社材料及用户咨询不在 MIT 授权范围内；本仓库不分发它们的全文。
