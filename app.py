import streamlit as st
import pandas as pd
from datetime import datetime
import json
import firebase_admin
from firebase_admin import credentials, auth, firestore

# --- Firebase Initialization and Authentication ---
# These global variables are provided by the Canvas environment
app_id = typeof __app_id !== 'undefined' ? __app_id : 'default-app-id'
firebase_config = json.loads(typeof __firebase_config !== 'undefined' ? __firebase_config : '{}')
initial_auth_token = typeof __initial_auth_token !== 'undefined' ? __initial_auth_token : None

# Initialize Firebase only once
if not firebase_admin._apps:
    try:
        # Use a placeholder credential if running outside Canvas for local testing
        # In Canvas, firebase_config will be populated.
        if firebase_config:
            cred = credentials.Certificate(firebase_config)
            firebase_admin.initialize_app(cred)
        else:
            # Fallback for local testing if firebase_config is empty (e.g., when not in Canvas)
            # You would need to provide your own service account key here for local testing
            st.warning("Firebase config not found. App will run with limited functionality locally.")
            # Example for local testing (replace with your actual path if needed):
            # cred = credentials.Certificate("path/to/your/serviceAccountKey.json")
            # firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Error initializing Firebase: {e}")
        st.stop() # Stop the app if Firebase init fails

db = firestore.client()

# --- User Authentication (using session_state to persist across reruns) ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = None
    st.session_state.auth_ready = False

@st.cache_resource
def get_firebase_auth_and_db():
    """Caches Firebase auth and db instances."""
    return auth, db

auth_client, db_client = get_firebase_auth_and_db()

# Authenticate user only once
if not st.session_state.auth_ready:
    try:
        if initial_auth_token:
            user = auth_client.sign_in_with_custom_token(initial_auth_token)
            st.session_state.user_id = user['uid']
            st.session_state.auth_ready = True
            st.success(f"Authenticated as user: {st.session_state.user_id}")
        else:
            # Sign in anonymously if no custom token is provided (e.g., local testing)
            user = auth_client.sign_in_anonymously()
            st.session_state.user_id = user['uid']
            st.session_state.auth_ready = True
            st.warning(f"Signed in anonymously as: {st.session_state.user_id}")
    except Exception as e:
        st.error(f"Authentication failed: {e}")
        st.session_state.auth_ready = True # Mark as ready to avoid infinite loop on failure
        st.session_state.user_id = "anonymous_unauthenticated" # Fallback ID

# --- Firestore Paths ---
def get_spendings_collection_ref():
    """Returns the Firestore collection reference for spendings."""
    if st.session_state.user_id:
        return db_client.collection(f"artifacts/{app_id}/users/{st.session_state.user_id}/spendings")
    return None

def get_categories_collection_ref():
    """Returns the Firestore collection reference for categories."""
    if st.session_state.user_id:
        return db_client.collection(f"artifacts/{app_id}/users/{st.session_state.user_id}/categories")
    return None

# --- Data Fetching Functions ---
@st.cache_data(ttl=60) # Cache data for 60 seconds
def fetch_spendings(_user_id, _timestamp): # _timestamp is dummy for cache invalidation
    """Fetches all spending records for the current user."""
    spendings_ref = get_spendings_collection_ref()
    if not spendings_ref:
        return pd.DataFrame() # Return empty if user not authenticated
    try:
        docs = spendings_ref.order_by("timestamp", direction=firestore.Query.DESCENDING).get()
        data = []
        for doc in docs:
            spending = doc.to_dict()
            spending['id'] = doc.id
            # Convert Firestore Timestamp to datetime object for better display
            if 'timestamp' in spending and isinstance(spending['timestamp'], firestore.Timestamp):
                spending['timestamp'] = spending['timestamp'].to_datetime()
            data.append(spending)
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error fetching spendings: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=60) # Cache data for 60 seconds
def fetch_categories(_user_id, _timestamp): # _timestamp is dummy for cache invalidation
    """Fetches all categories for the current user."""
    categories_ref = get_categories_collection_ref()
    if not categories_ref:
        return [] # Return empty if user not authenticated
    try:
        docs = categories_ref.get()
        categories = [doc.to_dict()['name'] for doc in docs]
        return sorted(categories)
    except Exception as e:
        st.error(f"Error fetching categories: {e}")
        return []

# --- Streamlit UI ---
st.set_page_config(layout="centered", page_title="Personal Spending Tracker")

st.title("💸 Personal Spending Tracker")

if not st.session_state.auth_ready:
    st.info("Initializing application and authenticating...")
    st.stop() # Stop until authentication is complete

if not st.session_state.user_id or st.session_state.user_id == "anonymous_unauthenticated":
    st.error("Could not authenticate user. Please try refreshing the page.")
    st.stop()

st.write(f"Logged in as: `{st.session_state.user_id}`")

# Force cache invalidation by updating a dummy timestamp in session state
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = datetime.now()

categories = fetch_categories(st.session_state.user_id, st.session_state.last_update_time)

with st.form("spending_form", clear_on_submit=True):
    st.header("Add New Spending")

    amount = st.number_input("Amount", min_value=0.01, format="%.2f", step=0.01)
    description = st.text_input("Description (e.g., Grocery bill, Coffee)")

    # Category selection
    category_options = ["Select an existing category"] + categories + ["--- Create New Category ---"]
    selected_category_option = st.selectbox("Category", category_options)

    new_category_name = None
    if selected_category_option == "--- Create New Category ---":
        new_category_name = st.text_input("Enter New Category Name")
        if new_category_name:
            # Normalize new category name
            new_category_name = new_category_name.strip().title()
            if new_category_name in categories:
                st.warning(f"Category '{new_category_name}' already exists. Selecting it instead.")
                selected_category_option = new_category_name
            else:
                selected_category_option = new_category_name # Use the new name as the selected one

    submit_button = st.form_submit_button("Add Spending")

    if submit_button:
        if not amount or not description:
            st.error("Please enter both Amount and Description.")
        elif selected_category_option == "Select an existing category":
            st.error("Please select or create a category.")
        elif selected_category_option == "--- Create New Category ---" and not new_category_name:
            st.error("Please enter a name for the new category.")
        else:
            final_category = selected_category_option
            if selected_category_option == "--- Create New Category ---" and new_category_name:
                final_category = new_category_name.strip().title()

            try:
                # Add new category to Firestore if it's truly new
                if final_category not in categories:
                    categories_ref = get_categories_collection_ref()
                    if categories_ref:
                        categories_ref.add({"name": final_category, "userId": st.session_state.user_id})
                        st.session_state.last_update_time = datetime.now() # Invalidate cache for categories
                        st.success(f"New category '{final_category}' created!")

                # Add spending record
                spendings_ref = get_spendings_collection_ref()
                if spendings_ref:
                    spendings_ref.add({
                        "amount": float(amount),
                        "description": description.strip(),
                        "category": final_category,
                        "timestamp": firestore.SERVER_TIMESTAMP, # Use server timestamp for consistency
                        "userId": st.session_state.user_id
                    })
                    st.success("Spending added successfully!")
                    st.session_state.last_update_time = datetime.now() # Invalidate cache for spendings
                else:
                    st.error("Firestore collection not ready. Please refresh.")

            except Exception as e:
                st.error(f"Error adding spending: {e}")

st.markdown("---")

st.header("Your Spendings")

# Display spendings
spendings_df = fetch_spendings(st.session_state.user_id, st.session_state.last_update_time)

if not spendings_df.empty:
    # Reorder columns for better display
    display_df = spendings_df[['timestamp', 'amount', 'category', 'description']]
    display_df.columns = ['Date/Time', 'Amount', 'Category', 'Description']
    st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("No spendings recorded yet. Add some above!")

st.markdown("---")
st.write("Data is stored in Firestore and can be easily exported for ML analysis.")
st.write(f"Firestore Path: `artifacts/{app_id}/users/{st.session_state.user_id}/...`")
