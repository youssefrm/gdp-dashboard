# map_generator.py

import os
import json
import requests
import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
import folium
from folium.plugins import MiniMap, MeasureControl, MousePosition, FloatImage
import logging
import glob

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

###################################
# Utility Functions
###################################
def parse_matrice(matrice_str):
    """Parse the 'matrice' column (JSON)."""
    if pd.isna(matrice_str):
        return []
    try:
        data = json.loads(matrice_str)
        if isinstance(data, dict):
            return [data]
        elif isinstance(data, list):
            return data
        else:
            logging.error(f"Unexpected format in matrice: {matrice_str}")
            return []
    except Exception as e:
        logging.error(f"Error in parse_matrice: {e}")
        return []

def extract_min_consumption(matrice_str):
    """Return the lowest consumption found in 'matrice'."""
    mat = parse_matrice(matrice_str)
    conso_list = [float(entry.get("CONSO", 0)) for entry in mat]
    return min(conso_list) if conso_list else np.inf

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate the great-circle distance between two points on the Earth."""
    R = 6371.0  # Earth radius in kilometers
    dLat = np.radians(lat2 - lat1)
    dLon = np.radians(lon2 - lon1)
    a = (np.sin(dLat/2)**2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dLon/2)**2)
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def code_jurid_to_str(val, code_to_description):
    """Convert juridical form code to description using categories-juridiques-insee.csv."""
    if pd.isna(val):
        return ''
    try:
        code_j = str(int(float(val))).strip()
        return code_to_description.get(code_j, "Unknown")
    except:
        return "Unknown"

def reverse_geocode_citycode(lat, lon, geo_communes_url="https://geo.api.gouv.fr/communes"):
    """
    Returns the INSEE code of the commune containing the point (lat, lon).
    """
    params = {"lat": lat, "lon": lon}
    response_geo = requests.get(geo_communes_url, params=params)

    if response_geo.status_code == 200:
        communes_data = response_geo.json()
        if communes_data:
            commune_info = communes_data[0]
            code_insee = commune_info.get('code', 'Not available')
            return code_insee
    return ""

def load_naf_dict(file_path):
    """Load a dictionary Code -> Label from an Excel NAF file (n2 or n5)."""
    naf_dict = {}
    try:
        df = pd.read_excel(file_path)
        for _, row in df.iterrows():
            code = str(row['Code']).strip()
            label = str(row['Libellé']).strip()
            naf_dict[code] = label
        logging.info(f"NAF loaded: {len(naf_dict)} entries from {file_path}.")
    except Exception as e:
        logging.error(f"Error loading NAF from {file_path}: {e}")
    return naf_dict

def get_perimetre_from_dens(dens_value):
    """
    Determine perimeter based on density:
    - Rural communes: dens > 4 => 20 km
    - Peri-urban communes: dens = 3 or 4 => 10 km
    - Urban communes (1 or 2) => 0 km
    """
    if dens_value in [3, 4]:
        return 10
    elif dens_value >= 5:
        return 20
    else:
        return 0  # dens 1 or 2 => 0

###################################
# Data Loading Function
###################################
def initial_load(data_dir):
    global nearest_df, data_mo_dict, naf2_dict, naf5_dict, code_to_description
    global consommation_min_global, dens_dict

    nearest_df = pd.DataFrame()
    data_mo_dict = {}
    naf2_dict = {}
    naf5_dict = {}
    code_to_description = {}
    dens_dict = {}
    consommation_min_global = 0

    # List of files to load
    file_paths = {
        "naf2_path": os.path.join(data_dir, "naf2008_liste_n2.xls"),
        "naf5_path": os.path.join(data_dir, "naf2008_liste_n5.xls"),
        "path_dens": os.path.join(data_dir, "dens.xlsx"),
        "cat_jur_path": os.path.join(data_dir, "categories-juridiques-insee.csv"),
    }

    try:
        # Load NAF2
        naf2_dict = load_naf_dict(file_paths["naf2_path"])

        # Load NAF5
        naf5_dict = load_naf_dict(file_paths["naf5_path"])

        # Load dens.xlsx => dens_dict
        dens_df = pd.read_excel(file_paths["path_dens"], engine='openpyxl')
        dens_dict = {
            str(row[0]).strip(): int(row[1])
            for row in dens_df.itertuples(index=False)
            if row[0] and row[1]
        }
        logging.info("dens.xlsx loaded.")

        # Load categories-juridiques-insee.csv => code_to_description
        cat_jur_df = pd.read_csv(file_paths["cat_jur_path"], sep=';')
        code_to_description = {
            str(row["Code"]).strip(): str(row["Libellé"]).strip()
            for _, row in cat_jur_df.iterrows()
        }
        logging.info("categories-juridiques-insee.csv loaded.")

        # Load data_mo.csv parts => data_mo_dict
        data_mo_parts = glob.glob(os.path.join(data_dir, "data_mo_part*.csv"))
        if not data_mo_parts:
            logging.warning("No split data_mo CSV files found in 'split_csvs/data_mo' directory.")
        else:
            data_mo_list = []
            for part in data_mo_parts:
                temp_df = pd.read_csv(part, low_memory=False, sep=';', dtype={
                    'id_moral': str,
                    'siren_proprietaire': str,
                    'denomination_proprietaire': str,
                    'adresse': str,
                    'code_forme_juridique_proprietaire': str,
                    'activitePrincipaleEtablissement': str,
                    'latitude': float,
                    'longitude': float
                })
                data_mo_list.append(temp_df)
            mo_df = pd.concat(data_mo_list, ignore_index=True)
            mo_df = mo_df.reset_index().rename(columns={'index': 'line_num'})
            mo_df['line_num'] = mo_df['line_num'] + 1
            data_mo_dict = mo_df.set_index('line_num').to_dict(orient='index')
            logging.info(f"Loaded {len(data_mo_dict)} entries from split data_mo CSV files.")

        # Load nearest_neighbors.csv parts => nearest_df
        nn_parts = glob.glob(os.path.join(data_dir, "nearest_neighbors_part*.csv"))
        if not nn_parts:
            logging.warning("No split nearest_neighbors CSV files found in 'split_csvs/nearest_neighbors' directory.")
        else:
            nn_list = []
            for part in nn_parts:
                temp_df = pd.read_csv(part, sep=',', dtype={
                    'IRIS_CODE': str,
                    'CODE_INSEE': str,
                    'ADRESSE': str,
                    'NOM_COMMUNE': str,
                    'matrice': str,
                    'latitude': float,
                    'longitude': float,
                    'matched_line_numbers': str,
                    'distances_km': str
                })
                nn_list.append(temp_df)
            tmp_nn = pd.concat(nn_list, ignore_index=True)
            tmp_nn['matched_line_numbers'] = tmp_nn['matched_line_numbers'].apply(
                lambda x: [int(num.strip()) for num in x.split(';')] if pd.notna(x) else []
            )
            tmp_nn['distances_km'] = tmp_nn['distances_km'].apply(
                lambda x: [float(num.strip()) for num in x.split(';')] if pd.notna(x) else []
            )
            tmp_nn['min_conso'] = tmp_nn['matrice'].apply(extract_min_consumption)
            nearest_df = tmp_nn
            consommation_min_global = nearest_df['min_conso'].min()
            logging.info(f"Loaded nearest_neighbors.csv with {nearest_df.shape[0]} entries from split CSV files.")

    except Exception as e:
        logging.error(f"Error during initial loading: {e}")
        raise e

    logging.info("Initial loading completed.")

###################################
# Popup Creation Function
###################################
def create_popup(adresse, nom_commune, code_commune, matrice_entries, entreprises, matched_distances, distance_from_start, naf2_dict, naf5_dict, code_to_description):
    """Construct the final HTML popup (2 tables)."""
    popup_content = f"""
    <div style="width:700px; height:600px; overflow-y:auto; background-color:white; padding:10px;">
        <h3>Address: {adresse}, {nom_commune}, {code_commune}</h3>
    """

    # 1) Consumption Details
    if matrice_entries:
        popup_content += """
        <h4>Consumption Details</h4>
        <table border='1' style='width:100%; border-collapse:collapse;'>
            <tr>
                <th>Operator</th>
                <th>Year</th>
                <th>NAF2 Sector Code</th>
                <th>Consumption (MWh)</th>
                <th>PDL</th>
                <th>Distance (km)</th>
            </tr>
        """
        for entry in matrice_entries:
            operateur = entry.get("OPERATEUR","N/A")
            annee = entry.get("ANNEE","N/A")
            code_naf2 = entry.get("CODE_SECTEUR_NAF2_CODE","N/A")
            conso = entry.get("CONSO","N/A")
            pdl = entry.get("PDL","N/A")

            # Use the NAF2 dictionary
            lib_naf2 = naf2_dict.get(code_naf2, "Unknown")

            popup_content += f"""
            <tr>
              <td>{operateur}</td>
              <td>{annee}</td>
              <td>NAF2: {lib_naf2} (Code: {code_naf2})</td>
              <td>{conso}</td>
              <td>{pdl}</td>
              <td>{distance_from_start:.2f} km</td>
            </tr>
            """
        popup_content += "</table>"

    # 2) Associated Companies
    if entreprises:
        popup_content += """
        <h4>Associated Companies</h4>
        <table border='1' style='width:100%; border-collapse:collapse;'>
            <tr>
                <th>SIREN</th>
                <th>Name</th>
                <th>Address</th>
                <th>Juridical Form</th>
                <th>NAF5</th>
                <th>Distance (km)</th>
            </tr>
        """
        for ent, dist_ in zip(entreprises, matched_distances):
            siren = ent.get("siren_proprietaire","N/A")
            denom = ent.get("denomination_proprietaire","N/A")
            adr = ent.get("adresse","N/A")
            forme_jur = code_jurid_to_str(ent.get("code_forme_juridique_proprietaire",""), code_to_description)
            naf_val = ent.get("activitePrincipaleEtablissement","N/A")

            lib_naf5 = naf5_dict.get(naf_val, "")

            popup_content += f"""
            <tr>
              <td>{siren}</td>
              <td><a href='https://www.pappers.fr/entreprise/{siren}' target='_blank'>{denom}</a></td>
              <td>{adr}</td>
              <td>{forme_jur}</td>
              <td>{naf_val} - {lib_naf5}</td>
              <td>{dist_}</td>
            </tr>
            """
        popup_content += "</table>"

    popup_content += "</div>"
    return popup_content

def get_entreprises(matched_line_numbers):
    """Retrieve associated companies from data_mo_dict."""
    results = []
    for ln in matched_line_numbers:
        if ln in data_mo_dict:
            results.append(data_mo_dict[ln])
        else:
            logging.warning(f"Line {ln} not found in data_mo.csv")
    return results

###################################
# Geocoding Function
###################################
def geocode_address(address, geo_communes_url="https://data.geopf.fr/geocodage/search"):
    """Search for lat, lon using the GeoPF API."""
    url = geo_communes_url
    params = {'q': address, 'index': 'address', 'limit': 1}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        feats = data.get('features', [])
        if feats:
            coords = feats[0].get('geometry', {}).get('coordinates', [])
            if len(coords) == 2:
                lon, lat = coords
                return (lat, lon)
        return (None, None)
    except Exception as e:
        logging.error(f"Error in geocode_address: {e}")
        return (None, None)

###################################
# Map Generation Functions
###################################
def create_map_html(lat, lon, rayon_km, conso_min):
    if nearest_df.empty:
        logging.error("nearest_df is empty.")
        return None

    # Calculate citycode => dens => perimeter
    citycode = reverse_geocode_citycode(lat, lon)
    dens_val = dens_dict.get(citycode, None)
    if dens_val is None:
        dens_str = f"(INSEE Commune {citycode} unknown in dens.xlsx)"
        perimetre_txt = ""
    else:
        per = get_perimetre_from_dens(dens_val)
        if per == 0:
            perimetre_txt = "Urban Commune => 2 km"
        elif per == 10:
            perimetre_txt = "Peri-urban Commune => 10 km"
        elif per == 20:
            perimetre_txt = "Rural Commune => 20 km"
        else:
            perimetre_txt = f"Dens={dens_val} => ???"
        dens_str = f"INSEE Code: {citycode}, DENS={dens_val}"

    # BallTree filtering
    df = nearest_df.copy()
    df['lat_rad'] = np.radians(df['latitude'])
    df['lon_rad'] = np.radians(df['longitude'])
    tree = BallTree(df[['lat_rad','lon_rad']].values, metric='haversine')
    start_rad = np.radians([lat, lon])
    rayon_rad = rayon_km / 6371.0

    idx_within = tree.query_radius([start_rad], r=rayon_rad)[0]
    subset = df.iloc[idx_within]
    subset = subset[subset["min_conso"] >= conso_min]

    logging.info(f"Points within {rayon_km} km & conso >= {conso_min} => {subset.shape[0]} rows")

    # Create map
    m = folium.Map(location=[lat, lon], zoom_start=12, tiles=None)
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
        name='Esri World Imagery',
        control=True,
        show=False
    ).add_to(m)
    folium.LayerControl().add_to(m)
    MiniMap(toggle_display=True, zoom_level_offset=-8).add_to(m)
    MeasureControl().add_to(m)
    MousePosition().add_to(m)

    # Green Marker (starting point)
    popup_start = f"""
    <b>Starting Point</b><br>
    Coord={lat},{lon}<br>
    {dens_str}<br>
    {perimetre_txt}
    """
    folium.Marker(
        location=[lat, lon],
        popup=popup_start,
        icon=folium.Icon(color="green", icon="star")
    ).add_to(m)

    # Prepare markers data
    markers_data = []
    for idx, row in subset.iterrows():
        lat_ = float(row['latitude'])
        lon_ = float(row['longitude'])
        adr_ = row.get('ADRESSE','')
        nomcom_ = row.get('NOM_COMMUNE','')
        code_insee_ = row.get('CODE_INSEE','')
        matrice_str = row['matrice']
        matched_nums = row['matched_line_numbers']
        dist_km = row['distances_km']
        dist_from_start = haversine_distance(lat, lon, lat_, lon_)
        # Parse matrice + entreprises
        mat_entries = parse_matrice(matrice_str)
        ent = get_entreprises(matched_nums)

        # Construct final HTML
        popup_html = create_popup(adr_, nomcom_, code_insee_, mat_entries, ent, dist_km, dist_from_start, naf2_dict, naf5_dict, code_to_description)

        min_conso = float(row['min_conso'])
        markers_data.append({
            "lat": lat_,
            "lon": lon_,
            "popup": popup_html,
            "conso": min_conso
        })

    markers_data_json = json.dumps(markers_data)

    # Style Sheets + JS
    style = """
    <style>
    .filter-controls {
        z-index: 9999;
        background-color: white;
        padding: 10px;
        pointer-events: auto !important;
        border-radius: 5px;
        box-shadow: 0 0 15px rgba(0,0,0,0.2);
    }
    .filter-controls input[type=range] {
        width: 150px;
    }
    .leaflet-control-layers {
        background: rgba(255, 255, 255, 0.8);
    }
    </style>
    """
    m.get_root().html.add_child(folium.Element(style))

    icon_url = "https://richelieu-player-ecran.altarea.info/RVB_ALTAREA_10CM.png"
    FloatImage(icon_url, bottom=1, left=1, width='70px', height='70px').add_to(m)

    map_name = m.get_name()

    custom_js = f"""
    <script>
    var refLat = {lat};
    var refLon = {lon};
    var markersData = {markers_data_json};

    var markerObjects = [];

    function haversineDistance(lat1, lon1, lat2, lon2) {{
        var R = 6371;
        var dLat = (lat2 - lat1)*Math.PI/180;
        var dLon = (lon2 - lon1)*Math.PI/180;
        var a = Math.sin(dLat/2)*Math.sin(dLat/2) +
                Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*
                Math.sin(dLon/2)*Math.sin(dLon/2);
        var c = 2*Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
        return R*c;
    }}

    function createMarkers() {{
        for(var i=0; i<markersData.length; i++){{
            var md = markersData[i];
            var marker = L.marker([md.lat, md.lon]).bindPopup(md.popup);
            markerObjects.push({{ marker: marker, conso: md.conso, lat: md.lat, lon: md.lon }});
        }}
    }}

    function filterMarkers() {{
        var distanceMax = parseFloat(document.getElementById('distanceSlider').value);
        var consoMin = parseFloat(document.getElementById('consoSlider').value);

        for(var i=0; i<markerObjects.length; i++){{
            var mo = markerObjects[i];
            var dist = haversineDistance(refLat, refLon, mo.lat, mo.lon);
            if(dist <= distanceMax && mo.conso >= consoMin){{
                if(!window.{map_name}.hasLayer(mo.marker)){{
                    mo.marker.addTo(window.{map_name});
                }}
            }} else {{
                if(window.{map_name}.hasLayer(mo.marker)){{
                    window.{map_name}.removeLayer(mo.marker);
                }}
            }}
        }}
    }}

    function createControls() {{
        var cDiv = L.DomUtil.create('div','filter-controls');

        // Distance slider
        var labelDist = document.createElement('label');
        labelDist.innerHTML = 'Max Distance (km): ';
        var distSlider = document.createElement('input');
        distSlider.type = 'range';
        distSlider.min = 0;
        distSlider.max = 50;
        distSlider.value = {rayon_km};
        distSlider.step = 1;
        distSlider.id = 'distanceSlider';

        var distVal = document.createElement('span');
        distVal.id = 'distanceValue';
        distVal.innerHTML = distSlider.value;

        distSlider.oninput = function(){{
            distVal.innerHTML = this.value;
            filterMarkers();
        }};

        cDiv.appendChild(labelDist);
        cDiv.appendChild(distSlider);
        cDiv.appendChild(distVal);
        cDiv.appendChild(document.createElement('br'));

        // Consumption slider
        var labelConso = document.createElement('label');
        labelConso.innerHTML = '<br>Min Consumption (MWh): ';
        var consoSlider = document.createElement('input');
        consoSlider.type = 'range';
        consoSlider.min = 0;
        consoSlider.max = 5000;
        consoSlider.value = {conso_min};
        consoSlider.step = 50;
        consoSlider.id = 'consoSlider';

        var consoVal = document.createElement('span');
        consoVal.id = 'consoValue';
        consoVal.innerHTML = consoSlider.value;

        consoSlider.oninput = function(){{
            consoVal.innerHTML = this.value;
            filterMarkers();
        }};

        cDiv.appendChild(labelConso);
        cDiv.appendChild(consoSlider);
        cDiv.appendChild(consoVal);

        L.DomEvent.disableClickPropagation(cDiv);
        return cDiv;
    }}

    window.onload = function(){{
        window.{map_name} = window["{map_name}"];
        var controls = createControls();
        var topRight = document.querySelector('.leaflet-top.leaflet-right');
        if(!topRight){{
            var container = document.createElement('div');
            container.className = 'leaflet-top leaflet-right';
            document.querySelector('.leaflet-control-container').appendChild(container);
            topRight = container;
        }}
        topRight.appendChild(controls);

        createMarkers();
        filterMarkers();
    }};
    </script>
    """

    m.get_root().html.add_child(folium.Element(custom_js))

    return m

def generate_map_html(lat, lon, rayon_km, conso_min):
    """Generates the folium map HTML object."""
    m = create_map_html(lat, lon, rayon_km, conso_min)
    return m

def generate_map(adresse=None, lat=None, lon=None, distance_max=20, conso_min=0, data_dir="data"):
    """Generates the map based on provided address or coordinates.

    Parameters:
    - adresse (str): Address to geocode.
    - lat (float): Latitude.
    - lon (float): Longitude.
    - distance_max (float): Maximum radius in km.
    - conso_min (float): Minimum consumption in MWh.
    - data_dir (str): Directory containing data files.

    Returns:
    - folium.Map: Generated map object.
    """
    # Geocode if address is provided
    if adresse:
        lat, lon = geocode_address(adresse)
        if lat is None or lon is None:
            raise ValueError("Address not found via GeoPF.")

    if lat is None or lon is None:
        raise ValueError("Please provide a valid address or coordinates.")

    # Generate the map
    m = generate_map_html(lat, lon, distance_max, conso_min)
    return m
