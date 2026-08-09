# `data/geography/`

Country-level reference data for maps and emissions.


| File                                | Description                                                                                                             |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `country_boundaries.geojson`        | Country polygons (choropleth) to change the colour of the world from red to green as people pledge carbon contributions |
| `country_boundaries_centroids.json` | Label/centroid points for delegate countries                                                                            |
| `country_neighbors.json`            | Adjacency for grouping pledges such that no individual can be identified                                                |
| `country_continents.json`           | Continent membership (`country_continents.py`)                                                                           |
| `national_per_capita_co2.json`      | Per-capita emissions reference to contextualise my personal emissions                                                   |


Used by `src/geography/` and the emissions UI.