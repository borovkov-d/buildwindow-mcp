# BuildWindow dataset format

The BuildWindow MCP server reads its work-type limits from one JSON file:
the file named by the `BUILDWINDOW_DATASET` environment variable, or the
built-in construction example when that variable is unset or empty. The
file is validated at startup. Any error stops the server with a list of
every problem found. Each problem names the record (by index and code), the
field, and what is allowed.

## File shape

```json
{
  "schema_version": "1.0",
  "work_types": [ { ...record... }, { ...record... } ]
}
```

No other top-level fields are allowed. `work_types` must contain at least
one record, and codes must be unique.

## Record fields (all required, no extra fields)

| Field | Type | Allowed values | Meaning |
|---|---|---|---|
| `code` | string | lowercase snake_case: `^[a-z][a-z0-9_]*$` | Unique identifier, used as `work_code` in every tool |
| `name` | string | any | Human-readable name |
| `category` | string | lowercase snake_case | Grouping used by `lookup_work_requirements(category=…)` |
| `temp_min_c` | number | −30 … 50, less than `temp_max_c` | Lowest air temperature (°C) at which the work may proceed |
| `temp_max_c` | number | −30 … 50 | Highest air temperature (°C) at which the work may proceed |
| `wind_max_ms` | number | 0 … 40 | Highest wind speed (m/s) at which the work may proceed |
| `humidity_max_pct` | integer | 0 … 100 | Highest relative humidity (%) at which the work may proceed |
| `precipitation_allowed` | boolean | `true` / `false` | `false`: any precipitation > 0 mm is a hard violation |
| `base_curing_hours` | integer or `null` | > 0, or `null` | Nominal curing time at 20 °C, used by `estimate_curing_time`. `null` means no curing stage. The field must be present even when `null`. |
| `reference_note` | string | any | Where these limits come from (standard, data sheet, manual). Shown to the user, so cite your source here. |

## Example record (drone operations domain)

```json
{
  "code": "crop_spraying",
  "name": "Crop spraying by drone",
  "category": "agriculture",
  "temp_min_c": 5,
  "temp_max_c": 28,
  "wind_max_ms": 4,
  "humidity_max_pct": 95,
  "precipitation_allowed": false,
  "base_curing_hours": null,
  "reference_note": "Product label section 4 and the operator's spray-drift procedure."
}
```

A full five-mission example dataset ships in the repository as
`examples/drone_operations.json`.

## How limits are applied

For each forecast day, all five checks run:

- minimum temperature, against `temp_min_c`
- maximum temperature, against `temp_max_c`
- wind, against `wind_max_ms`
- humidity, against `humidity_max_pct`
- precipitation, against `precipitation_allowed`

A breach within the tolerance band is a **warning**, and the verdict is
`conditional`. The bands are 2 °C for temperature, 1 m/s for wind and 5 %
for humidity. A breach beyond the band is a **violation**, and the verdict
is `prohibited`. Precipitation has no band. The bands are fixed in the
engine and are not set per dataset.
