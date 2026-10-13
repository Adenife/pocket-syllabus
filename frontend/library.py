import streamlit as st
from frontend.client import api


@st.fragment(run_every='5s')
def render():
    st.subheader('Your textbooks and notes')
    with st.form('upload_form', clear_on_submit=True):
        files = st.file_uploader('Add documents', type=['md', 'txt', 'pdf', 'docx'], accept_multiple_files=True, max_upload_size=st.session_state.get('upload_limit_mb', 50))
        submitted = st.form_submit_button('Upload and index')
    if submitted:
        for file in files:
            response = api('POST', '/documents', files={'file': (file.name, file.getvalue(), file.type)})
            if response is not None:
                result = response.json()
                st.success(f"{file.name}: " + ('already in your library' if result['duplicate'] else 'queued for indexing'))
    with st.expander('Write a note'):
        with st.form('note_form', clear_on_submit=True):
            title = st.text_input('Note title')
            text = st.text_area('Your notes (Markdown supported)')
            save = st.form_submit_button('Save and index note')
        if save:
            if not title.strip() or not text.strip():
                st.warning('Add a title and some text.')
            else:
                content = f'# {title.strip()}\n\n{text}'
                response = api('POST', '/documents', files={'file': ('note.md', content.encode(), 'text/markdown')})
                if response is not None:
                    st.success('Note queued for indexing.')
    page = st.number_input('Library page', min_value=1, step=1)
    st.button('Refresh library')
    response = api('GET', '/documents', params={'offset': (page - 1) * 20, 'limit': 20})
    if response is None:
        return
    documents = response.json()
    if not documents:
        st.info('No documents on this page. Upload a textbook or save your first note.')
    for doc in documents:
        with st.expander(f"{doc['title']} · {doc['status']} · {doc['chunk_count']} chunks"):
            st.caption(f"{doc['filename']} • {doc['size']:,} bytes • version {doc['version']}")
            if doc['status'] in {'queued', 'indexing'}:
                st.info('Indexing in the background. This view refreshes every five seconds.')
                if doc.get('job'):
                    job = doc['job']
                    st.caption(f"Stage: {job['stage']} · {job['chunks']} chunks processed")
            if doc['error']:
                st.error(doc['error'])
            for warning in doc['warnings']:
                st.warning(warning)
            if doc['indexed_version'] and doc['indexed_version'] != doc['version']:
                st.caption('Search currently uses the previous successfully indexed version.')
            with st.form('replace-' + doc['id'], clear_on_submit=True):
                replacement = st.file_uploader('Replace with an updated file', type=['md', 'txt', 'pdf', 'docx'], key='replacement-' + doc['id'], max_upload_size=st.session_state.get('upload_limit_mb', 50))
                replace = st.form_submit_button('Update document', disabled=doc['status'] in {'queued', 'indexing'})
            if replace and replacement is not None:
                response = api('POST', '/documents',
                    params={'document_id': doc['id'], 'expected_version': doc['version']},
                    files={'file': (replacement.name, replacement.getvalue(), replacement.type)})
                if response is not None:
                    st.success('Updated document queued for indexing.')
            if doc['file_type'] in {'.md', '.txt'}:
                if st.button('Edit note', key='edit-' + doc['id']):
                    original = api('GET', f"/documents/{doc['id']}/original")
                    if original is not None:
                        st.session_state['edit-content-' + doc['id']] = original.content.decode('utf-8')
                if 'edit-content-' + doc['id'] in st.session_state:
                    with st.form('edit-form-' + doc['id']):
                        edited = st.text_area('Edit document text', value=st.session_state['edit-content-' + doc['id']], key='edited-' + doc['id'])
                        saved = st.form_submit_button('Save changes', disabled=doc['status'] in {'queued', 'indexing'})
                    if saved:
                        response = api('POST', '/documents', params={'document_id': doc['id'], 'expected_version': doc['version']},
                            files={'file': (doc['filename'], edited.encode('utf-8'), 'text/plain')})
                        if response is not None:
                            st.session_state.pop('edit-content-' + doc['id'], None)
                            st.success('Changes queued for indexing.')
            if st.button('Reindex', key='reindex-' + doc['id']):
                api('POST', f"/documents/{doc['id']}/reindex")
            if st.button('Prepare original download', key='original-' + doc['id']):
                original = api('GET', f"/documents/{doc['id']}/original")
                if original is not None:
                    st.download_button('Download original', original.content, file_name=doc['filename'], key='download-' + doc['id'], on_click='ignore')
            confirmation = st.checkbox('Delete this document and its search index', key='confirm-' + doc['id'])
            if st.button('Delete', key='delete-' + doc['id'], disabled=not confirmation):
                result = api('DELETE', f"/documents/{doc['id']}", params={'expected_version': doc['version']})
                if result is not None:
                    st.session_state.pop('search_response', None)
                    st.rerun()
