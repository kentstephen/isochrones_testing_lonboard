import marimo

__generated_with = "0.10.19"
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
    from shapely.geometry import Point, LineString
    import pandas as pd
    import numpy as np
    return LineString, Point, duckdb, gpd, np, ox, nx, pd


@app.cell
def _(mo):
    mo.md(
        """
        # Burlington POI Competition Explorer

        Click a restaurant → see its walking isochrone → find competitors within reach.
        """
    )
    return


@app.cell
def _(duckdb):
    # Initialize DuckDB with extensions
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
    # Query restaurants from Overture
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
        AND (
            lower(categories.primary) LIKE '%restaurant%'
            OR lower(categories.primary) LIKE '%food%'
            OR lower(categories.primary) LIKE '%cafe%'
            OR lower(categories.primary) LIKE '%coffee%'
        )
    """).df()

    restaurants_gdf = gpd.GeoDataFrame(
        restaurants_df,
        geometry=gpd.points_from_xy(restaurants_df['lon'], restaurants_df['lat']),
        crs="EPSG:4326"
    )
    return restaurants_df, restaurants_gdf


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

    # Add travel times (75 m/min walking speed)
    for u, v, data in G_proj.edges(data=True):
        data['travel_time'] = data.get('length', 0) / 75.0

    crs_proj = G_proj.graph['crs']
    return G, G_proj, crs_proj, osm_bbox


@app.cell
def _(LineString, Point, gpd, nx, ox):
    def generate_isochrone(G, center_point, trip_time_minutes, crs_proj, buffer_m=15):
        """Generate isochrone using edge buffering."""
        center_gdf = gpd.GeoDataFrame(
            geometry=[Point(center_point)],
            crs="EPSG:4326"
        ).to_crs(crs_proj)
        center_proj = (center_gdf.geometry.iloc[0].x, center_gdf.geometry.iloc[0].y)

        nearest_node = ox.nearest_nodes(G, center_proj[0], center_proj[1])
        subgraph = nx.ego_graph(G, nearest_node, radius=trip_time_minutes, distance='travel_time')

        if len(subgraph.nodes()) < 2:
            return center_gdf.buffer(50).to_crs("EPSG:4326").geometry.iloc[0]

        edge_lines = []
        for u, v in subgraph.edges():
            u_coords = (G.nodes[u]['x'], G.nodes[u]['y'])
            v_coords = (G.nodes[v]['x'], G.nodes[v]['y'])
            edge_lines.append(LineString([u_coords, v_coords]))

        if not edge_lines:
            return center_gdf.buffer(50).to_crs("EPSG:4326").geometry.iloc[0]

        edges_gdf = gpd.GeoDataFrame(geometry=edge_lines, crs=crs_proj)
        buffered = edges_gdf.buffer(buffer_m)
        isochrone = buffered.union_all()

        isochrone_gdf = gpd.GeoDataFrame(geometry=[isochrone], crs=crs_proj)
        return isochrone_gdf.to_crs("EPSG:4326").geometry.iloc[0]
    return (generate_isochrone,)


@app.cell
def _(G_proj, crs_proj, generate_isochrone, gpd, mo, restaurants_gdf):
    # Generate isochrones for all POIs (5 min only for speed)
    mo.status.spinner("Generating isochrones...")

    isochrone_records = []
    for idx, poi in restaurants_gdf.iterrows():
        iso = generate_isochrone(G_proj, (poi['lon'], poi['lat']), 5, crs_proj)
        isochrone_records.append({
            'poi_id': poi['id'],
            'poi_name': poi['name'],
            'primary_category': poi['primary_category'],
            'geometry': iso
        })

    isochrones_gdf = gpd.GeoDataFrame(isochrone_records, crs="EPSG:4326")
    return isochrone_records, isochrones_gdf


@app.cell
def _(mo):
    mo.md("## Map with Brushing")
    return


@app.cell
def _(isochrones_gdf, restaurants_gdf):
    import lonboard
    from lonboard import Map, SolidPolygonLayer, ScatterplotLayer
    from lonboard.basemap import CartoStyle
    from lonboard.colormap import apply_categorical_cmap

    # Create layers
    polygon_layer = SolidPolygonLayer.from_geopandas(
        isochrones_gdf,
        get_fill_color=[0, 100, 200, 80],
        get_line_color=[0, 100, 200, 200],
        pickable=True,
        auto_highlight=True,
    )

    point_layer = ScatterplotLayer.from_geopandas(
        restaurants_gdf,
        get_fill_color=[255, 0, 0, 200],
        get_radius=50,
        pickable=True,
        auto_highlight=True,
    )

    m = Map(
        layers=[polygon_layer, point_layer],
        basemap=CartoStyle.Positron,
    )
    m
    return Map, ScatterplotLayer, SolidPolygonLayer, apply_categorical_cmap, lonboard, m, point_layer, polygon_layer


@app.cell
def _(isochrones_gdf, mo, polygon_layer):
    # Show selected isochrone info
    selected_idx = polygon_layer.selected_index
    if selected_idx is not None and selected_idx >= 0:
        selected = isochrones_gdf.iloc[selected_idx]
        mo.md(f"**Selected:** {selected['poi_name']} ({selected['primary_category']})")
    else:
        mo.md("*Click an isochrone to see details*")
    return (selected_idx,)


@app.cell
def _(isochrones_gdf, mo):
    # Data table with brushing
    mo.ui.table(
        isochrones_gdf[['poi_name', 'primary_category']],
        selection="single",
        label="Restaurants"
    )
    return


if __name__ == "__main__":
    app.run()
