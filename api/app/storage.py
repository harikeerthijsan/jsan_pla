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
    _s3().put_bucket_cors(
        Bucket=bucket_name(),
        CORSConfiguration={'CORSRules':[{
            'AllowedHeaders':['*'],
            'AllowedMethods':['GET','HEAD','PUT','POST'],
            'AllowedOrigins':origins,
            'ExposeHeaders':['ETag','Accept-Ranges','Content-Length','Content-Range'],
            'MaxAgeSeconds':3600,
        }]},
    )

def local_path(key:str)->pathlib.Path:
    p=(LOCAL_ROOT/key).resolve()
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
    _s3().put_object(**args)
    return key

def download_to(key:str,dst:str):
    pathlib.Path(dst).parent.mkdir(parents=True,exist_ok=True)
    if MODE=='local': shutil.copy2(local_path(key),dst)
    else: _s3().download_file(bucket_name(),key,dst)

def upload_from(src:str,key:str,content_type:str|None=None):
    if MODE=='local': return put_local(src,key)
    extra={'ContentType':content_type} if content_type else None
    _s3().upload_file(src,bucket_name(),key,ExtraArgs=extra or {})
    return key

def object_exists(key:str)->bool:
    if MODE=='local': return local_path(key).exists()
    try: _s3().head_object(Bucket=bucket_name(),Key=key); return True
    except ClientError as e:
        if e.response.get('ResponseMetadata',{}).get('HTTPStatusCode')==404: return False
        raise

def presign_put(key:str,content_type:str|None=None,expires=3600):
    if MODE=='local': return None
    params={'Bucket':bucket_name(),'Key':key}
    if content_type: params['ContentType']=content_type
    return _s3().generate_presigned_url('put_object',Params=params,ExpiresIn=expires,HttpMethod='PUT')

def block_url(key:str)->str|None:
    if not key: return None
    if MODE=='local':
        base=os.getenv('LIDAR_PUBLIC_BASE_URL','').rstrip('/')
        if not base:
            railway_domain=os.getenv('RAILWAY_PUBLIC_DOMAIN','').strip()
            base=f'https://{railway_domain}' if railway_domain else 'http://localhost:8000'
        return f"{base}/api/storage/{quote(key, safe='/')}"
    return _s3().generate_presigned_url('get_object',Params={'Bucket':bucket_name(),'Key':key},ExpiresIn=int(os.getenv('SIGNED_URL_TTL','3600')))

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
