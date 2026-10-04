"""ASR cache association follows current approved source metadata, never cached case IDs."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import duckdb
from speech import approved_cached_audio


class AudioCacheChecks(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.cache=self.root/'cache'
        self.cache.mkdir()
        self.audio=self.root/'files/voice/VS-1.wav'
        self.audio.parent.mkdir(parents=True)
        self.audio.write_bytes(b'verified synthetic audio fixture')
        self.digest=hashlib.sha256(self.audio.read_bytes()).hexdigest()
        self.con=duckdb.connect()
        self.addCleanup(self.con.close)
        self.con.execute('CREATE SCHEMA raw; CREATE SCHEMA curated')
        self.con.execute('CREATE TABLE raw.voice_samples(voice_sample_id VARCHAR,transcript_id VARCHAR,contact_id VARCHAR,file_path VARCHAR,checksum_sha256 VARCHAR,duration_sec VARCHAR)')
        self.con.execute('CREATE TABLE curated.transcripts(transcript_id VARCHAR,case_id VARCHAR,contact_id VARCHAR,voice_sample_id VARCHAR,file_path VARCHAR,call_start_ts TIMESTAMP)')
        self.con.execute("INSERT INTO raw.voice_samples VALUES ('VS-1','T1','CT1','voice/VS-1.wav',?,'10')",[self.digest])
        self.con.execute("INSERT INTO curated.transcripts VALUES ('T1','CASE1','CT1','VS-1','transcripts/T1.json','2026-09-25')")
        self.body={'voice_sample_id':'VS-1','case_id':'CASE1','file_path':'voice/VS-1.wav',
            'transcript_path':'transcripts/T1.json','checksum_sha256':self.digest,'audio_sha256':self.digest,
            'model':'small.en','requires_speaker_review':True,
            'segments':[{'start_sec':1,'end_sec':2,'text':'Customer speech needs verification.','speaker':'unassigned'}]}
        self.write(self.body)

    def write(self,body):
        (self.cache/'VS-1.json').write_text(json.dumps(body),encoding='utf-8')

    def read(self,case_id='CASE1'):
        return approved_cached_audio(self.con,case_id,self.cache,self.root)

    def test_verified_cache_disappears_when_source_is_quarantined_or_reassigned(self):
        self.assertEqual(self.read()[0]['case_id'],'CASE1')
        self.assertFalse(self.read('CASE2'))
        self.con.execute("UPDATE curated.transcripts SET case_id='CASE2'")
        self.assertFalse(self.read())
        self.assertFalse(self.read('CASE2'))  # Cached association still says CASE1.
        self.con.execute('DELETE FROM curated.transcripts')
        self.assertFalse(self.read())

    def test_forged_cache_paths_ids_checksums_and_recording_changes_are_rejected(self):
        for field,value in [('case_id','CASE2'),('voice_sample_id','VS-2'),('file_path','../outside.wav'),
            ('transcript_path','transcripts/T2.json'),('checksum_sha256','0'*64),('audio_sha256','0'*64)]:
            with self.subTest(field=field):
                self.write({**self.body,field:value})
                self.assertFalse(self.read())
        self.write(self.body)
        self.audio.write_bytes(b'different recording')
        self.assertFalse(self.read())

    def test_voice_metadata_must_agree_with_the_approved_contact_and_voice_link(self):
        self.con.execute("UPDATE raw.voice_samples SET contact_id='OTHER'")
        self.assertFalse(self.read())
        self.con.execute("UPDATE raw.voice_samples SET contact_id='CT1'")
        self.con.execute("UPDATE curated.transcripts SET voice_sample_id='VS-2'")
        self.assertFalse(self.read())

    def test_malformed_cache_and_unverified_speakers_or_ambiguous_sources_are_skipped(self):
        path=self.cache/'VS-1.json'
        for text in ('{broken','[]','null'):
            path.write_text(text,encoding='utf-8')
            self.assertFalse(self.read())
        for segment in ({'start_sec':float('nan'),'end_sec':2,'text':'Bad timestamp','speaker':'unassigned'},
            {'start_sec':1,'end_sec':2,'text':'Unverified diarization','speaker':'customer'}):
            self.write({**self.body,'segments':[segment]})
            self.assertFalse(self.read())
        self.write(self.body)
        self.con.execute('INSERT INTO raw.voice_samples SELECT * FROM raw.voice_samples')
        self.assertFalse(self.read())


if __name__=='__main__':
    unittest.main()
