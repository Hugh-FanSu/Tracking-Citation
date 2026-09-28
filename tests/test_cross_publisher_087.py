import unittest
from test_standardize import sample,ref
from standardize_citations import org_reference,normalize,unep_rows
from recall_audit import audit

class Publisher087Tests(unittest.TestCase):
    def test_commissioned_is_candidate_not_author(self):
        for statement in ['Prepa- rado para UNEP','Preparado para o United Nations Environment Programme',
                          'Prepared for UNEP','Commissioned by UNEP']:
            identity=org_reference(ref('b','Ubong. 2010. Air Quality Review. '+statement+'.','2010'))
            self.assertIn('target_in_commissioned_report_statement',identity['evidence'])
            self.assertNotIn('organization_in_reference_author_prefix',identity['evidence'])
            self.assertIsNone(identity['joint_authorship'])
        for text in ['Smith. 2010. Discussion of UNEP.','Smith. 2010. Prepared for UNICEF.',
                     'Smith. 2010. Prepared for UNEPish.']:
            self.assertIsNone(org_reference(ref('b',text,'2010')))

    def test_third_party_title_is_not_promoted_to_author(self):
        r=ref('b','Izeze. 2015. "Buhari and Ogoni UNEP Report". Sahara Reporters.','2015')
        r['authors']=[{'name':'Ifeanyi Izeze','family':'Izeze'}]
        r['title']='Buhari and Ogoni UNEP Report';idx=normalize(sample('Example (Izeze 2015).',[r]),'p')
        reference=idx['references'][0]
        idx['occurrences']=[dict(location_id='loc1',raw_marker='(Izeze 2015)',links=[dict(reference_id=reference['reference_id'])])]
        result=audit([],idx,[])
        self.assertEqual(result['findings'][0]['code'],'target_named_in_third_party_source')
        self.assertEqual(result['findings'][0]['location_ids'],['loc1'])
        self.assertIsNone(reference['organization_candidate'])
        reference['target_identity_excluded_due_to_verified_subentry']=True
        self.assertEqual(audit([],idx,[])['findings'],[])
        reference.pop('target_identity_excluded_due_to_verified_subentry')
        idx['occurrences'][0]['links']=[]
        self.assertEqual(audit([],idx,[])['findings'][0]['possible_unlinked_locations'][0]['location_id'],'loc1')
        idx['occurrences']=[];self.assertEqual(audit([],idx,[])['findings'],[])

class Context087Tests(unittest.TestCase):
    def fixture(self,root,terminal=False,mismatch=False):
        import pymupdf
        from target_recovery import coord
        path=root/'context.pdf';doc=pymupdf.open();a=doc.new_page(width=600,height=800)
        fragments=[]
        def block(page,x,ys,texts,size=10):
            boxes=[]
            for y,t in zip(ys,texts):
                page.insert_text((x,y),t,fontsize=size)
                boxes.append(page.search_for(t)[-1])
            box=pymupdf.Rect(boxes[0])
            for b in boxes[1:]:box|=b
            return dict(label='text',self_ref=str(x),text=' '.join(texts),prov=[dict(page_no=page.number+1,bbox=dict(l=box.x0,r=box.x1,t=box.y0,b=box.y1,coord_origin='TOPLEFT'))]),box
        # Equal-width columns with an unfinished line ending at the page bottom.
        left,_=block(a,45,[720,735,750],['Rising pollution is of concern to the','environment and the entire scientific','community and the wider field of sci-'])
        right,_=block(a,330,[720,735,750],['entific research finds significant risks','from the severe chemical emissions','which accumulate and cause effects'+('.' if terminal else '')],size=13 if mismatch else 10)
        b=doc.new_page(width=600,height=800)
        current,box=block(b,45,[70,85,100],['dangerous pollution affects the people','and ecosystems according to UNEP,','as shown by this report (UNEP, 2010).'])
        doc.save(path);doc.close()
        text=current['text'];p=dict(id='p',kind='p',text=text,coordinates=[coord(2,box)],sentences=[],next_paragraph_id=None)
        row=dict(record_id='r',paragraph_id='p',paragraph_text='Research Article '+text,offsets={'start':len(text)-13})
        return path,dict(contexts=[p]),[row],dict(texts=[left,right,current])

    def test_previous_page_columns_restored_without_header(self):
        import tempfile
        from pathlib import Path
        from context_repair import repair_contexts
        with tempfile.TemporaryDirectory() as t:
            pdf,index,rows,document=self.fixture(Path(t))
            changes=repair_contexts(pdf,index,rows,document)
            self.assertTrue(any(c['kind']=='restore_verified_previous_page_opening' for c in changes))
            self.assertTrue(rows[0]['paragraph_text'].startswith('Rising pollution'))
            self.assertNotIn('Research Article',rows[0]['paragraph_text'])
            self.assertIn('scientific research',rows[0]['paragraph_text'])
            self.assertTrue(index['contexts'][0]['text'].startswith('dangerous'))

    def test_do_not_join_completed_or_different_size_previous_column(self):
        import tempfile
        from pathlib import Path
        from context_repair import repair_contexts
        for terminal,mismatch in [(True,False),(False,True)]:
            with tempfile.TemporaryDirectory() as t:
                pdf,index,rows,document=self.fixture(Path(t),terminal,mismatch)
                changes=repair_contexts(pdf,index,rows,document)
                self.assertFalse(any(c['kind']=='restore_verified_previous_page_opening' for c in changes))
