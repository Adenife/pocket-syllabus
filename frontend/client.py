import os
import requests
import streamlit as st

API_BASE = os.getenv('POCKET_API_URL', 'http://127.0.0.1:8000/api/v1').rstrip('/')


def api(method, path, **kwargs):
    token = st.session_state.get('access_token')
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        response = requests.request(method, API_BASE + path, headers=headers, timeout=120, **kwargs)
        if not response.ok:
            try:
                detail = response.json().get('detail', response.text)
            except ValueError:
                detail = response.text
            st.error(f'Request failed: {detail}')
            return None
        return response
    except requests.RequestException:
        st.error('Cannot reach the backend. Start the PocketSyllabus API and check its address.')
        return None
