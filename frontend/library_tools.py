import streamlit as st
from frontend.client import api


def preview(doc):
    identifier=doc['id']
    with st.expander('Preview and related materials'):
        page=st.number_input('PDF page (0 = all)',min_value=0,value=0,key='preview-page-'+identifier) if doc['file_type']=='.pdf' else 0
        block_page=st.number_input('Excerpt page',min_value=1,value=1,key='preview-block-'+identifier)
        if st.button('Load preview',key='preview-'+identifier):
            params={'offset':(block_page-1)*10,'limit':10}
            if page: params['page']=page
            response=api('GET','/library/documents/'+identifier+'/preview',params=params)
            if response is not None:
                st.session_state['preview-data-'+identifier]=response.json()
        result=st.session_state.get('preview-data-'+identifier)
        if result:
            st.caption(f"{result['total']} indexed excerpts match this view")
            for item in result['items']:
                location=f"Page {item['page']}" if item['page'] else (f"Line {item['line']}" if item['line'] else '')
                st.caption(item['section']+' · '+location)
                st.text(item['text'])
                if st.button('Bookmark excerpt',key='preview-bookmark-'+str(item['id'])):
                    response=api('POST','/library/bookmarks',json={'chunk_id':item['id']})
                    if response is not None: st.success('Excerpt bookmarked.')
        if st.button('Find related materials',key='related-'+identifier):
            response=api('GET','/library/documents/'+identifier+'/related')
            if response is not None:
                st.session_state['related-data-'+identifier]=response.json()
        for item in st.session_state.get('related-data-'+identifier,[]):
            st.write(f"{item['document']['title']} · similarity {item['score']:.3f}")


def bookmarks():
    page=st.number_input('Bookmarks page',min_value=1,value=1)
    response=api('GET','/library/bookmarks',params={'offset':(page-1)*20,'limit':20})
    if response is None: return
    items=response.json()
    if not items: st.info('Bookmark an excerpt from search or a document preview to build your reading list.')
    for item in items:
        with st.expander(item['title']+' · '+item['section']):
            st.text(item['excerpt'])
            st.caption(f"{item['filename']} · saved from document version {item['document_version']}")
            with st.form('bookmark-'+item['id']):
                annotation=st.text_area('Personal annotation',value=item['annotation'],max_chars=4000)
                saved=st.form_submit_button('Save annotation')
            if saved and api('PATCH','/library/bookmarks/'+item['id'],json={'annotation':annotation}) is not None:
                st.success('Annotation saved.')
            st.download_button('Download bookmarked excerpt',item['excerpt']+'\n\nAnnotation: '+item['annotation'],file_name='bookmark-'+item['id']+'.txt',key='bookmark-download-'+item['id'])
            confirmation=st.checkbox('Remove this bookmark and annotation',key='bookmark-confirm-'+item['id'])
            if st.button('Remove bookmark',key='bookmark-remove-'+item['id'],disabled=not confirmation):
                if api('DELETE','/library/bookmarks/'+item['id']) is not None: st.rerun()


def insights():
    response=api('GET','/library/statistics')
    if response is None: return
    stats=response.json()
    a,b,c=st.columns(3)
    a.metric('Documents',stats['documents']);b.metric('Favorites',stats['favorites']);c.metric('In trash',stats['trash_documents'])
    st.caption(f"Original storage: {stats['storage_bytes']/1024**2:.1f} MiB of {stats['quota_bytes']/1024**2:.0f} MiB, including trash")
    st.write('Indexing status:',stats['status_counts'])
    if stats['subjects']:
        st.dataframe([{'Subject':item['name'],'Documents':item['document_count']} for item in stats['subjects']],hide_index=True)
    if st.button('Review possible duplicates and editions'):
        response=api('GET','/library/duplicates')
        if response is not None:
            st.session_state['duplicate-groups']=response.json()
    for group in st.session_state.get('duplicate-groups',[]):
        st.write(group['title']);st.caption(group['reason'])
        for doc in group['documents']: st.write(doc['title']+' · '+(doc['edition'] or 'edition unspecified'))


def trash():
    page=st.number_input('Trash page',min_value=1,value=1)
    response=api('GET','/library/documents',params={'trash':True,'offset':(page-1)*20,'limit':20})
    if response is None: return
    result=response.json()
    st.caption(f"{result['total']} documents in trash. They are excluded from search but still use storage.")
    labels={doc['id']:doc['title'] for doc in result['items']}
    selected=st.multiselect('Select trash documents',list(labels),format_func=labels.get)
    if st.button('Restore selected documents',disabled=not selected):
        if api('POST','/library/bulk',json={'document_ids':selected,'action':'restore'}) is not None: st.rerun()
    for doc in result['items']:
        with st.expander(doc['title']):
            if st.button('Restore',key='restore-'+doc['id']):
                if api('POST','/library/documents/'+doc['id']+'/restore',params={'expected_version':doc['version']}) is not None:
                    st.rerun()
            confirmed=st.checkbox('Permanently delete original, excerpts, and bookmarks',key='purge-confirm-'+doc['id'])
            if st.button('Delete permanently',key='purge-'+doc['id'],disabled=not confirmed):
                if api('DELETE','/documents/'+doc['id'],params={'expected_version':doc['version']}) is not None:
                    st.rerun()


def transfers(catalog,selected):
    with st.expander('Export or import a collection'):
        st.caption('Exports contain readable originals, organization, and saved notes. Keep the ZIP private.')
        labels={item['id']:item['name'] for item in catalog['collections']}
        collection=st.selectbox('Collection to export',[None,*labels],format_func=lambda value:'Selected documents' if value is None else labels[value])
        if st.button('Prepare library export',disabled=not(selected or collection)):
            response=api('POST','/library/export',json={'document_ids':selected,'collection_id':collection})
            if response is not None: st.session_state['library-export']=response.content
        if st.session_state.get('library-export'):
            st.download_button('Download library ZIP',st.session_state['library-export'],file_name='pocket-library.zip',mime='application/zip',key='library-export-download',on_click='ignore')
        with st.form('library-import'):
            archive=st.file_uploader('Import PocketSyllabus ZIP',type=['zip'],key='bundle-file',max_upload_size=st.session_state.get('upload_limit_mb',50))
            submitted=st.form_submit_button('Import library archive')
        if submitted and archive is not None:
            response=api('POST','/library/import',files={'file':(archive.name,archive.getvalue(),'application/zip')})
            if response is not None: st.success(f"Imported {response.json()['imported']} documents; new originals are queued for indexing.")
