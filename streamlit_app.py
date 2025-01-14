# streamlit_app.py

import streamlit as st
from map_generator import load_data, generate_map
import os
import io
import logging

# Configuration du logging pour Streamlit
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Configuration de la page
    st.set_page_config(
        page_title='Consumer Map Dashboard',
        page_icon=':earth_americas:',
        layout='wide',
        initial_sidebar_state='expanded'
    )

    # Titre de l'application
    st.title("Consumer Map Dashboard :earth_americas:")

    # Fonction de chargement des données avec cache
    @st.cache_data(ttl=3600)  # Cache les données pendant 1 heure
    def get_data(data_directory):
        return load_data(data_directory)

    # Spécifiez le répertoire des données
    data_directory = "data"  # Chemin relatif vers le répertoire des données

    # Chargement des données au démarrage
    with st.spinner("Chargement des données..."):
        try:
            data = get_data(data_directory)
            st.success("Données chargées avec succès !")
            logger.info("Données chargées avec succès.")
        except Exception as e:
            st.error(f"Échec du chargement des données : {e}")
            logger.error(f"Échec du chargement des données : {e}")
            st.stop()

    # Barre latérale pour les paramètres utilisateur
    st.sidebar.header("Paramètres d'entrée")

    # Disposition des entrées en une seule colonne
    with st.sidebar:
        # Adresse ou Coordonnées
        use_address = st.checkbox("Utiliser une adresse pour le géocodage", value=True)
        if use_address:
            address = st.text_input("Adresse", "4 rue de la Paix, Paris")
            lat = None
            lon = None
        else:
            address = ""
            lat = st.number_input("Latitude", value=48.8566, format="%.6f")
            lon = st.number_input("Longitude", value=2.3522, format="%.6f")

        st.markdown("---")  # Séparateur

        # Rayon et Consommation
        distance_max = st.slider("Rayon de recherche (km)", min_value=0, max_value=50, value=20, step=1)
        conso_min = st.slider("Consommation minimale (MWh)", min_value=0, max_value=5000, value=0, step=50)

        st.markdown("---")  # Séparateur

        # Bouton pour générer la carte
        generate_map_btn = st.button("Générer la Carte")

        # Bouton pour réinitialiser les paramètres
        if st.button("Réinitialiser"):
            st.experimental_rerun()

    if generate_map_btn:
        try:
            # Validation des entrées
            if use_address and not address:
                st.error("Veuillez entrer une adresse ou décocher 'Utiliser une adresse pour le géocodage'.")
            elif not use_address and (lat is None or lon is None):
                st.error("Veuillez entrer une latitude et une longitude valides.")
            else:
                with st.spinner("Génération de la carte..."):
                    try:
                        map_object = generate_map(
                            adresse=address if use_address else None,
                            lat=lat if not use_address else None,
                            lon=lon if not use_address else None,
                            distance_max=distance_max,
                            conso_min=conso_min,
                            data=data  # Passage des données chargées
                        )
                        if map_object:
                            # Conversion de la carte en HTML
                            map_html = map_object.get_root().render()

                            # Encodage en bytes pour le téléchargement
                            map_bytes = map_html.encode('utf-8')

                            # Affichage du lien de téléchargement
                            st.success("Carte générée avec succès !")
                            st.download_button(
                                label="Télécharger la Carte en HTML",
                                data=map_bytes,
                                file_name="carte_conso.html",
                                mime="text/html"
                            )
                        else:
                            st.error("Échec de la génération de la carte.")
                            logger.error("Échec de la génération de la carte.")
                    except Exception as e:
                        st.error(f"Erreur lors de la génération de la carte : {e}")
                        logger.error(f"Erreur lors de la génération de la carte : {e}")
        except Exception as e:
            st.error(f"Erreur inattendue : {e}")
            logger.error(f"Erreur inattendue : {e}")

    # Section d'aide et instructions supplémentaires
    st.header("Instructions")
    st.markdown("""
    - **Utiliser une adresse pour le géocodage :** Cochez cette case pour entrer une adresse. L'application géocodera l'adresse pour obtenir la latitude et la longitude.
    - **Adresse :** Entrez une adresse spécifique à géocoder et centrer la carte (par exemple, "4 rue de la Paix, Paris").
    - **Latitude & Longitude :** Alternativement, entrez directement les coordonnées géographiques en décochant la case ci-dessus.
    - **Rayon (km) :** Définissez le rayon de recherche autour du point de départ.
    - **Consommation minimale (MWh) :** Définissez le seuil de consommation minimale pour filtrer les points de données.
    - Cliquez sur **Générer la Carte** pour générer la carte.
    - Après génération, téléchargez la carte en cliquant sur **Télécharger la Carte en HTML**.
    """)

    # Section "À Propos" avec lien vers les données
    st.sidebar.header("À Propos")
    st.sidebar.info("""
    **Consumer Map Dashboard** permet de visualiser les points de consommation d'énergie dans un rayon spécifié autour d'une adresse ou de coordonnées géographiques données.

    **Instructions :**
    - **Utiliser une adresse pour le géocodage :** Cochez cette case pour entrer une adresse. L'application géocodera l'adresse pour obtenir la latitude et la longitude.
    - **Adresse :** Entrez une adresse spécifique à géocoder et centrer la carte (par exemple, "4 rue de la Paix, Paris").
    - **Latitude & Longitude :** Alternativement, entrez directement les coordonnées géographiques en décochant la case ci-dessus.
    - **Rayon de recherche (km) :** Définissez le rayon de recherche autour du point de départ.
    - **Consommation minimale (MWh) :** Définissez le seuil de consommation minimale pour filtrer les points de données.
    - **Générer la Carte :** Cliquez pour générer la carte.
    - **Télécharger la Carte en HTML :** Après génération, téléchargez la carte pour une utilisation hors ligne ou un partage ultérieur.
    
    **Accès aux Données :**
    - Les données utilisées par cette application se trouvent dans le répertoire [`data/`](./data/).
    - Assurez-vous que tous les fichiers nécessaires sont présents dans ce répertoire.
    """)

    st.sidebar.markdown("""
    ---
    **Développé par :** Votre Nom  
    **Contact :** [votre.email@example.com](mailto:votre.email@example.com)
    """)

if __name__ == "__main__":
    main()
