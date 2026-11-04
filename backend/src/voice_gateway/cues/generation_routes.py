"""Authenticated, immutable complete-generation cue delivery."""
import re
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from backend.src.voice_gateway.jobs.auth import owns_device


def install_mp3_cue_routes(app: FastAPI, generations, device_tokens):
    def authenticate(request):
        if not owns_device(request.headers.get('X-Device-Id',''),
                           request.headers.get('Authorization'),device_tokens):
            raise HTTPException(status_code=401)

    # Install before the legacy /cues/{name} catch-all.
    @app.get('/api/device/cues/generation')
    def manifest(request: Request):
        authenticate(request)
        data=generations.manifest() if generations is not None else None
        if data is None:
            return JSONResponse({'status':generations.status() if generations else {'status':'disabled'}},
                                status_code=503,headers={'Retry-After':'60','Cache-Control':'private, no-store'})
        data['update']=generations.status()
        return JSONResponse(data,headers={'Cache-Control':'private, no-store'})

    @app.get('/api/device/cues/mp3/{generation_id}/{name}.mp3')
    def audio(request: Request,generation_id: str,name: str):
        authenticate(request)
        data=generations.audio(generation_id,name) if generations and re.fullmatch('[0-9a-f]{64}',generation_id) else None
        if data is None:
            raise HTTPException(status_code=404)
        import hashlib
        digest=hashlib.sha256(data).hexdigest()
        return Response(data,media_type='audio/mpeg',headers={
            'ETag':f'"{digest}"','Cache-Control':'private, no-store'})
