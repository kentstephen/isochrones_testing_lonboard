import marimo

__generated_with = "0.19.7"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _():
    import duckdb
    import geopandas as gpd
    import osmnx as ox
    import networkx as nx
    from shapely.geometry import Point, MultiPoint
    from shapely import concave_hull
    return MultiPoint, Point, concave_hull, duckdb, gpd, nx, ox


@app.cell
def _(mo):
    mo.md("""
    # Isochrone Visualization

    Proper walking isochrones using concave hull - beautiful geometries showing reachable area.
    """)
    return


@app.cell
def _(duckdb):
    # Initialize DuckDB
    con = duckdb.connect()
    con.sql("""
        INSTALL spatial; LOAD spatial;
        INSTALL httpfs; LOAD httpfs;
        SET s3_region='us-west-2';
    """)
    return (con,)


@app.cell
def _(con):
    # Get Burlington VT boundary
    bbox, wkt_geom = con.sql("""
    SELECT
        bbox,
        ST_AsText(geometry) AS wkt
    FROM read_parquet('s3://overturemaps-us-west-2/release/2026-01-21.0/theme=divisions/type=division_area/*.parquet')
    WHERE
        country = 'US'
        AND region = 'US-VT'
        AND names.primary = 'Burlington'
        AND subtype = 'locality'
    """).fetchall()[0]
    return bbox, wkt_geom


@app.cell
def _(bbox, con, gpd, wkt_geom):
    # Get a few sample restaurants
    restaurants_df = con.sql(f"""
    SELECT
        id,
        names.primary as name,
        categories.primary as primary_category,
        ST_X(geometry) as lon,
        ST_Y(geometry) as lat
    FROM read_parquet('s3://overturemaps-us-west-2/release/2026-01-21.0/theme=places/type=place/*.parquet')
    WHERE
        bbox.xmin <= {bbox['xmax']}
        AND bbox.xmax >= {bbox['xmin']}
        AND bbox.ymin <= {bbox['ymax']}
        AND bbox.ymax >= {bbox['ymin']}
        AND ST_Intersects(geometry, ST_GeomFromText('{wkt_geom}'))
        AND lower(categories.primary) LIKE '%restaurant%'
    LIMIT 10
    """).df()

    restaurants_gdf = gpd.GeoDataFrame(
        restaurants_df,
        geometry=gpd.points_from_xy(restaurants_df['lon'], restaurants_df['lat']),
        crs="EPSG:4326"
    )
    return (restaurants_gdf,)


@app.cell
def _(bbox, ox):
    # Download street network
    buffer = 0.02
    osm_bbox = (
        bbox['xmin'] - buffer,
        bbox['ymin'] - buffer,
        bbox['xmax'] + buffer,
        bbox['ymax'] + buffer
    )
    G = ox.graph_from_bbox(osm_bbox, network_type='walk')
    G_proj = ox.project_graph(G)

    # Add travel times (75 m/min = 4.5 km/h walking)
    for u, v, data in G_proj.edges(data=True):
        data['travel_time'] = data.get('length', 0) / 75.0

    crs_proj = G_proj.graph['crs']
    return G_proj, crs_proj


@app.cell
def _(MultiPoint, Point, concave_hull, gpd, nx, ox):
    def generate_isochrone(G, center_point, trip_time_minutes, crs_proj, ratio=0.3):
        """
        Generate isochrone polygon using concave hull.

        Args:
            G: Projected NetworkX graph with travel_time edge attribute
            center_point: (lon, lat) tuple in WGS84
            trip_time_minutes: Maximum travel time in minutes
            crs_proj: CRS of the projected graph
            ratio: Concave hull ratio (0=convex, 1=tightest fit)

        Returns:
            Shapely Polygon in WGS84
        """
        # Project center point
        center_gdf = gpd.GeoDataFrame(
            geometry=[Point(center_point)],
            crs="EPSG:4326"
        ).to_crs(crs_proj)
        center_proj = (center_gdf.geometry.iloc[0].x, center_gdf.geometry.iloc[0].y)

        # Find nearest node and get reachable subgraph
        nearest_node = ox.nearest_nodes(G, center_proj[0], center_proj[1])
        subgraph = nx.ego_graph(G, nearest_node, radius=trip_time_minutes, distance='travel_time')

        if len(subgraph.nodes()) < 3:
            return center_gdf.buffer(100).to_crs("EPSG:4326").geometry.iloc[0]

        # Get all reachable node coordinates
        node_coords = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in subgraph.nodes()]
        points = MultiPoint(node_coords)

        # Create concave hull - this gives us a proper filled polygon
        iso_polygon = concave_hull(points, ratio=ratio)

        # Convert back to WGS84
        iso_gdf = gpd.GeoDataFrame(geometry=[iso_polygon], crs=crs_proj)
        return iso_gdf.to_crs("EPSG:4326").geometry.iloc[0]
    return (generate_isochrone,)


@app.cell
def _(G_proj, crs_proj, generate_isochrone, gpd, restaurants_gdf):
    # Generate isochrones for sample POIs at different time intervals
    TRIP_TIMES = [5, 10, 15]

    isochrone_records = []
    for idx, poi in restaurants_gdf.head(5).iterrows():  # Just 5 POIs for now
        for minutes in TRIP_TIMES:
            iso = generate_isochrone(G_proj, (poi['lon'], poi['lat']), minutes, crs_proj)
            isochrone_records.append({
                'poi_id': poi['id'],
                'poi_name': poi['name'],
                'minutes': minutes,
                'geometry': iso
            })

    isochrones_gdf = gpd.GeoDataFrame(isochrone_records, crs="EPSG:4326")
    isochrones_gdf
    return (isochrones_gdf,)


@app.cell
def _(mo):
    mo.md("""
    ## Isochrone Map
    """)
    return


@app.cell
def _(isochrones_gdf):
    import numpy as np
    from lonboard import Map, SolidPolygonLayer

    # Color by time: 5min=green, 10min=yellow, 15min=red
    def get_color(minutes):
        if minutes == 5:
            return [0, 200, 100, 120]
        elif minutes == 10:
            return [255, 200, 0, 100]
        else:
            return [255, 80, 80, 80]

    colors = np.array([get_color(m) for m in isochrones_gdf['minutes']], dtype=np.uint8)

    layer = SolidPolygonLayer.from_geopandas(
        isochrones_gdf,
        get_fill_color=colors,
        pickable=True,
        auto_highlight=True,
    )

    m = Map(layers=[layer])
    m
    return


if __name__ == "__main__":
    app.run()
