# Skill session: the agent finds the forecast itself

A fresh Claude Code session (`claude -p`, captured 2026-10-19) with the `buildwindow` skill
installed and the server added with the skill's own one-line command
(`claude mcp add buildwindow -- uvx --from git+https://github.com/borovkov-d/buildwindow-mcp@v0.2.2 buildwindow-server`,
built-in example dataset). The prompt names neither the skill nor any weather figures;
web search/fetch were permitted. The prompt is in Ukrainian ("can we paint the facade in Kyiv tomorrow").

## Prompt

> чи можна завтра фарбувати фасад у Києві

## Tool calls, in order

1. `Skill` `{"skill": "buildwindow"}`
2. `WebFetch` `{"url": "https://api.open-meteo.com/v1/forecast?latitude=50.45&longitude=30.52&daily=temperature_2m_min,temperature_2m_max,wind_speed_10m_max,relative_humidity_2m_mean,precipitation_sum&wind_speed_unit=ms&timezone=Europe%2FKyiv&start_date=2026-10-20&end_date=2026-10-20"}`
3. `mcp__buildwindow__lookup_work_requirements` `{"request": {"work_code": "exterior_painting"}}`
4. `mcp__buildwindow__validate_work_window` `{"request": {"work_code": "exterior_painting", "window": {"date": "2026-10-20", "temp_min_c": 10.4, "temp_max_c": 16.7, "wind_ms": 3.52, "humidity_pct": 86, "precipitation_mm": 0.9}}}`

## Final answer (verbatim)

**Завтра (20.10.2026) фарбувати фасад у Києві не можна. Вердикт: `prohibited`.**

Я вважав, що йдеться про зовнішнє фарбування (`exterior_painting`). Якщо у вас штукатурка фасаду, скажіть, і я перевірю `facade_plastering`.

| Показник | Прогноз | Ліміт | Результат |
|---|---|---|---|
| Вологість | 86 % | не більше 80 % | перевищено на 6 % |
| Опади | 0,9 мм | не допускаються | перевищено на 0,9 мм |
| Температура | 10,4…16,7 °C | 10…30 °C | у нормі |
| Вітер | 3,52 м/с | не більше 8 м/с | у нормі |

- **Прогноз:** Open-Meteo, Київ (50,45; 30,52), денні значення на 2026-10-20. Усі поля з одного джерела, нічого не конвертував і не домислював.
- **Ліміти:** це вбудований приклад BuildWindow, а не норма, паспорт фарби чи регламент. Для вашої фарби перевірте дані виробника на банці. Якщо дасте свої ліміти, я перерахую.

Хочете, перевірю наступні дні й підберу найближче вікно?

