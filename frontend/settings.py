import streamlit as st
from frontend.client import API_BASE, api


def sign_in():
    response = api('GET', '/auth/mode')
    if response is None:
        return False
    mode = response.json()
    st.session_state['upload_limit_mb'] = max(1, (mode.get('max_upload_bytes', 50 * 1024 * 1024) + 1024 * 1024 - 1) // (1024 * 1024))
    if not mode['auth_enabled']:
        return True
    if st.session_state.get('access_token'):
        if st.sidebar.button('Sign out'):
            api('POST', '/auth/logout')
            st.session_state.clear()
            st.rerun()
        return True
    st.subheader('Sign in to your library')
    with st.form('login'):
        username = st.text_input('Username')
        password = st.text_input('Password', type='password')
        login = st.form_submit_button('Sign in')
        register = st.form_submit_button('Create account', disabled=not mode['registration_enabled'])
    if login or register:
        payload = {'username': username, 'password': password}
        if register:
            response = api('POST', '/auth/register', json=payload)
            if response is None:
                return False
        response = api('POST', '/auth/login', json=payload)
        if response is not None:
            st.session_state['access_token'] = response.json()['access_token']
            st.rerun()
    return False


def render():
    st.subheader('Offline use and synchronization')
    st.caption('Backend address: ' + API_BASE)
    st.write('After the model is cached, indexing and search can run without internet. Downloaded excerpts work independently of the application.')
    st.write('To synchronize with another PocketSyllabus server, use the synchronization CLI. It transfers originals and metadata, then indexes locally. Conflicting edits are reported for review.')
    st.code('python sync.py --remote-url https://your-server.example/api/v1', language='bash')
    st.caption('Hosted accounts require server authentication to be enabled. Encryption is configured on the server before a library is created.')
