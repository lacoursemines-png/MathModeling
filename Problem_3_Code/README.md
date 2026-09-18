# A题第三问代码

本目录实现问题二方案的精确时间评价、同Pipe顺序边、关键路径、资源感知候选调度、
搬移预算筛选、局部前移和当前搜索集合内的非支配筛选。

第三问代码通过相邻的`Problem_2_Code`复用已验证的连续地址、SPILL与问题二验证器，
但不会修改问题二代码或结果。

## 固定口径

- 主结果：`alpha=0`，`Dmax=问题二实际D`；
- 补充预算：`alpha=0,2%,5%,10%`；
- `Dmax=floor((1+alpha)*D2)`；
- 每个候选重新计算实际D并验证`D<=Dmax`；
- 先满足硬预算，再最小化T；T相同时选择D更小的方案；
- 只将当前已搜索集合中的非支配方案称为非支配解，不宣称完整Pareto前沿；
- L0单驻留默认关闭。

## 运行六个算例

```cmd
cd /d "D:\MathModeling\04_模拟训练\Problem_3_Code"

python run_problem3.py --input "D:\MathModeling\04_模拟训练\A题\通用神经网络处理器下的核内调度问题附件\Json版本" --problem2-output "D:\MathModeling\04_模拟训练\Problem_2_Code\output\Problem2" --output ".\output"
```

若目录结构改变，可额外使用：

```text
--problem2-code-dir "D:\MathModeling\04_模拟训练\Problem_2_Code"
```

## 输出

- `output\Problem3`：alpha=0主结果的schedule、memory、spill；
- `output\scenarios\alpha_XXpct\Problem3`：各预算情景详细结果；
- `output\logs\*_summary.json`：D、T、预算、候选、参数、Pipe利用率；
- `output\logs\*_node_timing.csv`：各节点开始/结束时间及关键路径标记；
- `output\logs\*_pipe_intervals.csv`：各Pipe执行区间；
- `output\logs\*_candidates.csv`：全部成功候选及非支配标记；
- `output\logs\*_submission_verification.json`：正式文件写出后的回读验证；
- `output\logs\problem3_all_cases_budgets.csv`：六例四档预算汇总。

## 测试

```cmd
python -m unittest discover -s tests -v
```

正式输出可单独回读复核：

```cmd
python verify_problem3.py --input "D:\MathModeling\04_模拟训练\A题\通用神经网络处理器下的核内调度问题附件\Json版本" --output ".\output"
```
