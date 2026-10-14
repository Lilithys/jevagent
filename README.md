# jevagent

在安卓手机上把游戏里的固定操作示范一遍，jevagent 记下你的每个手势和手指按下前的画面，之后照着做一遍。每一步都先确认画面和录制时一致再动手；画面不对就停下并说明原因，不会盲点。

当前阶段是 **M0：学习点击，完成相对固定的流程**，目标游戏是《哈利波特：魔法觉醒》。验收标准和测试场景见 [docs/M0.md](docs/M0.md)。

## M0 做什么，不做什么

| 做 | 不做（留给 M1 或以后） |
| --- | --- |
| 录制你在手机上的单指点击、长按、滑动/拖动 | 多指手势、键盘输入 |
| 回放前等录制时触点处的画面（锚点）出现并稳定，再执行；按钮位置略有移动时跟着移动 | 处理录制时没出现过的弹窗、按画面内容走不同分支 |
| 等不到画面就停止，报告失败画面与期望画面 | OCR 识字、LLM / Jev 判断 |
| 回放结束对比结束画面，自动判定成功或失败 | 定时无人值守运行 |
| HTML 报告：每步截图 + 手势 + 锚点；每次回放的结果 | iPhone、跨机型或跨分辨率复用 |

## 准备

- Apple Silicon Mac，[uv](https://docs.astral.sh/uv/)，adb：
  ```bash
  brew install uv
  brew install --cask android-platform-tools
  ```
- 安卓手机打开开发者选项里的 USB 调试，用数据线连接，在手机上允许这台电脑。设备层沿用 hawarma 在 HONOR ELZ_AN00（Android 14，横屏 2376×1152）上验证过的方案，这台手机可以直接用。
- 安装依赖（与 hawarma 相同的 Airtest 分支和版本）：
  ```bash
  uv sync
  ```

第一次截图时，Airtest 会往手机的 `/data/local/tmp` 放截图（minicap）和触摸（maxtouch）辅助程序；不需要 root，也不修改游戏。

## 使用

```bash
uv run jevagent devices                # 看手机是否连上
uv run jevagent check                  # 只读检查：画面尺寸、截图速度、触摸屏；不发送触摸
uv run jevagent record 商店来回         # 在手机上操作，最后回终端按 Enter 结束
uv run jevagent show 商店来回           # 打印步骤，打开报告核对每一步
uv run jevagent play 商店来回           # 回放；回放中按 Enter 停止
uv run jevagent play 商店来回 --times 10   # 连续回放（流程要回到起始画面），失败即停
uv run jevagent play A-战斗 --from 2       # 前面的步骤已手动做完，从第 2 步接着回放
uv run jevagent list                   # 所有流程与回放成功次数
uv run jevagent loop A-战斗 B-普通宝箱 C-滴答宝箱 --repeat B-普通宝箱 --times 3
                                       # 按顺序连起来循环 3 轮；--repeat 的流程做到它的起始画面不再出现为止
uv run jevagent edit 商店来回 --delete 3 --set 2.check=off --set 4.timeout=30
```

### 录制建议

1. 从一个稳定、容易回到的画面开始（例如主界面），先关掉无关弹窗。
2. 像平时一样在手机上操作。每一步等画面完全出来再按，按在按钮本身，不要按空白处。
3. 最后一步做完，等画面停稳，再回终端按 Enter。这时的画面是"结束画面"，回放用它判断是否成功。
4. 打开报告，确认每个红圈（滑动是红线）都落在你按的位置上。蓝色虚线框是回放时要先找到的画面。

### 回放怎么判断

- **先等，再找画面**：每步先等 `min(录制时的间隔, 1.5 秒)`，然后在录制位置附近（短边的 25% 范围内）找锚点。锚点要连续两帧匹配度 ≥ 0.60 且位置不变才执行。
- **按轮廓比**：锚点比较的是边缘（按钮、图标、文字的轮廓），不是颜色，所以按钮背后的页面变了（比如商店记住了上次的页签）也认得出来。实测：同一画面约 1.0，同一按钮换了背景 0.7–0.8，别的画面不超过 0.46。
- **等多久**：第 1 步最多 5 秒（你应该已经停在起点）；之后每步最多 `max(10 秒, 录制间隔 × 2)`，自动上限 10 分钟；更长的等待（例如自动战斗一直打到宝箱满）用 `edit --set N.timeout=秒数` 设，最多 60 分钟。加载慢时会一直等到画面出现。
- **点在空白处的步骤**（例如“点击任意处关闭奖励”）：触点周围没有可认的东西，所以改为“点到下一画面出现为止”——点一下，3 秒内没看到下一步的画面（最后一步则是结束画面）就再点，最多 5 次，仍不行就停下。空白处多点几下没有副作用，也不依赖动画的长短。
- **连续快速点击**：与上一步间隔不到 0.6 秒的点击（例如连点 4 次加号）按录制节奏原样执行，不检查画面，也不会多点。第 1 步即使不检查锚点，也会先确认整屏与录制起点一致。报告里会标出每一步用的是哪种方式，可用 `edit` 改。
- **结束**：所有步骤执行后，等画面与结束画面一致（最多 `max(10 秒, 2 × 录制时最后的停顿)`，上限 60 秒），才判定成功。
- **停止**：按 Enter，当前手势松开后停止；Ctrl+C 也能停，但如果正在长按或滑动，手指可能残留在按下状态，点一下屏幕即可恢复。拔线、换方向、分辨率变化都会立即报错退出，不会重试或重放已经执行的动作。

### 编辑

```bash
uv run jevagent edit 名称                          # 不带参数：列出步骤编号
uv run jevagent edit 名称 --delete 3 5             # 删除误触
uv run jevagent edit 名称 --set 2.check=off        # 这一步不检查画面（内容每天变化时）
uv run jevagent edit 名称 --set 6.until_next=on    # 点到下一画面出现为止（录制时点在空白处的步骤会自动打开）
uv run jevagent edit 名称 --set 6.tap=1200,210     # 改点击位置（滑动整体平移）
uv run jevagent edit 名称 --set 1.look=2035,960    # 检查这里、点击位置不变：例如跳过会变的数字，或确定前核对数量
uv run jevagent edit 名称 --set 4.timeout=40       # 加载慢的步骤多等一会；auto 恢复默认
uv run jevagent edit 名称 --set 4.delay=2          # 至少先等 2 秒
uv run jevagent edit 名称 --set 1.threshold=0.7    # 这一步要求更像（默认 0.6，一般不需要改；auto 恢复默认）
uv run jevagent edit 名称 --set 1.label=打开商店
uv run jevagent edit 名称 --set end_check=off      # 不检查结束画面
uv run jevagent edit 名称 --set end_look=1775,1052  # 结束时只看这一处（3D 地图每次取景不同时，看固定按钮）
```

只想改后半段时不用整段重录：`uv run jevagent record 名称 --from 7` 保留前 6 步，从第 7 步开始重录并替换后面的步骤和结束画面（手机先停在第 6 步刚做完时的画面）。

每次编辑版本号加 1，回放记录会记下所用版本。流程文件是可读的 JSON，也可以直接改。

## 数据

```text
data/flows/<名称>/
  flow.json        步骤：手势路径（截图像素坐标 + 时间）、录制间隔、回放设置
  step-01.jpg …    每步按下前的画面，锚点从这里截取
  end.jpg          结束画面
  getevent.log     录制时手机原始触摸事件（排查录制问题用）
  report.html      流程报告
  runs/<时间>/     每次回放：run.json、最后看到的画面 last.jpg、report.html
```

`data/` 不进 git：截图里有你的游戏账号画面。

## 代码

```text
src/jevagent/
  cli.py        命令行
  device.py     ADB 设备选择、截图（MINICAP_APK）、触摸（MAXTOUCH）、getevent 原始触摸流
  touch.py      解析 getevent（多点触控协议 A/B）→ 手势；屏幕方向换算
  recorder.py   录制：后台取帧 + 读取触摸，每个手势配上按下前的画面
  vision.py     锚点截取与匹配、整屏相似度
  player.py     回放：等锚点 → 执行手势 → 检查结束画面
  routine.py    把几个流程串起来循环（loop 命令）
  flow.py       流程数据、默认等待规则、编辑
  report.py     HTML 报告
tests/          不需要手机：用合成的游戏画面（含动画和加载延迟）模拟手机
```

```bash
uv run pytest
uv run ruff check src tests
```

## 和其他项目的关系

- **hawarma**（同一款游戏的自动做饭）：`device.py` 的设备选择、屏幕方向读取和截图/触摸后端沿用它的实机方案，Airtest 分支钉在同一个 commit；两个项目要升级 Airtest 时一起升级。
- **laya-mlx**（本地 Laya 决策模型）：M0 不使用。它和 Jev 一样只接收文本状态和选择题，M1 如果用它，需要先把画面转换成文字，见 [docs/M0.md](docs/M0.md#之后m1)。
- **旧版本**：浏览器工作流研究版（SkillCUA）在提交 `1f3f76f`；改版前未提交的 iPhone 镜像 M0 尝试保存在 `git stash list` 里的 `stash@{0}`，需要时用 `git stash branch archive/iphone-m0 stash@{0}` 恢复成分支。

MIT License.
