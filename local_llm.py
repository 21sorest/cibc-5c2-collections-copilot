"""Optional CPU GGUF drafting with the same evidence checks as paid generation."""
from functools import lru_cache
import hashlib
import json
import time

from llm import approved_evidence, validate_facts, fact_schema, INSTRUCTIONS
from pipeline import ROOT

MODEL=ROOT/'data/models/qwen2.5-0.5b-instruct-q4_k_m.gguf'
EXPECTED_SHA256='74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db'
PROMPT_VERSION='local-case-facts-v0.4'


@lru_cache(maxsize=1)
def runtime():
    from llama_cpp import Llama
    if not MODEL.exists():
        raise ValueError('The local GGUF model has not been downloaded.')
    digest=hashlib.sha256(MODEL.read_bytes()).hexdigest()
    if digest!=EXPECTED_SHA256:
        raise ValueError('Local model checksum mismatch')
    return Llama(model_path=str(MODEL),n_ctx=8192,n_threads=4,n_gpu_layers=0,verbose=False)


def enhance_summary(bundle,brief):
    approved=approved_evidence(bundle)
    # A small CPU model gets a narrow factual task; policy decisions stay deterministic.
    evidence={key:value for key,value in approved.items() if key.startswith('case:')}
    schema=fact_schema(evidence)
    encoded=json.dumps(evidence,default=str)
    tick=time.monotonic()
    try:
        response=runtime().create_chat_completion(messages=[{'role':'system','content':INSTRUCTIONS},
            {'role':'user','content':'Select case_status and total_overdue_cad, plus current_dpd if known. Evidence JSON: '+encoded}],
            response_format={'type':'json_object','schema':schema},temperature=0,max_tokens=450)
        choice=response['choices'][0]
        if choice['finish_reason']!='stop':
            raise ValueError('Local generation was incomplete')
        facts=validate_facts(json.loads(choice['message']['content']),evidence)
    except (ImportError,KeyError,TypeError,RuntimeError,ValueError) as error:
        raise ValueError('Local draft unavailable or failed evidence checks; keep the deterministic brief. '+str(error)[:160]) from None
    result=dict(brief)
    result['summary']=' '.join(f"{fact['text']} [{', '.join(fact['sources'])}]" for fact in facts)
    result['generator']='local:Qwen2.5-0.5B-Instruct-Q4_K_M'
    result['sources']=list(dict.fromkeys(brief['sources']+list(evidence)))
    result['ai_metadata']={'prompt_version':PROMPT_VERSION,'model_sha256':EXPECTED_SHA256,
        'input_sha256':hashlib.sha256(encoded.encode()).hexdigest(),'latency_seconds':round(time.monotonic()-tick,3),
        'usage':response.get('usage'),'pretrained_not_finetuned':True,'device':'cpu',
        'validation':'typed source/field/value equality and deterministic rendering; employee review required'}
    return result
