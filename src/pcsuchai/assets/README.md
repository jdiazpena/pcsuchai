# Bundled map data

`natural_earth_110m_land.npz` and
`natural_earth_110m_country_borders.npz` are runtime-light extractions of the
Natural Earth 1:110m land polygons and land boundary lines. Natural Earth data
is public domain. Sources:
<https://www.naturalearthdata.com/downloads/110m-physical-vectors/110m-land/>.
<https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-boundary-lines/>.

The extraction stores only longitude/latitude polygon vertices and part
indices. It lets Matplotlib render continent context without Cartopy,
GeoPandas, Shapely, or network access on the Raspberry Pi.
