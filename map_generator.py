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
    """Parse la colonne 'matrice' (JSON)."""
    if pd.isna(matrice_str):
        return []
    try:
        data = json.loads(matrice_str)
        if isinstance(data, dict):
            return [data]
        elif isinstance(data, list):
            return data
        else:
            logging.error(f"Format inattendu dans matrice : {matrice_str}")
            return []
    except Exception as e:
        logging.error(f"Erreur dans parse_matrice : {e}")
        return []

def extract_min_consumption(matrice_str):
    """Retourne la consommation la plus basse trouvée dans 'matrice'."""
    mat = parse_matrice(matrice_str)
    conso_list = [float(entry.get("CONSO", 0)) for entry in mat]
    return min(conso_list) if conso_list else np.inf

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calcule la distance orthodromique entre deux points sur Terre."""
    R = 6371.0  # Rayon de la Terre en kilomètres
    dLat = np.radians(lat2 - lat1)
    dLon = np.radians(lon2 - lon1)
    a = (np.sin(dLat/2)**2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dLon/2)**2)
    c = 2 * np.arcsin(np.sqrt(a))
    return R * c

def code_jurid_to_str(val, code_to_description):
    """Convertit le code forme juridique en description via categories-juridiques-insee.csv."""
    if pd.isna(val):
        return ''
    try:
        code_j = str(int(float(val))).strip()
        return code_to_description.get(code_j, "Inconnu")
    except:
        return "Inconnu"

def reverse_geocode_citycode(lat, lon, geo_communes_url="https://geo.api.gouv.fr/communes"):
    """
    Retourne le code INSEE de la commune contenant le point (lat, lon).
    """
    params = {"lat": lat, "lon": lon}
    try:
        response_geo = requests.get(geo_communes_url, params=params, timeout=10)
        response_geo.raise_for_status()
        communes_data = response_geo.json()
        if communes_data:
            commune_info = communes_data[0]
            code_insee = commune_info.get('code', 'Non disponible')
            return code_insee
    except Exception as e:
        logging.error(f"Erreur dans reverse_geocode_citycode : {e}")
    return ""

def load_naf_dict(file_path):
    """Charge un dictionnaire Code -> Libellé depuis un fichier Excel NAF (n2 ou n5)."""
    naf_dict = {}
    try:
        df = pd.read_excel(file_path)
        for _, row in df.iterrows():
            code = str(row['Code']).strip()
            label = str(row['Libellé']).strip()
            naf_dict[code] = label
        logging.info(f"NAF chargé : {len(naf_dict)} entrées depuis {file_path}.")
    except Exception as e:
        logging.error(f"Erreur lors du chargement de NAF depuis {file_path} : {e}")
    return naf_dict

def get_perimetre_from_dens(dens_value):
    """
    Détermine le périmètre basé sur la densité :
    - Communes rurales : dens > 4 => 20 km
    - Communes périurbaines : dens = 3 ou 4 => 10 km
    - Communes urbaines (1 ou 2) => 0 km
    """
    if dens_value in [3, 4]:
        return 10
    elif dens_value >= 5:
        return 20
    else:
        return 0  # dens 1 ou 2 => 0 km

def create_popup(adresse, nom_commune, code_commune, matrice_entries, entreprises, matched_distances, distance_from_start, naf2_dict, naf5_dict, code_to_description):
    """Construit le popup HTML final (2 tableaux)."""
    popup_content = f"""
    <div style="width:700px; height:600px; overflow-y:auto; background-color:white; padding:10px;">
        <h3>Adresse : {adresse}, {nom_commune}, {code_commune}</h3>
    """

    # 1) Détails de la Consommation
    if matrice_entries:
        popup_content += """
        <h4>Détails de la Consommation</h4>
        <table border='1' style='width:100%; border-collapse:collapse;'>
            <tr>
                <th>Opérateur</th>
                <th>Année</th>
                <th>Code Secteur NAF2</th>
                <th>Consommation (MWh)</th>
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

            # Utilisation du dictionnaire NAF2
            lib_naf2 = naf2_dict.get(code_naf2, "Inconnu")

            popup_content += f"""
            <tr>
              <td>{operateur}</td>
              <td>{annee}</td>
              <td>NAF2 : {lib_naf2} (Code : {code_naf2})</td>
              <td>{conso}</td>
              <td>{pdl}</td>
              <td>{distance_from_start:.2f} km</td>
            </tr>
            """
        popup_content += "</table>"

    # 2) Entreprises Associées
    if entreprises:
        popup_content += """
        <h4>Entreprises Associées</h4>
        <table border='1' style='width:100%; border-collapse:collapse;'>
            <tr>
                <th>SIREN</th>
                <th>Dénomination</th>
                <th>Adresse</th>
                <th>Forme Juridique</th>
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

def get_entreprises(matched_line_numbers, data_mo_dict):
    """Récupère les entreprises associées à partir de data_mo_dict."""
    results = []
    for ln in matched_line_numbers:
        if ln in data_mo_dict:
            results.append(data_mo_dict[ln])
        else:
            logging.warning(f"Ligne {ln} non trouvée dans data_mo_parti.csv")
    return results

###################################
# Fonction de Chargement des Données
###################################

def load_data(data_dir):
    """
    Charge toutes les données nécessaires et retourne un dictionnaire contenant les DataFrames et dictionnaires.

    Parameters:
    - data_dir (str): Répertoire contenant les fichiers de données.

    Returns:
    - dict: Données chargées.
    """
    data = {}
    file_paths = {
        "naf2_path": os.path.join(data_dir, "naf2008_liste_n2.xls"),
        "naf5_path": os.path.join(data_dir, "naf2008_liste_n5.xls"),
        "path_dens": os.path.join(data_dir, "dens.xlsx"),
        "cat_jur_path": os.path.join(data_dir, "categories-juridiques-insee.csv"),
    }

    try:
        # Charger NAF2
        data['naf2_dict'] = load_naf_dict(file_paths["naf2_path"])

        # Charger NAF5
        data['naf5_dict'] = load_naf_dict(file_paths["naf5_path"])

        # Charger dens.xlsx
        dens_df = pd.read_excel(file_paths["path_dens"], engine='openpyxl')
        data['dens_dict'] = {
            str(row[0]).strip(): int(row[1])
            for row in dens_df.itertuples(index=False)
            if row[0] and row[1]
        }
        logging.info("dens.xlsx chargé.")

        # Charger categories-juridiques-insee.csv
        cat_jur_df = pd.read_csv(file_paths["cat_jur_path"], sep=';')
        data['code_to_description'] = {
            str(row["Code"]).strip(): str(row["Libellé"]).strip()
            for _, row in cat_jur_df.iterrows()
        }
        logging.info("categories-juridiques-insee.csv chargé.")

        # Charger data_mo_parti.csv
        data_mo_parts = glob.glob(os.path.join(data_dir, "data_mo_part*.csv"))
        if not data_mo_parts:
            logging.warning("Aucune partie data_mo_part*.csv trouvée.")
            data['data_mo_dict'] = {}
        else:
            data_mo_list = []
            for part in data_mo_parts:
                try:
                    temp_df = pd.read_csv(
                        part,
                        low_memory=False,
                        sep=';',
                        dtype={
                            'id_moral': str,
                            'siren_proprietaire': str,
                            'denomination_proprietaire': str,
                            'adresse': str,
                            'code_forme_juridique_proprietaire': str,
                            'activitePrincipaleEtablissement': str,
                            'latitude': float,
                            'longitude': float
                        },
                        on_bad_lines='skip'
                    )
                    data_mo_list.append(temp_df)
                    logging.info(f"Chargé {part} avec succès.")
                except Exception as e:
                    logging.error(f"Erreur lors du chargement de {part} : {e}")

            if data_mo_list:
                mo_df = pd.concat(data_mo_list, ignore_index=True)
                mo_df = mo_df.reset_index().rename(columns={'index': 'line_num'})
                mo_df['line_num'] = mo_df['line_num'] + 1
                data['data_mo_dict'] = mo_df.set_index('line_num').to_dict(orient='index')
                logging.info(f"Chargé {len(data['data_mo_dict'])} entrées depuis data_mo_part*.csv.")
            else:
                logging.warning("Aucune donnée valide chargée pour data_mo_part*.csv.")
                data['data_mo_dict'] = {}

        # Charger nearest_neighbors_parti.csv
        nn_parts = glob.glob(os.path.join(data_dir, "nearest_neighbors_part*.csv"))
        if not nn_parts:
            logging.warning("Aucune partie nearest_neighbors_part*.csv trouvée.")
            data['nearest_df'] = pd.DataFrame()
        else:
            nn_list = []
            for part in nn_parts:
                try:
                    temp_df = pd.read_csv(
                        part,
                        sep=';',
                        dtype={
                            'IRIS_CODE': str,
                            'CODE_INSEE': str,
                            'ADRESSE': str,
                            'NOM_COMMUNE': str,
                            'matrice': str,
                            'latitude': float,
                            'longitude': float,
                            'matched_line_numbers': str,
                            'distances_km': str
                        },
                        on_bad_lines='skip'
                    )
                    nn_list.append(temp_df)
                    logging.info(f"Chargé {part} avec succès.")
                except Exception as e:
                    logging.error(f"Erreur lors du chargement de {part} : {e}")

            if nn_list:
                tmp_nn = pd.concat(nn_list, ignore_index=True)
                tmp_nn['matched_line_numbers'] = tmp_nn['matched_line_numbers'].apply(
                    lambda x: [int(num.strip()) for num in x.split(';')] if pd.notna(x) else []
                )
                tmp_nn['distances_km'] = tmp_nn['distances_km'].apply(
                    lambda x: [float(num.strip()) for num in x.split(';')] if pd.notna(x) else []
                )
                tmp_nn['min_conso'] = tmp_nn['matrice'].apply(extract_min_consumption)
                data['nearest_df'] = tmp_nn
                data['consommation_min_global'] = tmp_nn['min_conso'].min()
                logging.info(f"Chargé nearest_neighbors_part*.csv avec {data['nearest_df'].shape[0]} entrées.")
            else:
                logging.warning("Aucune donnée valide chargée pour nearest_neighbors_part*.csv.")
                data['nearest_df'] = pd.DataFrame()

    except Exception as e:
        logging.error(f"Erreur lors du chargement des données : {e}")
        raise e

    logging.info("Chargement des données terminé.")
    return data

###################################
# Fonctions de Génération de la Carte
###################################

def create_map_html(lat, lon, rayon_km, conso_min, data):
    """
    Crée l'objet carte Folium basé sur les paramètres et les données.

    Parameters:
    - lat (float): Latitude du point de départ.
    - lon (float): Longitude du point de départ.
    - rayon_km (float): Rayon en kilomètres.
    - conso_min (float): Consommation minimale en MWh.
    - data (dict): Données chargées.

    Returns:
    - folium.Map: Carte générée.
    """
    nearest_df = data.get('nearest_df', pd.DataFrame())
    data_mo_dict = data.get('data_mo_dict', {})
    naf2_dict = data.get('naf2_dict', {})
    naf5_dict = data.get('naf5_dict', {})
    code_to_description = data.get('code_to_description', {})
    dens_dict = data.get('dens_dict', {})
    consommation_min_global = data.get('consommation_min_global', 0)

    if nearest_df.empty:
        logging.error("nearest_df est vide.")
        return None

    # Calcul du code INSEE et densité
    citycode = reverse_geocode_citycode(lat, lon)
    dens_val = dens_dict.get(citycode, None)
    if dens_val is None:
        dens_str = f"(Commune INSEE {citycode} inconnue dans dens.xlsx)"
        perimetre_txt = ""
    else:
        per = get_perimetre_from_dens(dens_val)
        if per == 0:
            perimetre_txt = "Commune urbaine => 0 km"
        elif per == 10:
            perimetre_txt = "Commune périurbaine => 10 km"
        elif per == 20:
            perimetre_txt = "Commune rurale => 20 km"
        else:
            perimetre_txt = f"Dens={dens_val} => ???"
        dens_str = f"Code INSEE : {citycode}, DENS={dens_val}"

    # Filtrage avec BallTree
    df = nearest_df.copy()
    df['lat_rad'] = np.radians(df['latitude'])
    df['lon_rad'] = np.radians(df['longitude'])
    tree = BallTree(df[['lat_rad','lon_rad']].values, metric='haversine')
    start_rad = np.radians([lat, lon])
    rayon_rad = rayon_km / 6371.0

    idx_within = tree.query_radius([start_rad], r=rayon_rad)[0]
    subset = df.iloc[idx_within]
    subset = subset[subset["min_conso"] >= conso_min]

    logging.info(f"Points dans un rayon de {rayon_km} km & conso >= {conso_min} => {subset.shape[0]} lignes")

    # Création de la carte
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

    # Marqueur Vert (point de départ)
    popup_start = f"""
    <b>Point de départ</b><br>
    Coord={lat},{lon}<br>
    {dens_str}<br>
    {perimetre_txt}
    """
    folium.Marker(
        location=[lat, lon],
        popup=popup_start,
        icon=folium.Icon(color="green", icon="star")
    ).add_to(m)

    # Préparation des données des marqueurs
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
        # Parser la matrice + entreprises
        mat_entries = parse_matrice(matrice_str)
        ent = get_entreprises(matched_nums, data_mo_dict)

        # Construire le HTML du popup
        popup_html = create_popup(adr_, nomcom_, code_insee_, mat_entries, ent, dist_km, dist_from_start, naf2_dict, naf5_dict, code_to_description)

        min_conso = float(row['min_conso'])
        markers_data.append({
            "lat": lat_,
            "lon": lon_,
            "popup": popup_html,
            "conso": min_conso
        })

    markers_data_json = json.dumps(markers_data)

    # Feuilles de style + JS
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

    # Image flottante (logo ou autre)
    icon_url = "https://richelieu-player-ecran.altarea.info/RVB_ALTAREA_10CM.png"  # Remplacez par votre URL d'image
    FloatImage(icon_url, bottom=1, left=1, width='70px', height='70px').add_to(m)

    map_name = m.get_name()

    # Script JavaScript pour les filtres
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

        // Slider de distance
        var labelDist = document.createElement('label');
        labelDist.innerHTML = 'Max Distance (km) : ';
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

        // Slider de consommation
        var labelConso = document.createElement('label');
        labelConso.innerHTML = '<br>Min Consumption (MWh) : ';
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

def generate_map(adresse=None, lat=None, lon=None, distance_max=20, conso_min=0, data=None):
    """
    Génère la carte basée sur l'adresse ou les coordonnées fournies.

    Parameters:
    - adresse (str): Adresse à géocoder.
    - lat (float): Latitude.
    - lon (float): Longitude.
    - distance_max (float): Rayon maximal en km.
    - conso_min (float): Consommation minimale en MWh.
    - data (dict): Données chargées via load_data.

    Returns:
    - folium.Map: Objet carte généré.
    """
    # Géocodage si une adresse est fournie
    if adresse:
        lat, lon = geocode_address(adresse)
        if lat is None or lon is None:
            raise ValueError("Adresse introuvable via GeoPF.")

    if lat is None or lon is None:
        raise ValueError("Veuillez fournir une adresse valide ou des coordonnées.")

    # Générer la carte
    m = create_map_html(lat, lon, distance_max, conso_min, data)
    return m

def geocode_address(address, geo_communes_url="https://data.geopf.fr/geocodage/search"):
    """Recherche les coordonnées lat, lon via l'API GeoPF."""
    url = geo_communes_url
    params = {'q': address, 'index': 'address', 'limit': 1}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data_resp = resp.json()
        feats = data_resp.get('features', [])
        if feats:
            coords = feats[0].get('geometry', {}).get('coordinates', [])
            if len(coords) == 2:
                lon, lat = coords
                return (lat, lon)
        return (None, None)
    except Exception as e:
        logging.error(f"Erreur dans geocode_address : {e}")
        return (None, None)
