from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Pole, Project
from app.sections import _pole_anchor, project_xyz, project_features, section_result_key


def test_profile_coordinate_transform():
    frame={'origin':[100.0,200.0,10.0],'ux':[1.0,0.0],'uy':[0.0,1.0]}
    station,offset,z=project_xyz(frame,[125.0,197.0,42.5])
    assert station==25.0
    assert offset==-3.0
    assert z==42.5


def test_project_delivery_features_into_three_2d_views():
    frame={'origin':[0.0,0.0,0.0],'ux':[1.0,0.0],'uy':[0.0,1.0]}
    features=[{'properties':{'feature_type':'pole','internal_id':1},'geometry':{'type':'LineString','coordinates':[[0,0,0],[0,0,40]]}},
              {'properties':{'feature_type':'anchor','internal_id':1},'geometry':{'type':'Point','coordinates':[5,-7,2]}}]
    out=project_features(frame,features)
    assert out[0]['geometry']['profile']==[[0.0,0.0],[0.0,40.0]]
    assert out[1]['geometry']['plan']==[5.0,-7.0]
    assert out[1]['geometry']['cross']==[-7.0,2.0]


def test_section_cache_key_changes_with_width():
    a=section_result_key('p',1,2,12,12,.5,90000)
    b=section_result_key('p',1,2,20,12,.5,90000)
    assert a!=b
    assert a.endswith('.json')


def test_qc_section_anchor_uses_generalized_workbook_xyz(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'sections.db'}"); Base.metadata.create_all(engine); db=sessionmaker(bind=engine)()
    try:
        db.add(Project(id='generalized',name='Generalized',customer='Test',crs='EPSG:6424',units='US survey foot',status='READY_FOR_QC'))
        db.add(Pole(project_id='generalized',internal_id=7,pole_number='P-007',block_name=None,
                    manifest_json='{"Easting": 6450000.25, "Northing": 1840000.75, "Elevation": 512.5}'))
        db.commit()
        anchor=_pole_anchor(db,'generalized',7)
        assert anchor['xyz']==(6450000.25,1840000.75,512.5)
        assert anchor['source']=='workbook_xyz' and anchor['has_3d'] is True
    finally:
        db.close()
