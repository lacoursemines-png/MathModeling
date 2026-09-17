# A题第二问代码

本目录实现连续地址分配、ResidentSegment、多次SPILL、失败驱动回溯、最终重编号及独立验证。

程序只使用Python标准库。第一问代码和结果不会被修改。

## 默认实现口径

- 五类缓存分别使用题目给定容量和连续地址；
- 问题二默认不强制L0单驻留；
- 默认先做FREE优先、计算节点优先、ALLOC延后的容量感知拓扑重排；
- First-Fit与Best-Fit分别搜索，按搬移量选择较优合法方案；
- 同一Buffer多次SPILL时按驻留片段构造；
- SPILL_IN地址失败时允许继续SPILL其他同类驻留Buffer；
- 最终按schedule中SPILL_OUT顺序重新编号；
- 最终结果称为最佳已知可行方案，不宣称全局最优。

## CMD运行六个算例

```cmd
cd /d "D:\MathModeling\04_模拟训练\Problem_2_Code"

python run_problem2.py --input "D:\MathModeling\04_模拟训练\A题\通用神经网络处理器下的核内调度问题附件\Json版本" --schedule-dir "D:\MathModeling\04_模拟训练\Problem_1_Code\output\Problem1" --output ".\output"
```

正式文件位于`output\Problem2`：

- `<任务名>_schedule.txt`
- `<任务名>_memory.txt`
- `<任务名>_spill.txt`

分析文件位于`output\logs`：

- `<任务名>_summary.json`
- `<任务名>_resident_segments.csv`
- `problem2_all_cases_summary.csv`
- `problem2_all_cases_summary.json`

## 常用搜索参数

```text
--spill-candidates 3
--max-states 250
--max-spills 10000
--time-limit 10
```

默认`--schedule-policy capacity_aware`。`--schedule-policy reference`只用于
评估直接沿用第一问序列的对照结果；第二问不会修改第一问文件。

`--enforce-l0-single`只用于对照实验，正式第二问默认不要启用。

## 搜索与并列规则

- 主目标：额外搬移量D最小；并列时依次比较SPILL对数和策略名；
- 候选评分：优先下一次使用/最终FREE更远的驻留Buffer，再比较搬移系数、
  是否单次即可形成足够连续空间、连续孔洞增益、Size和BufId；
- `--spill-candidates`是单次失败的分支数，不冒充束宽；
- 搜索是受`--max-states`约束的最佳优先搜索，没有固定束宽；
- 前瞻使用精确的下一次使用或FREE位置，没有固定窗口大小；
- 每个地址策略先生成贪心可行上界，再受时间、状态数和SPILL数共同限制；
- 所有结果均为最佳已知可行解，不宣称全局最优。

## 测试

```cmd
python -m unittest discover -s tests -v
```
