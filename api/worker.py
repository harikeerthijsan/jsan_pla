import os,time
from app.db import Base,engine,SessionLocal
from app.models import ProcessingJob
from app.processor import process_job

Base.metadata.create_all(bind=engine)
print('PLA QC worker started', flush=True)
while True:
    db=SessionLocal()
    try:
        job=db.query(ProcessingJob).filter(ProcessingJob.status=='QUEUED').order_by(ProcessingJob.created_at).first()
        jid=job.id if job else None
    finally: db.close()
    if jid:
        print('Processing',jid,flush=True); process_job(jid)
    else: time.sleep(int(os.getenv('WORKER_POLL_SECONDS','3')))
