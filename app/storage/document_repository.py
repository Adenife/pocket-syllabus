"""Owner-scoped queries; categories load in batches after stable pagination."""
import json

SORTS={'title':'COALESCE(d.display_title,d.title) COLLATE NOCASE',
       'created_at':'d.created_at','updated_at':'d.updated_at','size':'d.size',
       'status':'d.status','last_opened':'d.last_opened','author':'d.author COLLATE NOCASE',
       'publication_year':'d.publication_year'}

class DocumentRepository:
    def __init__(self,db):
        self.db=db

    def _decorate(self,conn,rows):
        if not rows:
            return []
        results=[];by_id={}
        for row in rows:
            item=dict(row)
            item['title']=item['display_title'] or item['title']
            item['favorite']=bool(item['favorite'])
            item['warnings']=json.loads(item['warnings'])
            item.update(subjects=[],tags=[],collections=[])
            item['job']=None;item['chunk_count']=0
            results.append(item);by_id[item['id']]=item
        ids=list(by_id);marks=','.join('?' for _ in ids)
        for row in conn.execute(f'SELECT document_id,COUNT(*) AS n FROM chunks WHERE document_id IN ({marks}) GROUP BY document_id',ids):
            by_id[row['document_id']]['chunk_count']=row['n']
        for row in conn.execute(f'''SELECT * FROM jobs WHERE document_id IN ({marks})
                    ORDER BY created_at DESC,id DESC''',ids):
            item=by_id[row['document_id']]
            if item['job'] is None:
                item['job']={k:row[k] for k in ('id','status','stage','progress','chunks','error','attempts','document_id')}
        for row in conn.execute(f'''SELECT dc.document_id,c.id,c.name,c.kind,c.description FROM document_categories dc
                JOIN categories c ON c.id=dc.category_id WHERE dc.document_id IN ({marks}) ORDER BY c.normalized_name,c.id''',ids):
            by_id[row['document_id']][{'subject':'subjects','tag':'tags','collection':'collections'}[row['kind']]].append(
                {'id':row['id'],'name':row['name'],'description':row['description']})
        return results

    def get(self,identifier,owner,include_deleted=False):
        with self.db.connect() as conn:
            row=conn.execute('SELECT * FROM documents WHERE id=? AND owner_id=?'+
                ('' if include_deleted else ' AND deleted_at IS NULL'),(identifier,owner)).fetchone()
            return self._decorate(conn,[row])[0] if row else None

    def where(self,owner,filters):
        where=['d.owner_id=?','d.purged_at IS NULL', 'd.deleted_at IS NOT NULL' if filters.get('trash') else 'd.deleted_at IS NULL']
        args=[owner]
        if filters.get('q'):
            # Literal substring matching: '%' and '_' in input are not wildcards.
            value='%'+filters['q'].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            where.append("(COALESCE(d.display_title,d.title) LIKE ? ESCAPE '\\' OR d.filename LIKE ? ESCAPE '\\' OR d.author LIKE ? ESCAPE '\\')")
            args.extend([value]*3)
        for field in ['material_type','status','file_type','favorite']:
            if filters.get(field) is not None:
                where.append('d.'+field+'=?');args.append(filters[field])
        for field in ['subject_ids','tag_ids','collection_ids']:
            values=filters.get(field,[])
            if values:
                where.append('EXISTS (SELECT 1 FROM document_categories dc WHERE dc.document_id=d.id AND dc.category_id IN ('+','.join('?' for _ in values)+'))')
                args.extend(values)
        return ' AND '.join(where),args

    def query(self,owner,**filters):
        where,args=self.where(owner,filters)
        sort=SORTS.get(filters.get('sort_by','created_at'))
        direction=filters.get('sort_order','desc').upper()
        if sort is None or direction not in {'ASC','DESC'}:
            raise ValueError('Invalid sort field/order')
        with self.db.connect() as conn:
            conn.execute('BEGIN')
            total=conn.execute('SELECT COUNT(*) FROM documents d WHERE '+where,args).fetchone()[0]
            rows=conn.execute('SELECT d.* FROM documents d WHERE '+where+
                f' ORDER BY {sort} {direction},d.id ASC LIMIT ? OFFSET ?',
                [*args,filters.get('limit',100),filters.get('offset',0)]).fetchall()
            items=self._decorate(conn,rows)
        return {'items':items,'total':total,'offset':filters.get('offset',0),'limit':filters.get('limit',100)}

    def matching_ids(self,owner,**filters):
        where,args=self.where(owner,filters)
        with self.db.connect() as conn:
            return [row[0] for row in conn.execute('SELECT d.id FROM documents d WHERE '+where,args)]

    def list(self,owner,offset=0,limit=100):
        return self.query(owner,offset=offset,limit=limit)['items']
