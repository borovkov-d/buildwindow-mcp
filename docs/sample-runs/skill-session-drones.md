# Skill session: drone jobs planned with the user's own dataset

A fresh Claude Code session (`claude -p`, captured 2026-10-18) with the `buildwindow` skill
installed in `~/.claude/skills/` and the server registered via the skill's own
`claude mcp add` command, `BUILDWINDOW_DATASET` pointing at a copy of
`examples/drone_operations.json` named `your_limits.json`. The prompt does not name the
skill; it was picked up from its description. The user prompt is in Ukrainian.

## Prompt

> Треба цього тижня зробити лідарну зйомку ділянки (1 день), а після неї аерофотозйомку (2 дні), і ще обприскати поле дроном (1 день). Коли це можна зробити? Прогноз: пн 2026-08-24: 3..9 °C, вітер 3 м/с, вологість 80%, сухо; вт 2026-08-25: 6..12 °C, вітер 9 м/с, вологість 70%, сухо; ср 2026-08-26: 8..15 °C, вітер 3 м/с, вологість 75%, дощ 2 мм; чт 2026-08-27: 9..16 °C, вітер 2 м/с, вологість 70%, сухо; пт 2026-08-28: 10..17 °C, вітер 3 м/с, вологість 65%, сухо.

## Tool calls, in order

1. `Skill` `{"skill": "buildwindow"}`
2. `mcp__buildwindow__lookup_work_requirements` `{"request": {"work_code": "lidar_survey"}}`
3. `mcp__buildwindow__lookup_work_requirements` `{"request": {"work_code": "aerial_photography"}}`
4. `mcp__buildwindow__lookup_work_requirements` `{"request": {"work_code": "crop_spraying"}}`
5. `mcp__buildwindow__plan_work_schedule` `{"request": {"works": [{"work_code": "lidar_survey", "duration_days": 1}, {"work_code": "aerial_photography", "duration_days": 2, "depends_on": ["lidar_survey"]}, {"work_code": "crop_spraying", "duration_days": 1}], "forecast": [{"date": "2026-08-24", "temp_min_c": 3, "temp_max_c": 9, "wind_ms": 3, "humidity_pct": 80, "precipitation_mm": 0}, {"date": "2026-08-25", "temp_min_c": 6, "temp_max_c": 12, "wind_ms": 9, "humidity_pct": 70, "precipitation_mm": 0}, {"date": "2026-08-26", "temp_min_c": 8, "temp_max_c": 15, "wind_ms": 3, "humidity_pct": 75, "precipitation_mm": 2}, {"date": "2026-08-27", "temp_min_c": 9, "temp_max_c": 16, "wind_ms": 2, "humidity_pct": 70, "precipitation_mm": 0}, {"date": "2026-08-28", "temp_min_c": 10, "temp_max_c": 17, "wind_ms": 3, "humidity_pct": 65, "precipitation_mm": 0}]}}`
6. `mcp__buildwindow__validate_work_window` `{"request": {"work_code": "crop_spraying", "window": {"date": "2026-08-24", "temp_min_c": 3, "temp_max_c": 9, "wind_ms": 3, "humidity_pct": 80, "precipitation_mm": 0}}}`
7. `mcp__buildwindow__validate_work_window` `{"request": {"work_code": "crop_spraying", "window": {"date": "2026-08-27", "temp_min_c": 9, "temp_max_c": 16, "wind_ms": 2, "humidity_pct": 70, "precipitation_mm": 0}}}`
8. `mcp__buildwindow__validate_work_window` `{"request": {"work_code": "crop_spraying", "window": {"date": "2026-08-28", "temp_min_c": 10, "temp_max_c": 17, "wind_ms": 3, "humidity_pct": 65, "precipitation_mm": 0}}}`
9. `mcp__buildwindow__validate_work_window` `{"request": {"work_code": "aerial_photography", "window": {"date": "2026-08-26", "temp_min_c": 8, "temp_max_c": 15, "wind_ms": 3, "humidity_pct": 75, "precipitation_mm": 2}}}`

## Final answer (verbatim)

**План (за вашими лімітами з файлу `your_limits.json`, це не вбудований приклад):**

| Робота | Дата | Вердикт |
|---|---|---|
| Лідарна зйомка (1 день) | **пн 24.08** | дозволено |
| Аерофотозйомка (2 дні) | **чт 27.08 – пт 28.08** | дозволено |
| Обприскування дроном (1 день) | **пн 24.08** | умовно, з ризиком |

**Про обприскування в понеділок.** Мінімальна температура прогнозується 3 °C, а ліміт для `crop_spraying` дорівнює 5 °C, тобто на 2 °C нижче. Інші ліміти не порушено. Для обприскування це «можливо, але з ризиком».

**Безпечніша альтернатива.** Обприскування в четвер 27.08 або п'ятницю 28.08 дозволене без застережень. Я перевірив обидва дні окремо. Проблема в тому, що ці дні вже зайняті аерофотозйомкою. Якщо ви можете робити дві роботи в один день (інший дрон чи екіпаж), поставте обприскування на чт або пт. Планувальник такого обмеження не враховує, тому поставив обприскування на понеділок.

**Чому аерофотозйомка не раніше.** Вона залежить від лідарної зйомки, яка в понеділок. У середу 26.08 вона заборонена: опади 2 мм, а опади для неї недопустимі (перевірено окремо). Тому дві поспіль доступні дні — чт і пт.

**Припущення й застереження:**
- Усі значення взяті з вашого прогнозу, нічого не домислювалося.
- Інструмент враховує лише добову мін./макс. температуру, вітер, вологість і опади. Пориви вітру, години доби та стан ґрунту він не оцінює.
- Вторник (вітер 9 м/с) окремо не перевіряв: за лімітами він не потрібен, бо лідар обмежений вітром 8 м/с.

