import os, shutil, pathlib
from urllib.parse import quote
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

MODE=os.getenv('STORAGE_MODE','local').lower()
LOCAL_ROOT=pathlib.Path(os.getenv('LOCAL_STORAGE_ROOT','./storage')).resolve()


def _s3():
    return boto3.client(
        's3',
        endpoint_url=os.getenv('BUCKET_ENDPOINT') or os.getenv('S3_ENDPOINT_URL') or os.getenv('AWS_ENDPOINT_URL') or os.getenv('ENDPOINT'),
        aws_access_key_id=os.getenv('BUCKET_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID') or os.getenv('ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('BUCKET_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY') or os.getenv('SECRET_ACCESS_KEY'),
        region_name=os.getenv('BUCKET_REGION') or os.getenv('AWS_DEFAULT_REGION') or os.getenv('REGION') or 'auto',
        config=Config(signature_version='s3v4', s3={'addressing_style':os.getenv('S3_ADDRESSING_STYLE') or os.getenv('AWS_S3_URL_STYLE') or 'virtual'})
    )

def bucket_name():
    return os.getenv('BUCKET') or os.getenv('BUCKET_NAME') or os.getenv('S3_BUCKET') or os.getenv('AWS_S3_BUCKET_NAME')


def bucket_cors_origins() -> list[str]:
    raw = os.getenv('BUCKET_CORS_ORIGINS') or os.getenv('CORS_ORIGINS') or ''
    origins = [x.strip().rstrip('/') for x in raw.split(',') if x.strip()]
    if not origins:
        railway_domain = os.getenv('RAILWAY_PUBLIC_DOMAIN','').strip().strip('/')
        if railway_domain:
            origins = [f'https://{railway_domain}']
    if os.getenv('APP_ENV','development').lower() in {'staging','production'}:
        if not origins:
            raise RuntimeError('BUCKET_CORS_ORIGINS or RAILWAY_PUBLIC_DOMAIN is required for direct browser storage access')
        if '*' in origins:
            raise RuntimeError('BUCKET_CORS_ORIGINS must explicitly list trusted origins, not *')
    return origins


def configure_bucket_cors():
    if MODE=='local' or os.getenv('AUTO_CONFIGURE_BUCKET_CORS','false').lower()!='true': return
    origins=bucket_cors_origins()
    if not origins:
        raise RuntimeError('No bucket CORS origin is configured')
    # One rule per origin: Garage answers a multi-origin rule with all of them in one Access-Control-Allow-Origin
    # header, which browsers reject. A rule per origin echoes just the requesting site, on every S3 store.
    _s3().put_bucket_cors(
        Bucket=bucket_name(),
        CORSConfiguration={'CORSRules':[{
            'AllowedHeaders':['*'],
            'AllowedMethods':['GET','HEAD','PUT','POST'],
            'AllowedOrigins':[origin],
            'ExposeHeaders':['ETag','Accept-Ranges','Content-Length','Content-Range'],
            'MaxAgeSeconds':3600,
        } for origin in origins]},
    )

def local_path(key:str)->pathlib.Path:
    # Lexical normalisation, not resolve(): on Windows resolve() can return a different spelling while another
    # thread is creating folders under the same root, which made valid keys fail this check intermittently.
    p=pathlib.Path(os.path.normpath(os.path.join(LOCAL_ROOT,key)))
    if not p.is_relative_to(LOCAL_ROOT): raise ValueError('Invalid storage key')
    return p

def put_local(src:str,key:str):
    dst=local_path(key); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); return str(dst)

def save_local_bytes(data:bytes,key:str):
    dst=local_path(key); dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(data); return str(dst)

def upload_bytes(data:bytes,key:str,content_type:str|None=None):
    if MODE=='local': return save_local_bytes(data,key)
    args={'Bucket':bucket_name(),'Key':key,'Body':data}
    if content_type: args['ContentType']=content_type
    if LIDAR_CACHE_CONTROL: args['CacheControl']=LIDAR_CACHE_CONTROL
    _s3().put_object(**args)
    return key

def download_to(key:str,dst:str):
    pathlib.Path(dst).parent.mkdir(parents=True,exist_ok=True)
    if MODE=='local': shutil.copy2(local_path(key),dst)
    else: _s3().download_file(bucket_name(),key,dst)

def upload_from(src:str,key:str,content_type:str|None=None):
    if MODE=='local': return put_local(src,key)
    extra={'ContentType':content_type} if content_type else {}
    # Also stored on the object: some S3 stores (Garage) ignore the signed link's response-cache-control override.
    if LIDAR_CACHE_CONTROL: extra['CacheControl']=LIDAR_CACHE_CONTROL
    _s3().upload_file(src,bucket_name(),key,ExtraArgs=extra)
    return key

def object_exists(key:str)->bool:
    if MODE=='local': return local_path(key).exists()
    try: _s3().head_object(Bucket=bucket_name(),Key=key); return True
    except ClientError as e:
        if e.response.get('ResponseMetadata',{}).get('HTTPStatusCode')==404: return False
        raise

def list_objects(prefix:str)->list[str]:
    """List exact keys below a non-empty, directory-shaped object prefix."""
    if not prefix or not prefix.endswith('/') or any(part in {'.','..'} for part in prefix.split('/')):
        raise ValueError('Invalid storage prefix')
    if MODE=='local':
        root=local_path(prefix)
        if not root.exists() or not root.is_dir(): return []
        return sorted(path.relative_to(LOCAL_ROOT).as_posix() for path in root.rglob('*') if path.is_file())
    paginator=_s3().get_paginator('list_objects_v2')
    return [item['Key'] for page in paginator.paginate(Bucket=bucket_name(),Prefix=prefix) for item in page.get('Contents',[]) if item.get('Key')]

def delete_objects(keys:list[str])->list[str]:
    """Delete exact object keys. Missing objects are already deleted and therefore succeed."""
    unique=list(dict.fromkeys(key for key in keys if key))
    if MODE=='local':
        for key in unique:
            path=local_path(key)
            if path.exists() and not path.is_file(): raise IsADirectoryError(f'Storage object is not a file: {key}')
            path.unlink(missing_ok=True)
            parent=path.parent
            while parent!=LOCAL_ROOT:
                try: parent.rmdir()
                except OSError: break
                parent=parent.parent
        return unique
    for start in range(0,len(unique),1000):
        batch=unique[start:start+1000]
        response=_s3().delete_objects(Bucket=bucket_name(),Delete={'Objects':[{'Key':key} for key in batch],'Quiet':True})
        errors=response.get('Errors') or []
        if errors:
            failed=', '.join(str(item.get('Key') or 'unknown') for item in errors[:5])
            raise RuntimeError(f'Object storage refused deletion for: {failed}')
    return unique

def presign_put(key:str,content_type:str|None=None,expires=3600):
    if MODE=='local': return None
    params={'Bucket':bucket_name(),'Key':key}
    if content_type: params['ContentType']=content_type
    return _s3().generate_presigned_url('put_object',Params=params,ExpiresIn=expires,HttpMethod='PUT')

# The viewer reads LiDAR (COPC) in many small range requests. Chrome's disk cache can fail to combine cached and new
# ranges (net::ERR_CACHE_OPERATION_NOT_SUPPORTED), and signed URLs change on every load so caching gains nothing:
# tell the browser not to store them. Set LIDAR_CACHE_CONTROL to empty to send the storage's own headers instead.
LIDAR_CACHE_CONTROL=os.getenv('LIDAR_CACHE_CONTROL','no-store').strip()

def block_url(key:str,local_base_url:str|None=None)->str|None:
    if not key: return None
    if MODE=='local':
        # A literal localhost URL only works in a browser running on the API machine. Use the
        # request's API origin for local/private-network clients unless an explicit public base
        # is configured. Production uses S3 presigned URLs and never reaches this branch.
        base=(os.getenv('LIDAR_PUBLIC_BASE_URL','') or local_base_url or '').rstrip('/')
        if not base:
            railway_domain=os.getenv('RAILWAY_PUBLIC_DOMAIN','').strip()
            base=f'https://{railway_domain}' if railway_domain else ''
        path=f"/api/storage/{quote(key, safe='/')}"
        return f"{base}{path}" if base else path
    params={'Bucket':bucket_name(),'Key':key}
    if LIDAR_CACHE_CONTROL: params['ResponseCacheControl']=LIDAR_CACHE_CONTROL
    return _s3().generate_presigned_url('get_object',Params=params,ExpiresIn=int(os.getenv('SIGNED_URL_TTL','3600')))

def create_multipart(key:str,content_type:str|None=None):
    if MODE=='local': return None
    args={'Bucket':bucket_name(),'Key':key}
    if content_type: args['ContentType']=content_type
    return _s3().create_multipart_upload(**args)['UploadId']

def presign_upload_part(key:str,upload_id:str,part_number:int,expires=3600):
    return _s3().generate_presigned_url('upload_part',Params={'Bucket':bucket_name(),'Key':key,'UploadId':upload_id,'PartNumber':part_number},ExpiresIn=expires,HttpMethod='PUT')

def complete_multipart(key:str,upload_id:str,parts:list[dict]):
    return _s3().complete_multipart_upload(Bucket=bucket_name(),Key=key,UploadId=upload_id,MultipartUpload={'Parts':parts})

def read_bytes(key:str)->bytes:
    if MODE=='local': return local_path(key).read_bytes()
    obj=_s3().get_object(Bucket=bucket_name(),Key=key)
    return obj['Body'].read()

def read_range(key:str,start:int,length:int)->bytes:
    """Bytes [start, start+length) of a stored object, without reading the rest (e.g. a LiDAR header)."""
    if length<=0: return b''
    if MODE=='local':
        with open(local_path(key),'rb') as fh:
            fh.seek(start); return fh.read(length)
    obj=_s3().get_object(Bucket=bucket_name(),Key=key,Range=f'bytes={start}-{start+length-1}')
    return obj['Body'].read()

def storage_diagnostics(sample_key:str|None=None)->dict:
    """What works with the bucket credentials this service has, without revealing them: the bucket itself (signed
    header request) and, for one stored object, a presigned link fetched exactly as a browser would (Range request).
    Pinpoints e.g. SignatureDoesNotMatch on presigned links when the secret differs from the one the bucket expects."""
    import urllib.request, urllib.error, re as _re
    if MODE!='s3': return {'mode':MODE,'note':'Local storage: files are served by the API; there are no bucket credentials to check.'}
    key_id=os.getenv('BUCKET_ACCESS_KEY_ID') or os.getenv('AWS_ACCESS_KEY_ID') or os.getenv('ACCESS_KEY_ID') or ''
    secret=os.getenv('BUCKET_SECRET_ACCESS_KEY') or os.getenv('AWS_SECRET_ACCESS_KEY') or os.getenv('SECRET_ACCESS_KEY') or ''
    out={'mode':'s3','bucket':bucket_name(),'endpoint':os.getenv('BUCKET_ENDPOINT') or os.getenv('S3_ENDPOINT_URL') or os.getenv('AWS_ENDPOINT_URL') or os.getenv('ENDPOINT'),
         'region':os.getenv('BUCKET_REGION') or os.getenv('AWS_DEFAULT_REGION') or os.getenv('REGION') or 'auto',
         'access_key_id_starts':key_id[:6]+'…' if key_id else None,'secret_length':len(secret),
         # Pasted secrets often carry a stray space, newline or quotes; S3 then answers SignatureDoesNotMatch.
         'secret_has_whitespace_or_quotes':bool(_re.search(r'[\s"\']',secret)),'checks':{}}
    try:
        _s3().head_bucket(Bucket=bucket_name()); out['checks']['bucket']='ok'
    except ClientError as exc:
        out['checks']['bucket']=f"failed: {exc.response.get('Error',{}).get('Code','error')}"
    except Exception as exc:
        out['checks']['bucket']=f'failed: {exc.__class__.__name__}'
    if sample_key:
        out['sample_key']=sample_key
        try:
            url=block_url(sample_key)
            request=urllib.request.Request(url,headers={'Range':'bytes=0-15'})
            with urllib.request.urlopen(request,timeout=20) as response:
                out['checks']['presigned_get']=f'ok (HTTP {response.status})'
        except urllib.error.HTTPError as exc:
            body=exc.read(600).decode('utf-8','replace'); code=_re.search(r'<Code>([^<]+)</Code>',body)
            out['checks']['presigned_get']=f"failed: HTTP {exc.code} {code.group(1) if code else ''}".strip()
        except Exception as exc:
            out['checks']['presigned_get']=f'failed: {exc.__class__.__name__}'
    return out
