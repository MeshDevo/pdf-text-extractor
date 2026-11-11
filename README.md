# 本地 PDF 流水线 — PDF 转 TXT

完全本地的流水线：将 PDF 文件放入 `input/`，运行后即可在 `output/` 中得到 TXT 文件。无需服务器、无需联网、无需上传。单文件快速版本（网页版和早期的 `pdf2txt.py` 脚本）仍可用于单次使用；本流水线适用于批量和重复性工作。

## 运行（两步）

```bash
# 1) 将 PDF 文件放入 input/
# 2) 运行：
./run.sh
```

首次运行时，`run.sh` 会创建虚拟环境 `.venv` 并安装唯一依赖（PyMuPDF）。之后的运行即刻完成。

## 五个阶段（按顺序）

| # | 阶段 | 作用 |
|---|---|---|
| 1 | `intake` | 发现 PDF 文件：单个文件或整个文件夹（递归），按字母顺序 |
| 2 | `extract` | 使用 PyMuPDF 提取文本，分离双栏（先完整读取左栏，再读取右栏） |
| 3 | `clean` | 仅做保守清理：连接被连字符断开的单词、去除行尾空格、合并连续空行 |
| 4 | `write` | 以 UTF-8 写入 TXT，并保留相对目录结构 |
| 5 | `report` | 写入 `output/manifest.json`，更新 `pipeline-state.json`，并打印摘要 |

## 断点续跑

流水线将每个文件的 `sha256` 哈希保存在 `pipeline-state.json`（项目根目录）中。下次运行时，会跳过所有未更改的文件（`[SKIP]`），仅处理新增或更改的文件。`--force` 会重新处理全部文件。

## 命令

```bash
./run.sh                      # 运行一批
./run.sh --watch 10           # 监视模式：每 10 秒检查一次 input/，按 Ctrl+C 停止
./run.sh paper.pdf            # 单个文件 → output/paper.txt
./run.sh --input docs --output out   # 自定义目录
./run.sh --page-markers       # 在页面之间插入 "--- Page N ---" 行
./run.sh --force              # 重新处理全部文件
./run.sh --self-test          # 自测（生成 3 个文件，验证后清理）
```

## 输出

- `output/<name>.txt` — 每篇论文的全文，并保留输入目录结构。
- `output/manifest.json` — 最近一次运行的记录：来源、哈希、页数、字符数、词数、状态（`done` / `skipped` / `empty` / `failed`）及警告。
- `pipeline-state.json` — 用于断点续跑的持久状态文件。

## 依赖

| 库 | 作用 | 安装 |
|---|---|---|
| **PyMuPDF**（唯一必需） | 文本提取与分栏 | `pip install -r requirements.txt`（`run.sh` 自动完成） |
| pypdf（仅备用） | 若未安装 PyMuPDF 则自动使用 | 通常不需要 |

## 已知限制

- 无文本层的扫描版 PDF 会生成空 TXT 文件，状态为 `empty`，并在清单中给出警告；需先进行 OCR，这超出了本轻量流水线的范围。
- 不提取图片，不将表格转换为表格，不格式化参考文献——仅输出纯文本。
- 分栏顺序基于几何启发式方法，适用于常见的双栏版式；罕见版式可能顺序不同。
- 中文（CJK）文本：完整提取，同一栏内被折行的文字会重新连接。若文件内嵌字体为日文字体，个别字符可能显示为兼容字形（如 行 而非 行）——这源于字体本身，而非提取错误。
