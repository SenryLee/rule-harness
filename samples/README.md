# Samples

本目录用来放跑端到端的样本素材。

| 文件 | 类型 | 推荐 source_tag | 备注 |
|---|---|---|---|
| `案例.txt` | 案例反推 | `案例` | 触发 P5 管道 |
| `generate_samples.py` | 工具脚本 | — | 调用方式：`python3 samples/generate_samples.py`，输出几份 DOCX/PDF/Excel 样本 |

跑通：

```bash
# 1. 生成样本（如有）
python3 samples/generate_samples.py

# 2. 启动后端 + 前端
./start.sh

# 3. 在浏览器打开 http://localhost:5199 上传 samples/ 下的文件
```

如果你只想跑后端的单测（不需要 LLM）：

```bash
pytest -q backend/tests
```
