---
name: flashcard
description: 单词闪卡：随机测验、浏览词库、按难度复习英语单词
keywords: 单词,闪卡,背单词,测验,英语,词汇,复习,默写,quiz,flashcard,vocabulary,word,记单词,学英语
required_tools: flashcard
---

# 单词闪卡技能 · 工作流

## 调用
用户表达背单词/测验/浏览/复习/查详情意图时，提取参数调用 flashcard 工具：

| 意图 | 参数 | 调用 |
|------|------|------|
| quiz | count（默认5） | `{"action":"quiz","count":5}` |
| list | 无 | `{"action":"list"}` |
| review | difficulty（可选）、count（默认5） | `{"action":"review","difficulty":"hard","count":5}` |
| detail | word | `{"action":"detail","word":"serendipity"}` |

## 展示与兜底
- 仅用工具数据，禁止编造；不透露调用细节；中文、友好、措辞多变。
- 展示：英文、音标、中文释义、例句及翻译；测验先显英文+音标，再显答案；detail 含难度和标签；用分隔线或空行区分单词；测验后询问答对数量。

| 场景 | 处理 |
|------|------|
| 意图不明 | 询问并列出支持操作 |
| 工具失败 | 解释并建议重试 |
| 单词不在词库 | 如实告知并建议查看词库 |