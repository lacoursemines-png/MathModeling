# A题第一问代码

本目录实现“最小缓存驻留调度”的第一问，不包含地址分配、SPILL、Pipe时序或总周期计算。

## 实现内容

- 读取并严格检查赛题JSON；
- 派生Buffer、使用节点和COPY_IN信息；
- 构造“原始依赖 + 生命周期依赖”的调度DAG；
- 独立验证完整性、原始拓扑、Buffer生命周期和L0单驻留；
- 独立计算L1与UB合计峰值；
- 运行ID优先baseline和多种确定性内存感知策略；
- 对峰值附近窗口进行保守重排；
- 写出比赛规定的schedule文件，并回读验证；
- 保存配置、各策略峰值、运行时间和可选驻留曲线。

算法输出是“最佳已知可行方案”，不宣称为全局最优。

## 环境

Python 3.10及以上，只使用标准库，无需安装第三方包。

## 运行一个算例

在本目录打开PowerShell：

```powershell
python run_problem1.py `
  --input "D:\MathModeling\04_模拟训练\A题\通用神经网络处理器下的核内调度问题附件\Json版本\Matmul_Case0.json" `
  --output ".\output" `
  --trace
```

## 一次运行六个算例

```powershell
python run_problem1.py `
  --input "D:\MathModeling\04_模拟训练\A题\通用神经网络处理器下的核内调度问题附件\Json版本" `
  --output ".\output" `
  --trace
```

正式附件位于：

```text
output\Problem1\<任务名>_schedule.txt
```

辅助日志位于`output\logs`，不应放入最终比赛附件。

## 运行单元测试

```powershell
python -m unittest discover -s tests -v
```

## 常用参数

- `--strategies`：逗号分隔的策略列表；
- `--local-window-radius 0`：关闭峰值窗口局部改进；
- `--local-passes 2`：局部改进最大轮数；
- `--trace`：输出逐节点L1+UB驻留曲线。

所有策略都使用确定性Id作为最终并列规则，便于复现。
