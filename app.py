"""Streamlit entry point; frontend modules manage the library, search, and settings."""
import streamlit as st
from frontend import library, search, settings

st.set_page_config(page_title='PocketSyllabus', page_icon='📚', layout='wide')
st.title('📚 PocketSyllabus')
st.caption('Search your textbooks and notes, and save cited excerpts for offline reading.')
if settings.sign_in():
    search_tab, library_tab, settings_tab = st.tabs(['Search', 'Library', 'Settings'])
    with search_tab:
        search.render()
    with library_tab:
        library.render()
    with settings_tab:
        settings.render()
