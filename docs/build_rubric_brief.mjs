// Rebuild the draft with the bundled Codex presentation runtime, then render for review.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=process.cwd();
const runtime='C:/Users/desai/.cache/codex-runtimes/codex-primary-runtime/dependencies';
process.env.RUNTIME_NODE_MODULES=runtime+'/node/node_modules';
const skill='C:/Users/desai/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.12148/skills/presentations';
const {Presentation,PresentationFile}=await import(pathToFileURL(runtime+'/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs').href);
const {resolvePresentationFont,applyPresentationChartFont,finalizePresentation}=await import(pathToFileURL(skill+'/container_tools/artifact_tool_utils.mjs').href);
const family=resolvePresentationFont({fontFamily:'Arial'});
const classifier=JSON.parse(await fs.readFile(root+'/reports/classifier_evaluation.json','utf8'));
const speech=JSON.parse(await fs.readFile(root+'/reports/speech_evaluation_small_en_2000.json','utf8'));
const trained=JSON.parse(await fs.readFile(root+'/reports/llm_training.json','utf8'));
const finalTest=JSON.parse(await fs.readFile(root+'/reports/llm_adapter_test.json','utf8'));
const safeguards=JSON.parse(await fs.readFile(root+'/reports/decision_safeguards.json','utf8'));

const checks=JSON.parse(await fs.readFile(root+'/reports/implementation_checks.json','utf8'));
const semantics=JSON.parse(await fs.readFile(root+'/reports/question_semantics.json','utf8'));
const p=Presentation.create({slideSize:{width:1280,height:720}});
const staging=root+'/tmp/rubric_brief_v9';
await fs.mkdir(staging,{recursive:true});
await fs.mkdir(root+'/submission',{recursive:true});
function text(slide,value,left,top,width,height,size=30,color='#253746',bold=false){
 const shape=slide.shapes.add({geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
 shape.text=value;shape.text.style={typeface:family,fontSize:size,color,bold,autoFit:'none'};return shape;
}
function slide(title,notes){const s=p.slides.add();s.background.fill='#FAFAF8';text(s,title,72,50,1136,90,44,'#8C183A',true);s.speakerNotes.textFrame.setText(notes);return s;}
function rows(s,values,size=30,step=112){values.forEach((v,i)=>text(s,v,76,165+i*step,1120,step-8,size));}
const source='Sources: README.md; docs/model_decisions.md; Build Phase/CIBC Hackathon Build Phase - Instructions.pdf; System Design Phase/5C2_SystemDesign.pdf. Synthetic Maple Bank dataset.';
let s=slide('Collections Copilot',source);
text(s,'Helping collections employees prepare a case and respond to customers',76,225,1080,175,48,'#253746',true);
text(s,'A unified customer view, relevant policy and suggested assistance',76,465,1100,95,30);
text(s,'Team 5C2. Project overview for rubric discussion.',76,600,1100,60,26,'#64717B');
s=slide('Four connected layers',source);
rows(s,[
'1  Data foundation: match identities across five systems, validate records and build a customer C360 with explicit missingness.',
'2  Questions: answer supported collections questions using trusted SQL, current policy or call evidence, with sources and refusals.',
'3  Features: serve 12 versioned case features with the same offline and online definitions, plus text signals.',
'4  Employee assistance: suggest a response or next step, explain its evidence and record accept, edit or reject decisions.'
]);
s=slide('Six use cases',source+' Agent Assist remains primary. Other workflows now include deeper contextual evidence and employee review. Sources: docs/deeper_use_cases.md; calls.py; decisions.py.');
const useCases=[
['Agent Assist','Help during the conversation, including hardship, disputes and policy guidance.'],
['Next Best Action','Explain action reasons, alternatives and programme eligibility prerequisites.'],
['Channel comparison','Show outcome support, uncertainty, timing and unmet operational checks.'],
['Agent routing','Match all required skills and language; explain capacity and roster exclusions.'],
['Post-call summary','Separate proposed terms, explicit commitments and follow-ups with timestamps.'],
['Quality assurance','Review context for ten checklist items and record employee evidence per item.']
];
for(let i=0;i<6;i++){const x=i<3?76:676;const y=175+(i%3)*155;text(s,useCases[i][0],x,y,530,44,30,'#8C183A',true);text(s,useCases[i][1],x,y+52,530,96,27);}
text(s,'Local reviewed workflows. Treatment effectiveness and production readiness remain unverified.',76,655,1130,45,22,'#64717B');
s=slide('AI and model choices',source+' Paid drafting has not been called. Whisper and base Qwen are pretrained. A team-trained LoRA adapts Qwen to a narrow factual task; no training from scratch is claimed.');
rows(s,[
'Team-trained model: a small text classifier trained on approved notes and customer transcript text to identify financial hardship.',
'Local models: Whisper transcribes audio. A team-trained Qwen LoRA selects cited case facts. Both run locally without paid API calls.',
'Optional paid API: an adapter is implemented, but needs user credentials and cost approval. It remains untested.',
'Controls: deterministic contact gates and employee review remain in place for every model approach.'
]);
s=slide('Current development evidence','Sources: reports/classifier_evaluation.json; reports/speech_evaluation_small_en_2000.json; reports/local_llm_evaluation.json; reports/benchmark_dev_evaluation.json; reports/decision_safeguards.json; tmp/final_tests.log. Metrics describe supplied development samples only.');
rows(s,[
`${checks.tests} automated checks pass. The proposal safeguard audit checks ${safeguards.samples} approved cases with ${safeguards.failed_cases} failures of tested constraints.`,
`All 12 numeric development benchmarks and ${semantics.passed} source-grounded policy/scope checks pass. Broad semantic accuracy remains unmeasured.`,
`Hardship, ${classifier.evaluation_rows} development examples: classifier 98.6% precision/recall. Live combination: 94.7% precision, 100% recall.`,
`Whisper small.en: ${(speech.aggregate_wer*100).toFixed(2)}% word error rate on ${speech.samples.length} approved synthetic recordings. Speaker review remains required.`,
`LoRA: ${trained.train_examples} training examples; ${finalTest.examples}/${finalTest.examples} final exact-value outputs. Narrow synthetic task.`
],26,91);
text(s,'Hidden-test results and preparation-time savings remain unmeasured.',76,650,1120,48,23,'#64717B');
s=slide('Possible grading dimensions',source+' These are discussion categories, not an official rubric or proposed point allocation. Organisers decide model eligibility, depth versus breadth and benchmark rules.');
rows(s,[
'Data correctness: matching quality, financial totals, quarantine, coverage and a reproducible C360 contract.',
'Question accuracy: benchmark tolerance, usable SQL or source evidence, policy applicability and correct refusals.',
'Model quality: separate training and evaluation, precision/recall, transcription error and factual draft quality.',
'Workflow quality: depth of the chosen use case, usability, response time and useful explanations.',
'Safeguards and reproducibility: consent, holds, privacy, employee control, executable code and honest limitations.'
],28,91);
text(s,'Organiser decisions: paid APIs, pretrained models, use-case breadth and scoring weights.',76,650,1120,50,23,'#64717B');
const candidate=staging+'/candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
const final=root+'/submission/5C2_rubric_brief_v9.pptx';
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,pythonExecutable:runtime+'/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],explicitTotalSlideCount:6,fontPolicy:{basis:'design',families:[family]},verifyArtifactToolImport:true,receiptPath:staging+'/validation.json'});
for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.items[i],format:'png',scale:2});await fs.writeFile(staging+`/slide-${i+1}.png`,new Uint8Array(await blob.arrayBuffer()));}
console.log(final);
