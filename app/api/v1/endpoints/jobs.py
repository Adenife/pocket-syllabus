from fastapi import APIRouter, Depends, HTTPException, Request
from app.core.security import current_owner, get_context
from app.schemas.job import JobItem

router = APIRouter(prefix='/jobs', tags=['jobs'])

@router.get('/{identifier}', response_model=JobItem)
def job(identifier: str, request: Request, owner: str = Depends(current_owner)):
    with get_context(request).db.connect() as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=? AND owner_id=?', (identifier, owner)).fetchone()
    if not row:
        raise HTTPException(404, 'Job not found')
    return dict(row)
