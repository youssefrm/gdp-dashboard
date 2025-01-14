# streamlit_app.py

import streamlit as st
import folium
from streamlit_folium import st_folium
from map_generator import load_data, generate_map
import os
import io

def main():
    # Configuration de la page
    st.set_page_config(
        page_title='Consumer Map Dashboard',
        page_icon=':earth_americas:',
        layout='wide'
    )

    st.title("Consumer Map Dashboard :earth_americas:")

    # Fonction de chargement des données avec cache
    @st.cache_data  # Utilisez @st.cache si vous utilisez une version antérieure de Streamlit
    def get_data(data_directory):
        return load_data(data_directory)

    # Spécifiez le répertoire des données
    data_directory = "data"  # Chemin relatif vers le répertoire des données

    # Chargement des données au démarrage
    with st.spinner("Chargement des données..."):
        try:
            data = get_data(data_directory)
            st.success("Données chargées avec succès !")
        except Exception as e:
            st.error(f"Échec du chargement des données : {e}")
            st.stop()

    # Barre latérale pour les paramètres utilisateur
    st.sidebar.header("Paramètres d'entrée")

    # Adresse ou Coordonnées
    use_address = st.sidebar.checkbox("Utiliser une adresse pour le géocodage", value=True)
    if use_address:
        address = st.sidebar.text_input("Adresse", "4 rue de la Paix, Paris")
        lat = None
        lon = None
    else:
        address = ""
        lat = st.sidebar.number_input("Latitude", value=48.8566, format="%.6f")
        lon = st.sidebar.number_input("Longitude", value=2.3522, format="%.6f")

    # Rayon et Consommation
    distance_max = st.sidebar.slider("Rayon (km)", min_value=0, max_value=50, value=20, step=1)
    conso_min = st.sidebar.slider("Consommation minimale (MWh)", min_value=0, max_value=5000, value=0, step=50)

    # Bouton pour générer la carte
    generate_map_btn = st.sidebar.button("Générer la Carte")

    if generate_map_btn:
        try:
            if use_address and not address:
                st.sidebar.error("Veuillez entrer une adresse ou décocher 'Utiliser une adresse pour le géocodage'.")
            elif not use_address and (lat is None or lon is None):
                st.sidebar.error("Veuillez entrer une latitude et une longitude valides.")
            else:
                with st.spinner("Génération de la carte..."):
                    map_object = generate_map(
                        adresse=address if use_address else None,
                        lat=lat if not use_address else None,
                        lon=lon if not use_address else None,
                        distance_max=distance_max,
                        conso_min=conso_min,
                        data=data  # Passage des données chargées
                    )
                    
                    if map_object:
                        st.header("Carte Générée")
                        # Affichage de la carte avec st_folium
                        st_folium(map_object, width=1200, height=800)

                        # Conversion de la carte en HTML
                        map_html = map_object.get_root().render()

                        # Encodage en bytes pour le téléchargement
                        map_bytes = map_html.encode('utf-8')

                        # Ajout du bouton de téléchargement
                        st.download_button(
                            label="Télécharger la Carte en HTML",
                            data=map_bytes,
                            file_name="map.html",
                            mime="text/html"
                        )
                    else:
                        st.error("Échec de la génération de la carte.")
        except ValueError as ve:
            st.error(str(ve))
        except Exception as e:
            st.error(f"Une erreur inattendue est survenue : {e}")

    # Instructions supplémentaires
    st.header("Instructions")
    st.markdown("""
    - **Utiliser une adresse pour le géocodage :** Cochez cette case pour entrer une adresse. L'application géocodera l'adresse pour obtenir la latitude et la longitude.
    - **Adresse :** Entrez une adresse spécifique à géocoder et centrer la carte (par exemple, "4 rue de la Paix, Paris").
    - **Latitude & Longitude :** Alternativement, entrez directement les coordonnées géographiques en décochant la case ci-dessus.
    - **Rayon (km) :** Définissez le rayon de recherche autour du point de départ.
    - **Consommation minimale (MWh) :** Définissez le seuil de consommation minimale pour filtrer les points de données.
    - Cliquez sur **Générer la Carte** pour visualiser les résultats.
    - Après génération, vous pouvez télécharger la carte en cliquant sur **Télécharger la Carte en HTML**.
    """)

if __name__ == "__main__":
    main()
