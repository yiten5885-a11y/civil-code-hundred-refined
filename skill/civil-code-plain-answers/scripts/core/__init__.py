"""民法典·百炼白话问答 —— 受控流程核心。

本包只实现规格第五、六部分描述的程序化控制；法律解释能力是否开放由
references/release-manifest.json 与真实审核记录决定，运行时模型无权修改。
"""

__all__ = ["loader", "pipeline", "policy", "renderer", "validator", "rules", "facts"]
