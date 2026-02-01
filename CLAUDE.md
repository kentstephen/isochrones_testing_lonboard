# Burlington VT POI Competition Explorer
year is 2026
Click a POI → see nearby competition with Lonboard brushing + DataFusion analytics.

**Big Hairy Goal**: Click any restaurant in Burlington → walking isochrone appears → all competing POIs within isochrone highlight → brush on map filters charts, brush on charts highlights POIs on map. Full bidirectional brushing.

---

## Decision: Isochrones vs Simpler Approaches

**Do we need isochrones?** Depends on accuracy requirements.

| Approach | Complexity | Accuracy | Speed |
|----------|------------|----------|-------|
| **H3 grid_disk** | Low | Straight-line (ignores roads, rivers, barriers) | Instant |
| **ST_DWithin radius** | Low | Straight-line | Fast |
| **Pre-computed isochrones** | High upfront | True network walk distance | Slow to generate, fast to query |

**H3 limitation**: `grid_disk` is straight-line hexagon distance, NOT network movement. It won't account for rivers, highways, or street layout.

**If accuracy matters** (e.g., "which competitors can steal customers within 5 min walk"), **use isochrones**.

**Recommendation**: Pre-compute isochrones with OSMnx (one-time, slow), store in GeoParquet, query at runtime is fast.

---

## Two Paths

### Path A: Marimo + Lonboard (Python-first, simpler)

| Layer | Choice | Notes |
|-------|--------|-------|
| **Notebook** | Marimo | Reactive cells |
| **Map** | Lonboard | `selected_index` + `observe` for click callbacks |
| **Query** | DuckDB (in-process) or DataFusion | |
| **Analytics** | Marimo tables + Altair/Vega | Not as slick as Mosaic, but works |

**Lonboard click support**: Yes - `selected_index` updates on click, use `observe` pattern to trigger Python callback. `auto_highlight` for hover. Can link to `mo.ui.table`.

### Path B: Browser App (TypeScript, full Mosaic experience)

| Layer | Choice | Notes |
|-------|--------|-------|
| **Map + clicks** | deck.gl + @geoarrow/deck.gl-layers | Full control over events |
| **Query engine** | DuckDB-WASM | In-browser SQL |
| **Analytics** | Mosaic | Linked charts, histograms, data tables - instant crossfilter |
| **Data format** | GeoParquet | Loaded from hosted URL |

**Key interaction**: Click POI → query H3 neighbors → Mosaic updates charts/table instantly

---

## Architecture

### Data Prep (one-time, Python)
```
FSQ Places → Filter city/category → OSMnx isochrones → GeoParquet → Host
```

### Click Flow
```
User clicks POI
    ↓
Get fsq_id
    ↓
Query isochrone polygon from isochrones.parquet
    ↓
Display isochrone on map (PolygonLayer)
    ↓
Query: SELECT * FROM pois WHERE ST_Within(geom, isochrone)
    ↓
Update Mosaic charts/table with competitors
```

### Browser App (Path B - full Mosaic)
Based on: https://github.com/fhk/sqlroomsdemo

```
┌─────────────────────────────────────────────────────────────┐
│  BROWSER APP                                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐    ┌────────────────────────────────┐ │
│  │  deck.gl Map     │    │  Mosaic Charts + Data Table    │ │
│  │  + geoarrow      │◄──►│  (category histogram, chain    │ │
│  │  + PolygonLayer  │    │   counts, competition metrics) │ │
│  │  (isochrones)    │    │                                │ │
│  └────────┬─────────┘    └────────────────────────────────┘ │
│           │                          ▲                      │
│           │ click POI                │ crossfilter          │
│           ▼                          │                      │
│  ┌─────────────────────────────────────────────────────────┐│
│  │  DuckDB-WASM + spatial                                  ││
│  │  - Load pois.parquet + isochrones.parquet               ││
│  │  - ST_Within for competition query                      ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Pipeline

1. **Query Overture Places** for Burlington via DuckDB (direct from cloud, no download)
2. **Filter by category** (restaurants, inspect JSON for subcategories)
3. **Generate walking isochrones** for each POI using OSMnx
4. **Store in DataFusion** (following Kyle's Lonboard pattern)
5. **Save as GeoParquet**:
   - `pois.parquet` - POI points with id, name, category, lat/lng
   - `isochrones.parquet` - isochrone polygons with poi_id, minutes, geometry

### Query at runtime (DataFusion)
```sql
-- Get competitors within clicked POI's 5-min isochrone
SELECT p.* FROM pois p
JOIN isochrones i ON i.poi_id = :clicked_poi_id AND i.minutes = 5
WHERE ST_Within(p.geom, i.geom)
```

---

## Scope (Start Small)

- **City**: Burlington, Vermont (small, walkable, manageable POI count)
- **Category**: Restaurants (start here, inspect Overture JSON for subcategory specificity)
- **Isochrone**: Walking only, 5/10/15 min contours
- **Metrics**: Competition count within isochrone, chain analysis

---

## Reference Examples

| Example | What it shows |
|---------|---------------|
| https://github.com/fhk/sqlroomsdemo | **KEY REFERENCE** - deck.gl + Mosaic crossfilter + DuckDB-WASM |
| https://github.com/dzole0311/deckgl-duckdb-geoarrow | GeoArrow + linked views pattern |
| https://github.com/geoarrow/deck.gl-layers | @geoarrow/deck.gl-layers - the deck.gl layers we'll use for click events |
| https://developmentseed.org/lonboard/latest/examples/marimo/nyc_taxi_trips/ | DataFusion + Lonboard + Marimo - data pipeline reference |
| https://github.com/developmentseed/lonboard/tree/39bd3e1df609eb0470f2bdf5c07184561156aba7/examples/marimo | **BRUSHING REFERENCE** - Lonboard + Marimo brushing examples (our target UX) |

---

## Data Sources

- **Overture Places**: https://docs.overturemaps.org/getting-data/duckdb/ (GeoParquet, query directly from cloud, no auth needed)
- **Overture Categories**: JSON struct in `categories` field - inspect for specificity
- **OSM Network**: Downloaded via OSMnx for isochrone generation

---

## Libraries

### Python (data prep + isochrone generation)
```bash
pip install marimo osmnx geopandas pyarrow networkx datafusion duckdb lonboard ipykernel
```

- `osmnx`: Download street network + isochrone generation
- `geopandas` + `pyarrow`: GeoParquet output
- `datafusion`: Apache DataFusion for polygon storage + querying (following Kyle's pattern)
- `duckdb`: Query Overture Places directly from cloud storage
- `lonboard`: Map visualization with brushing support
- `ipykernel`: Dev in Jupyter/VSCode, deploy to Marimo

### Browser app (npm)
```bash
npm install deck.gl @geoarrow/deck.gl-layers @duckdb/duckdb-wasm @uwdata/mosaic-core @uwdata/mosaic-sql
```

- `@geoarrow/deck.gl-layers`: Click events + efficient Arrow rendering
- `@duckdb/duckdb-wasm`: In-browser SQL with spatial extension
- `@uwdata/mosaic-*`: Linked charts, tables, crossfilter

---

## Scale Target

- NYC taxi example handles **100k rows** in ArcLayer - our POI + isochrone setup should match this
- GeoArrow + DuckDB-WASM: millions of rows feasible in browser

## Sharing Strategy

- Pre-compute isochrones offline (slow, but one-time per city/category)
- Host GeoParquet (pois + isochrones) on source.coop or GitHub releases
- Browser app loads from URL → instant for users
- Users never wait for isochrone generation - it's all pre-computed

## Open Questions

1. Which city to start with?
2. Which POI category to focus on?
3. Do we want chain-specific views (Starbucks vs competitors)?

---

## Session Notes

*Use this section to track progress across sessions.*

- **2026-01-31**: Initial stack discussion. Valhalla rejected (server dependency). Will pre-compute isochrones with OSMnx.
- **2026-01-31**: Clarified architecture - need browser app (not just Marimo) for full Mosaic crossfilter experience. Stack: deck.gl + @geoarrow/deck.gl-layers + DuckDB-WASM + Mosaic.
- **2026-01-31**: Explored H3 grid_disk as simpler alternative. Rejected - straight-line distance doesn't reflect network movement (rivers, highways, etc.). Sticking with pre-computed isochrones for accuracy.
- **2026-01-31**: Lonboard DOES support click events (`selected_index` + `observe`), so Path A (Marimo) is viable for prototyping, but Path B (browser) needed for full Mosaic experience.
- **2026-01-31**: **DECISIONS LOCKED** - City: Burlington VT. Data: Overture Places (not FSQ, no auth needed). Isochrones: OSMnx (not Pandana, cleaner deps). Storage: Apache DataFusion (Kyle's pattern). Dev: Jupyter/ipykernel → deploy to Marimo. Category: Restaurants (inspect JSON for specificity).
- **2026-01-31**: Notebook progress - isochrone generation working for 108 Burlington restaurants (5/10/15 min). Fixed GeoPandas deprecation: use `union_all()` instead of `unary_union`. Lonboard works better in Jupyter Lab than VSCode notebooks.