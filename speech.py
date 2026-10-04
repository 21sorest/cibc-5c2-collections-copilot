"""Local speech-to-text on verified synthetic recordings, with reference WER evaluation."""
import argparse
import hashlib
import json
import math
import re
import time
import zipfile

import duckdb
from features import safe_file
from pipeline import ROOT, DEFAULT_RELEASE
from text_signals import extract, normalize

VOICE_SHA256='fcbe7a7e1af7eef40eed874c457f604dc02e9b4c119bd913a5b24a52b5164234'


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as handle:
        while chunk:=handle.read(1024*1024):
            digest.update(chunk)
    return digest.hexdigest()


def approved_cached_audio(con,case_id,cache_dir=None,release=DEFAULT_RELEASE):
    """Display only cached recordings whose current source still serves this case."""
    cache_dir=cache_dir or ROOT/'data/transcriptions'
    cursor=con.execute("""SELECT v.voice_sample_id,v.file_path,v.checksum_sha256,v.duration_sec,
        t.case_id,t.file_path AS transcript_path
        FROM raw.voice_samples v JOIN curated.transcripts t ON v.transcript_id=t.transcript_id
        AND v.contact_id=t.contact_id AND (t.voice_sample_id IS NULL OR t.voice_sample_id=v.voice_sample_id)
        WHERE t.case_id=? AND try_cast(t.call_start_ts AS DATE)<=DATE '2026-09-28'""",[case_id])
    columns=[column[0] for column in cursor.description]
    grouped={}
    for values in cursor.fetchall():
        source=dict(zip(columns,values))
        grouped.setdefault(source['voice_sample_id'],[]).append(source)
    approved=[]
    for voice_id,sources in sorted(grouped.items(),key=lambda item:str(item[0])):
        if len(sources)!=1 or not isinstance(voice_id,str) or not re.fullmatch(r'VS-\d+',voice_id):
            continue
        source=sources[0]
        path=cache_dir/(voice_id+'.json')
        try:
            if not path.is_file() or path.stat().st_size>1024*1024:
                continue
            body=json.loads(path.read_text(encoding='utf-8'))
            checksum=source['checksum_sha256']
            if not isinstance(body,dict) or not isinstance(checksum,str) or not re.fullmatch(r'[0-9a-f]{64}',checksum):
                continue
            if any(body.get(field)!=source[field] for field in ('voice_sample_id','file_path','checksum_sha256','case_id','transcript_path')) or body.get('audio_sha256')!=checksum:
                continue
            audio=safe_file(release,source['file_path'])
            if not audio.is_file() or file_hash(audio)!=checksum:
                continue
            segments=body.get('segments')
            duration=float(source['duration_sec'])
            if not math.isfinite(duration) or duration<=0 or not isinstance(segments,list) or not 1<=len(segments)<=2000:
                continue
            previous=0
            for segment in segments:
                if not isinstance(segment,dict) or not isinstance(segment.get('text'),str) or len(segment['text'])>12000 or segment.get('speaker')!='unassigned':
                    raise ValueError('Invalid cached segment')
                start,end=segment['start_sec'],segment['end_sec']
                if any(isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) for value in (start,end)) or not previous<=start<=end<=duration+1:
                    raise ValueError('Invalid cached timestamps')
                previous=start
            if body.get('requires_speaker_review') is not True or not isinstance(body.get('model'),str) or not body['model'].strip() or len(body['model'])>100:
                continue
            # Cache provenance validates association, not ASR accuracy or speaker attribution.
            approved.append({**source,'segments':segments,'model':body['model'],'audio_sha256':checksum,'requires_speaker_review':True})
        except (OSError,UnicodeError,ValueError,TypeError,KeyError):
            continue
    return approved


def word_error(reference,hypothesis):
    a=re.findall(r'\w+',normalize(reference))
    b=re.findall(r'\w+',normalize(hypothesis))
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):
            current.append(min(previous[j]+1,current[j-1]+1,previous[j-1]+(x!=y)))
        previous=current
    return {'edits':previous[-1],'reference_words':len(a),'wer':previous[-1]/len(a) if a else None}


def samples(limit):
    with duckdb.connect(str(ROOT/'data/collections.duckdb'),read_only=True) as con:
        cursor=con.execute("""SELECT v.voice_sample_id,v.file_path,v.checksum_sha256,v.duration_sec,t.case_id,t.file_path AS transcript_path
          FROM raw.voice_samples v JOIN curated.transcripts t USING(transcript_id)
          WHERE v.contact_id IS NOT DISTINCT FROM t.contact_id
            AND v.voice_sample_id IS NOT DISTINCT FROM t.voice_sample_id
            AND v.language IN ('en','en-CA') AND t.language IN ('en','en-CA')
          ORDER BY v.voice_sample_id LIMIT ?""",[limit])
        return [dict(zip([c[0] for c in cursor.description],row)) for row in cursor.fetchall()]


def prepare(limit):
    archive=ROOT/'maple_data/maple_collections_voice.zip'
    if file_hash(archive)!=VOICE_SHA256:
        raise ValueError('Audio archive SHA256 differs from the public Hugging Face LFS metadata')
    selected=samples(limit)
    with zipfile.ZipFile(archive) as pack:
        names=pack.namelist()
        for row in selected:
            target=safe_file(DEFAULT_RELEASE,row['file_path'])
            matched=[name for name in names if name.endswith('/'+row['file_path']) or name==row['file_path']]
            if len(matched)!=1:
                raise ValueError('Ambiguous/missing voice member '+row['voice_sample_id'])
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(pack.read(matched[0]))
            if file_hash(target)!=row['checksum_sha256']:
                raise ValueError('Extracted recording checksum mismatch')
    print(json.dumps({'archive_verified':True,'extracted_samples':len(selected)},indent=2))


def evaluate(limit,model_name):
    from faster_whisper import WhisperModel
    started=time.monotonic()
    model=WhisperModel(model_name,device='cpu',compute_type='int8',cpu_threads=4,
        download_root=str(ROOT/'data/models/whisper'))
    rows=[]
    output=ROOT/'data/transcriptions'
    output.mkdir(parents=True,exist_ok=True)
    for sample in samples(limit):
        audio=safe_file(DEFAULT_RELEASE,sample['file_path'])
        if not audio.exists() or file_hash(audio)!=sample['checksum_sha256']:
            raise ValueError('Run prepare first; recording must match its source checksum')
        body=json.loads(safe_file(DEFAULT_RELEASE,sample['transcript_path']).read_text(encoding='utf-8'))
        reference=' '.join(turn['text'] for turn in body['turns'])
        tick=time.monotonic()
        segments,info=model.transcribe(str(audio),language='en',beam_size=5,vad_filter=True,condition_on_previous_text=False)
        segments=[{'start_sec':s.start,'end_sec':s.end,'text':s.text.strip(),'speaker':'unassigned'} for s in segments]
        hypothesis=' '.join(s['text'] for s in segments)
        elapsed=time.monotonic()-tick
        payload={**sample,'model':model_name,'device':'cpu','compute_type':'int8','segments':segments,
            'text':hypothesis,'requires_speaker_review':True,'audio_sha256':file_hash(audio),'language':info.language}
        (output/(sample['voice_sample_id']+'.json')).write_text(json.dumps(payload,indent=2),encoding='utf-8')
        score=word_error(reference,hypothesis)
        rows.append({'voice_sample_id':sample['voice_sample_id'],'case_id':sample['case_id'],**score,
            'duration_sec':float(sample['duration_sec']),'inference_seconds':round(elapsed,3),
            'real_time_factor':round(elapsed/float(sample['duration_sec']),4),
            'full_call_reference_signals':extract(reference),'full_call_asr_signals':extract(hypothesis)})
        print(json.dumps(rows[-1]),flush=True)
    words=sum(r['reference_words'] for r in rows)
    report={'model':model_name,'pretrained_not_finetuned':True,'device':'cpu','compute_type':'int8',
        'samples':rows,'aggregate_wer':sum(r['edits'] for r in rows)/words if words else None,
        'total_seconds_including_model_load':round(time.monotonic()-started,3),
        'limitations':['English synthetic TTS sample only, not representative of real calls.',
            'Single-channel mixed speakers have no automatic diarization. Employee must select/verify customer speech before conversation signal extraction.',
            'Full-call signal agreement is a transcription diagnostic only, not a customer-label accuracy measure.',
            'WER ignores punctuation/case, retains numbers as tokens. Reference script and spoken TTS may differ.']}
    (ROOT/'reports'/('speech_evaluation_'+model_name.replace('.','_')+'_'+str(limit)+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['prepare','evaluate'])
    parser.add_argument('--limit',type=int,default=5)
    parser.add_argument('--model',default='small.en')
    args=parser.parse_args()
    if not 1<=args.limit<=2000:
        parser.error('limit must be 1 to 2000')
    prepare(args.limit) if args.command=='prepare' else evaluate(args.limit,args.model)
