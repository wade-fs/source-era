# Manifest — 源質紀元

## Metadata

- title: 源質紀元
- author: Wade
- cache_display_name: 源質紀元聖經
- style: 第三人稱有限視角、緊貼林墨主觀感知；節奏偏沉穩觀察，重視合成細節與源質推理邏輯

---

## Priority Order

### Priority 0 — Canon（最高權威，不可違反）
- docs/canon/novel_bible.md
- docs/canon/world.md
- docs/canon/characters.md
- docs/canon/source_periodic_table.md
- docs/canon/synthesis_rules.md
- docs/canon/materials.md
- docs/canon/timeline.md

### Priority 1 — Rules（AI 寫作規範）
- docs/rules/writing_style.md
- docs/rules/continuity.md
- docs/rules/chapter_template.md

### Priority 2 — Volume Plan（當前卷設定）
- docs/volumes/vol{XX}/volume_plan.md

### Priority 3 — Chapter Outline（當前卷章綱）
- docs/volumes/vol{XX}/chapter_outline.md

### Priority 4 — Previous Chapter（連貫性參考）
- chapter/{XX}/ch{NNNN}.md（前 1～3 章）

### Priority 5 — Lore（深度設定，按需載入）
- docs/lore/*.md

---

## Conflict Resolution

```
Canon > Rules > Volume > Outline > Chapter
```

衝突時以優先級高者為準。任何生成內容不得與 Canon 矛盾。

---

## Writing Workflow

1. **Load Canon** — 載入 docs/canon/* 建立世界觀基礎
2. **Load Rules** — 載入 docs/rules/* 確認寫作規範
3. **Load Volume** — 載入當前卷的 volume_plan.md
4. **Load Outline** — 載入當前卷的 chapter_outline.md
5. **Load Previous Chapters** — 載入前 1～3 章維持連貫
6. **Generate Chapter** — 依 chapter_template.md 結構生成

---

## Cache Strategy

快取（高頻不變）：
- docs/canon/*
- docs/rules/*

按需載入（每章不同）：
- docs/volumes/vol{XX}/*
- chapter/{XX}/ch{NNNN}.md
