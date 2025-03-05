import streamlit as st
import pandas as pd
import calendar
import pulp
from pulp import PULP_CBC_CMD
import io
import logging

# Configuration du logging : le fichier debug.log sera créé
logging.basicConfig(filename="debug.log", level=logging.DEBUG,
                    format="%(asctime)s %(levelname)s: %(message)s")
logging.info("Application démarrée.")

st.title("Optimisation de répartition des kilomètres")
st.write("Chargez votre fichier d'entrée et définissez les paramètres.")

# --- Barre latérale ---
st.sidebar.header("Paramètres de la date")
ref_date = st.sidebar.date_input("Date de référence", value=pd.to_datetime("2025-01-01"))
year = ref_date.year
month = ref_date.month
days_in_month = calendar.monthrange(year, month)[1]
jour_du_mois = ref_date.day
jours_restants = days_in_month - jour_du_mois
st.sidebar.write(f"Jours restants dans le mois : {jours_restants}")

# Nouveau champ : Prix Carburant (MAD/L)
fuel_price = st.sidebar.number_input("Prix Carburant (MAD/L)", value=20.0, step=0.1, format="%.2f")
st.sidebar.write(f"Prix Carburant actuel : {fuel_price} MAD/L")

st.sidebar.header("Répartition par palier (%)")
p0 = st.sidebar.slider("Palier [0 - 4000]", 0, 100, 20, 1)
p1 = st.sidebar.slider("Palier [4000 - 8000]", 0, 100, 20, 1)
p2 = st.sidebar.slider("Palier [8000 - 11000]", 0, 100, 20, 1)
p3 = st.sidebar.slider("Palier [11001 - 14000]", 0, 100, 20, 1)
p4 = st.sidebar.slider("Palier (>14000)", 0, 100, 20, 1)
total_pourc = p0 + p1 + p2 + p3 + p4
st.sidebar.write(f"Somme des pourcentages : {total_pourc} %")
if total_pourc != 100:
    st.sidebar.error("La somme des pourcentages doit être égale à 100 %.")
    st.stop()

# --- Chargement du fichier d'entrée ---
uploaded_file = st.file_uploader("Choisissez le fichier Excel d'entrée (colonnes : Transporteur, Immatriculation, Total)", type=["xlsx"])
if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        logging.info("Fichier d'entrée chargé avec succès.")
    except Exception as e:
        st.error(f"Erreur lors du chargement du fichier : {e}")
        logging.error(f"Erreur de lecture du fichier : {e}")
        st.stop()
    
    st.write("### Aperçu du fichier d'entrée")
    st.dataframe(df.head())
    
    logging.info(f"Colonnes du fichier : {df.columns.tolist()}")
    if "Total" not in df.columns:
        st.error("La colonne 'Total' n'a pas été trouvée dans le fichier.")
        logging.error(f"Colonne 'Total' introuvable. Colonnes disponibles: {df.columns.tolist()}")
        st.stop()
    
    total_deja = df["Total"].sum()
    st.write(f"**Total déjà parcouru** = {total_deja}")
    
    # Calcul dynamique de total_mois (basé sur la moyenne journalière)
    moyenne_journaliere = total_deja / jour_du_mois if jour_du_mois > 0 else 0
    total_mois = total_deja + round(jours_restants * moyenne_journaliere)
    # st.write(f"**Estimation du total mensuel** = {total_mois}")
    
    R = total_mois - total_deja
    # st.write(f"**Km restants à répartir** = {R}")
    
    # Paramètres de Δ
    min_km_par_camion = jours_restants * 100   # 100 km/jour minimum
    max_km_par_camion = jours_restants * 650   # Δ_max fixé à 650 km/jour
    
    # Définition des paliers
    # On définit :
    # Palier 0 : [0 - 4000]
    # Palier 1 : [4000 - 8000]
    # Palier 2 : [8000 - 11000]   (11000 appartient à ce palier)
    # Palier 3 : [11001 - 14000]
    # Palier 4 : >14000 (x >= 14001)
    L = [0, 4000, 8000, 11000, 14001]
    U = [4000, 8000, 11000, 14000, 999999]
    num_paliers = 5
    # Nous utilisons ces intervalles pour l'affichage et dans les contraintes
    palier_intervals = {
        0: "[0 - 4000]",
        1: "[4000 - 8000]",
        2: "[8000 - 11000]",
        3: "[11001 - 14000]",
        4: ">14000"
    }
    
    # Données tarifaires de référence pour chaque prestataire et chaque palier
    tarif_data = [
        {'PRESTATAIRE': 'COMPTOIR SERVICE', 'KM': '[0 - 4000]', 'A fixe': 4.2, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'COMPTOIR SERVICE', 'KM': '[4000-8000]', 'A fixe': 4.2, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'COMPTOIR SERVICE', 'KM': '[8000-11000]', 'A fixe': 3.4, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'COMPTOIR SERVICE', 'KM': '[11000-14000]', 'A fixe': 3.2, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'COMPTOIR SERVICE', 'KM': '>14000', 'A fixe': 3.2, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'SDTM', 'KM': '[0 - 4000]', 'A fixe': 4.58, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'SDTM', 'KM': '[4000-8000]', 'A fixe': 4.58, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'SDTM', 'KM': '[8000-11000]', 'A fixe': 4.16, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'SDTM', 'KM': '[11000-14000]', 'A fixe': 3.65, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'SDTM', 'KM': '>14000', 'A fixe': 3.18, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'TRANSMEL SARL', 'KM': '[0 - 4000]', 'A fixe': 3.25, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'TRANSMEL SARL', 'KM': '[4000-8000]', 'A fixe': 4.26, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'TRANSMEL SARL', 'KM': '[8000-11000]', 'A fixe': 4.26, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'TRANSMEL SARL', 'KM': '[11000-14000]', 'A fixe': 3.73, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'TRANSMEL SARL', 'KM': '>14000', 'A fixe': 3.25, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'S.T INDUSTRIE', 'KM': '[0 - 4000]', 'A fixe': 3.25, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'S.T INDUSTRIE', 'KM': '[4000-8000]', 'A fixe': 4.26, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'S.T INDUSTRIE', 'KM': '[8000-11000]', 'A fixe': 4.26, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'S.T INDUSTRIE', 'KM': '[11000-14000]', 'A fixe': 3.73, 'Quote part gasoil': 0.35},
        {'PRESTATAIRE': 'S.T INDUSTRIE', 'KM': '>14000', 'A fixe': 3.25, 'Quote part gasoil': 0.35}
    ]
    
    # Calculer les nouveaux tarifs en appliquant la formule :
    # nouveau tarif = A fixe + (Quote part gasoil * fuel_price)
    # On reconstruit la structure "tarifs" comme dictionnaire avec pour chaque prestataire une liste de 5 tarifs dans l'ordre des paliers 0 à 4.
    # Pour cela, on normalise les intervalles en supprimant les espaces pour comparer.
    def normalize_interval(s):
        return s.replace(" ", "").lower()
    
    our_intervals = ["[0-4000]", "[4000-8000]", "[8000-11000]", "[11000-14000]", ">14000"]
    updated_tarifs = {}
    for prest in df["Transporteur"].unique():
        prest_tarifs = [None] * 5
        for d in tarif_data:
            if d["PRESTATAIRE"].lower() == prest.lower():
                # Normalisation de l'intervalle
                km_interval = normalize_interval(d["KM"])
                # Trouver l'indice correspondant dans our_intervals
                if km_interval in our_intervals:
                    idx = our_intervals.index(km_interval)
                    prest_tarifs[idx] = d["A fixe"] + d["Quote part gasoil"] * fuel_price
        updated_tarifs[prest] = prest_tarifs
    logging.info(f"Tarifs mis à jour avec le prix carburant {fuel_price} : {updated_tarifs}")
    
    # Utiliser updated_tarifs pour l'optimisation
    tarifs = updated_tarifs
    
    N = len(df)
    trucks = range(N)
    paliers = range(num_paliers)
    
    # Déterminer les camions éligibles pour atteindre au moins 8000 km
    eligible_trucks = [i for i in trucks if df.loc[i, "Total"] + max_km_par_camion >= 8000]
    # st.write(f"Nombre de camions éligibles pour atteindre 8000 km : {len(eligible_trucks)}")
    logging.info(f"{len(eligible_trucks)} camions éligibles sur {N} pour atteindre 8000 km.")
    
    if st.button("Lancer l'optimisation"):
        if total_pourc != 100:
            st.error("La somme des pourcentages doit être égale à 100%.")
            logging.error("La somme des pourcentages n'est pas égale à 100%.")
            st.stop()
        
        with st.spinner("Optimisation en cours (limite 60 s)..."):
            try:
                model = pulp.LpProblem("Optimisation_km", pulp.LpMinimize)
    
                # Variables : x[i] = Total déjà parcouru + Δ[i]
                x = pulp.LpVariable.dicts("x", trucks, lowBound=0, cat=pulp.LpContinuous)
                Delta = pulp.LpVariable.dicts("Delta", trucks,
                                              lowBound=min_km_par_camion,
                                              upBound=max_km_par_camion,
                                              cat=pulp.LpContinuous)
                for i in trucks:
                    km_deja = df.loc[i, "Total"]
                    model += x[i] == km_deja + Delta[i], f"Def_x_{i}"
                model += pulp.lpSum(Delta[i] for i in trucks) == R, "Total_Delta"
    
                # Variables binaires et auxiliaires
                y = pulp.LpVariable.dicts("y", (trucks, paliers), cat=pulp.LpBinary)
                z = pulp.LpVariable.dicts("z", (trucks, paliers), lowBound=0, cat=pulp.LpContinuous)
                for i in trucks:
                    model += x[i] == pulp.lpSum(z[i][j] for j in paliers), f"Decoupage_x_{i}"
                for i in trucks:
                    model += pulp.lpSum(y[i][j] for j in paliers) == 1, f"Unique_palier_{i}"
    
                M = 999999
                for i in trucks:
                    km_deja = df.loc[i, "Total"]
                    for j in paliers:
                        LB_ij = max(km_deja, L[j])
                        model += z[i][j] >= LB_ij * y[i][j], f"LB_{i}_{j}"
                        model += z[i][j] <= U[j] * y[i][j] + M*(1 - y[i][j]), f"UB_{i}_{j}"
                        if km_deja > U[j]:
                            model += y[i][j] == 0, f"Exclure_{i}_{j}"
    
                for i in trucks:
                    model += x[i] <= 4000 + M*(1 - y[i][0]), f"Max_x_palier0_{i}"
                    model += x[i] >= 4000 * y[i][1], f"Min_x_palier1_{i}"
                    model += x[i] <= 8000 + M*(1 - y[i][1]), f"Max_x_palier1_{i}"
                    model += x[i] >= 8000 * y[i][2], f"Min_x_palier2_{i}"
                    model += x[i] <= 11000 + M*(1 - y[i][2]), f"Max_x_palier2_{i}"
                    model += x[i] >= 11000 * y[i][3], f"Min_x_palier3_{i}"
                    model += x[i] <= 14000 + M*(1 - y[i][3]), f"Max_x_palier3_{i}"
                    model += x[i] >= 14001 * y[i][4], f"Min_x_palier4_{i}"
    
                # Contraintes globales de répartition (avec inégalités)
                model += pulp.lpSum(y[i][0] for i in trucks) <= (p0/100)*N, "Limite_palier_0"
                model += pulp.lpSum(y[i][1] for i in trucks) <= (p1/100)*N, "Limite_palier_1"
                model += pulp.lpSum(y[i][4] for i in trucks) <= (p4/100)*N, "Limite_palier_4"
                if eligible_trucks:
                    model += pulp.lpSum(y[i][2] + y[i][3] + y[i][4] for i in eligible_trucks) >= ((p2+p3+p4)/100) * len(eligible_trucks), "Limite_union_2_3_4"
                else:
                    st.warning("Aucun camion éligible pour atteindre 8000 km avec le Δ maximum.")
    
                model += pulp.lpSum(
                    tarifs[df.loc[i, "Transporteur"]][j] * z[i][j]
                    for i in trucks for j in paliers
                ), "Cout_Total"
    
                solver = PULP_CBC_CMD(msg=1, timeLimit=60)
                model.solve(solver=solver)
                status = pulp.LpStatus[model.status]
                logging.info(f"Status du solveur : {status}")
    
            except Exception as e:
                st.error(f"Erreur lors de l'optimisation : {e}")
                logging.error(f"Erreur d'optimisation : {e}")
                st.stop()
    
        if status == "Optimal" or status == "Not Solved":
            st.success("Optimisation terminée !")
    
            # Récapitulatif de répartition par palier
            recaps = []
            for j in paliers:
                count = sum(pulp.value(y[i][j]) for i in trucks)
                recaps.append({
                    "Palier": palier_intervals[j],
                    "Nombre de camions": count,
                    "Pourcentage (%)": (count / N) * 100
                })
            recap_df = pd.DataFrame(recaps)
            st.write("### Récapitulatif de répartition par palier")
            st.dataframe(recap_df)
            logging.info(f"Récapitulatif de répartition: {recap_df.to_dict(orient='records')}")
    
            # Préparation des résultats détaillés
            resultats = []
            for i in trucks:
                transporteur = df.loc[i, "Transporteur"]
                immatriculation = df.loc[i, "Immatriculation"]
                km_deja = df.loc[i, "Total"]
                x_final = pulp.value(x[i])
                delta_val = pulp.value(Delta[i])
                assigned_palier = None
                intervalle = None
                tarif = None
                for j in paliers:
                    if pulp.value(y[i][j]) > 0.5:
                        assigned_palier = j
                        intervalle = palier_intervals[j]
                        tarif = tarifs[transporteur][j]
                        break
                resultats.append({
                    "Immatriculation": immatriculation,
                    "Transporteur": transporteur,
                    "Total (17/02)": km_deja,
                    "Variation": delta_val,
                    "Total Finale": x_final,
                    "Intervalle Palier": intervalle,
                    "Tarif (MAD/km)": tarif
                })
    
            df_resultats = pd.DataFrame(resultats)
            total_km_deja = df_resultats["Total (17/02)"].sum()
            total_delta = df_resultats["Variation"].sum()
            total_x_final = df_resultats["Total Finale"].sum()
            ligne_total = {
                "Immatriculation": "Total",
                "Transporteur": "",
                "Total (17/02)": total_km_deja,
                "Variation": total_delta,
                "Total Finale": total_x_final,
                "Intervalle Palier": "",
                "Tarif (MAD/km)": round(pulp.value(model.objective), 2)
            }
            df_resultats = pd.concat([df_resultats, pd.DataFrame([ligne_total])], ignore_index=True)
    
            # Enregistrer dans un fichier Excel avec deux onglets : Optimisation et Répartition
            towrite = io.BytesIO()
            with pd.ExcelWriter(towrite, engine="openpyxl") as writer:
                df_resultats.to_excel(writer, index=False, sheet_name="Optimisation")
                recap_df.to_excel(writer, index=False, sheet_name="Répartition")
            towrite.seek(0)
            st.download_button(
                label="Télécharger le fichier optimisé",
                data=towrite,
                file_name="resultats_optimisation.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.error("Aucune solution optimale n'a été trouvée dans le délai imparti ou le problème est infaisable.")
            logging.error("Problème infaisable ou temps dépassé.")
else:
    st.info("Veuillez charger un fichier Excel pour commencer.")
