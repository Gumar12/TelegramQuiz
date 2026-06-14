# -*- coding: utf-8 -*-
"""Конвертирует quiz JSON в читаемый Markdown для ревью."""
import json, sys, os

src = sys.argv[1]
dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".md"

d = json.load(open(src, encoding="utf-8"))
qs = d.get("questions", [])


def is_corrupt(s: str) -> bool:
    s = (s or "").strip()
    if s == "" or s.lower() == "контекст":
        return True
    has_cyrillic = any("а" <= c.lower() <= "я" or c.lower() == "ё" for c in s)
    return "?" in s and not has_cyrillic


# заголовок берём из имени файла, если поле в JSON испорчено
title = d.get("quiz_title", "")
if is_corrupt(title):
    title = os.path.splitext(os.path.basename(src))[0]

out = []
out.append(f"# {title}")
out.append("")
out.append(f"Всего вопросов: **{len(qs)}**")
out.append("")
out.append("> Правильный ответ помечен ✅")
out.append("")
out.append("---")
out.append("")

for i, q in enumerate(qs, start=1):
    out.append(f"### {i}. {q.get('question', '').strip()}")
    out.append("")

    correct = q.get("correct")  # 1-индекс
    for j, opt in enumerate(q.get("options", []), start=1):
        mark = " ✅" if j == correct else ""
        out.append(f"{j}. {opt}{mark}")
    out.append("")

    ctx = (q.get("context") or "").strip()
    if ctx:
        ctitle = q.get("context_title", "")
        head = "" if is_corrupt(ctitle) else f"**{ctitle.strip()}** — "
        # контекст в блок-цитату
        out.append(f"> 📖 {head}{ctx}")
        out.append("")

    media = q.get("media") or []
    if media:
        out.append("🖼 Медиа: " + ", ".join(f"`{m}`" for m in media))
        out.append("")

    expl = (q.get("explanation") or "").strip()
    if expl:
        out.append(f"💡 Пояснение: {expl}")
        out.append("")

    out.append("---")
    out.append("")

open(dst, "w", encoding="utf-8").write("\n".join(out))
print("OK ->", dst)
print("questions:", len(qs))
