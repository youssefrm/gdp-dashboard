# app.py

import streamlit as st
import folium
from streamlit_folium import folium_static
from map_generator import initial_load, generate_map
import os

def main():
    st.set_page_config(
        page_title='Consumer Map Dashboard',
        page_icon=':earth_americas:',
        layout='wide'
    )

    st.title("Consumer Map Dashboard :earth_americas:")

    # Load data
    data_directory = "data"  # Chemin relatif vers le répertoire des données
    with st.spinner("Loading data..."):
        try:
            initial_load(data_directory)
            st.success("Data loaded successfully!")
        except Exception as e:
            st.error(f"Failed to load data: {e}")
            st.stop()

    # Sidebar for user inputs
    st.sidebar.header("Input Parameters")

    # Address or Coordinates
    use_address = st.sidebar.checkbox("Use Address for Geocoding", value=True)
    if use_address:
        address = st.sidebar.text_input("Address", "4 rue de la Paix, Paris")
        lat = None
        lon = None
    else:
        address = ""
        lat = st.sidebar.number_input("Latitude", value=48.8566, format="%.6f")
        lon = st.sidebar.number_input("Longitude", value=2.3522, format="%.6f")

    # Radius and Consumption
    distance_max = st.sidebar.slider("Radius (km)", min_value=0, max_value=50, value=20, step=1)
    conso_min = st.sidebar.slider("Min Consumption (MWh)", min_value=0, max_value=5000, value=0, step=50)

    # Generate Map Button
    generate_map_btn = st.sidebar.button("Generate Map")

    if generate_map_btn:
        try:
            if use_address and not address:
                st.sidebar.error("Please enter an address or uncheck 'Use Address for Geocoding'.")
            elif not use_address and (lat is None or lon is None):
                st.sidebar.error("Please enter valid latitude and longitude.")
            else:
                with st.spinner("Generating map..."):
                    map_object = generate_map(
                        adresse=address if use_address else None,
                        lat=lat if not use_address else None,
                        lon=lon if not use_address else None,
                        distance_max=distance_max,
                        conso_min=conso_min,
                        data_dir=data_directory
                    )
                    
                    if map_object:
                        st.header("Generated Map")
                        folium_static(map_object, width=1200, height=800)
                    else:
                        st.error("Failed to generate the map.")
        except ValueError as ve:
            st.error(str(ve))
        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")

    # Additional Features: Display Instructions
    st.header("Instructions")
    st.markdown("""
    - **Use Address for Geocoding:** Check this box to input an address. The application will geocode the address to get latitude and longitude.
    - **Address:** Enter a specific address to geocode and center the map (e.g., "4 rue de la Paix, Paris").
    - **Latitude & Longitude:** Alternatively, input geographic coordinates directly by unchecking the above box.
    - **Radius (km):** Define the search radius around the starting point.
    - **Min Consumption (MWh):** Set the minimum consumption threshold to filter data points.
    - Click **Generate Map** to visualize the results.
    """)

if __name__ == "__main__":
    main()
