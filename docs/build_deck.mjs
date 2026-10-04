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
const report=JSON.parse(await fs.readFile(root+'/reports/classifier_evaluation.json','utf8'));
const local=JSON.parse(await fs.readFile(root+'/reports/local_llm_evaluation.json','utf8'));
const speech=JSON.parse(await fs.readFile(root+'/reports/speech_evaluation_small_en_2000.json','utf8'));
const trained=JSON.parse(await fs.readFile(root+'/reports/llm_training.json','utf8'));
const finalTest=JSON.parse(await fs.readFile(root+'/reports/llm_adapter_test.json','utf8'));
const checks=JSON.parse(await fs.readFile(root+'/reports/implementation_checks.json','utf8'));
const semantics=JSON.parse(await fs.readFile(root+'/reports/question_semantics.json','utf8'));
const p=Presentation.create({slideSize:{width:1280,height:720}});
const staging=root+'/tmp/deck_v7';
await fs.mkdir(staging,{recursive:true});
await fs.mkdir(root+'/submission',{recursive:true});
function text(slide,value,left,top,width,height,size=30,color='#253746',bold=false){
 const shape=slide.shapes.add({geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
 shape.text=value;shape.text.style={typeface:family,fontSize:size,color,bold,autoFit:'none'};return shape;
}
function slide(title,notes){const s=p.slides.add();s.background.fill='#FAFAF8';text(s,title,72,50,1136,85,44,'#8C183A',true);s.speakerNotes.textFrame.setText(notes);return s;}
function paragraphs(s,values){values.forEach((value,i)=>text(s,value,76,170+i*112,1120,100,30));}
let s=slide('Collections Copilot','Team 5C2. All dataset facts refer to the fully synthetic Maple Bank release dated 2026-09-28. Sources: Build Phase/CIBC Hackathon Build Phase - Instructions.pdf; README.md. Draft for team review before final submission.');
text(s,'Evidence-backed assistance for collections employees',76,230,1050,150,50,'#253746',true);
text(s,'Team 5C2 | CIBC Hackathon Build Phase',76,490,1050,60,28);
text(s,'Local classifier and language generation | Employee review',76,560,1080,80,26);
s=slide('The employee workflow','Business framing from System Design Phase/5C2_SystemDesign.pdf. Preparation-time improvement is an intended measurement, not a result.');
paragraphs(s,['Find a trustworthy customer view across five source systems before discussing the case.','Identify financial hardship and disputes during the conversation, then retrieve the applicable policy.','Review a suggested response, record the employee decision, and preserve the evidence.','Measure preparation time against manual lookup. The original 30% improvement target remains unmeasured.']);
s=slide('Data foundation and coverage','Measured results: reports/quality_summary.json, reports/data_quality.md, reports/features_summary.json, reports/c360_export.json. Contract: contracts/c360.json. Counts describe accepted coverage, not all raw records.');
text(s,'1,011,944',76,175,500,70,60,'#8C183A',true);text(s,'accepted golden customers',76,260,1000,60,30);
text(s,'1,142,071 matched accounts | 338,295 served cases',76,355,1100,70,34);
text(s,'13 foundation checks cover keys, customer ownership, transcript links, amounts and contract schema. Contradictory records are quarantined.',76,460,1100,125,30);
text(s,'C360 export: 8.3 MB Parquet, with checksum and explicit coverage.',76,610,1100,60,25);
s=slide('Four connected layers','Implemented modules: pipeline.py, sql/foundation.sql, questions.py, features.py, sql/features.sql, conversation.py, decisions.py, calls.py, assistant.py. Architecture PNG is available separately in docs/architecture.png.');
paragraphs(s,['1  Data product: raw sources, validated identities, curated records and golden C360.','2  Insight: supported questions run trusted SQL or retrieve current policy sources; unsupported requests are refused.','3  Features: 12 versioned case features, shared text extraction and the same classifier tokenizer for training and inference.','4  Assistance: conversation help and decision proposals, followed by employee accept, edit or reject.']);
s=slide('Assistance during a conversation','Working flow implemented in app.py and conversation.py. This is an illustrative input used in UI validation, not a quote from a real customer. Policy evidence comes from synthetic POL-COLL-004 v4.2 and POL-COLL-001 v3.0.');
text(s,'Illustrative customer statement',76,175,1100,50,26,'#64717B');
text(s,'“I lost my job and cannot afford this payment.”',76,245,1090,110,40,'#253746',true);
text(s,'Acknowledge the hardship. Review support options and affordability before requesting a payment.',76,395,1090,115,33);
text(s,'Identity verification precedes disclosure. Policy sources and detected signals accompany the draft. Employee review records no automatic action.',76,545,1090,100,27);
s=slide('Locally trained hardship detection','Source: reports/classifier_evaluation.json. CPU word/bigram naive Bayes, customer/text/token-connected development split. Excludes 25 protected-content-labeled examples and 116 unapproved sources. Rules were previously assessed on public labels, so this is not a blind comparison. Rare-class models performed worse and do not replace rules.');
const chart=s.charts.add('bar',{position:{left:76,top:185,width:1100,height:345},categories:['Precision','Recall'],series:[{name:'Trained classifier',values:[Number((report.trained.hardship.precision*100).toFixed(1)),Number((report.trained.hardship.recall*100).toFixed(1))],fill:'#8C183A'},{name:'Existing rules',values:[Number((report.rules_baseline.hardship.precision*100).toFixed(1)),Number((report.rules_baseline.hardship.recall*100).toFixed(1))],fill:'#287B82'}],barOptions:{direction:'column',grouping:'clustered'},hasLegend:true,dataLabels:{showValue:true,position:'outEnd'}});
applyPresentationChartFont(chart,{fontFamily:family});
text(s,`${report.training_rows} training examples | ${report.evaluation_rows} development evaluation examples`,76,565,1110,60,28);
text(s,`Live combination: ${(report.live_review_signals.hardship.precision*100).toFixed(1)}% precision, 100% recall. Public development data only; all flags require review.`,76,630,1110,65,24);
s=slide('A locally fine-tuned language model','Sources: reports/llm_training.json; reports/llm_adapter_dev.json; reports/llm_adapter_test.json; reports/llm_base_dev.json. Deterministic factual-format supervision of an existing pretrained model, not training from scratch or proof of conversational intelligence. Exact values are validated before application-rendered sentences.');
paragraphs(s,[`Qwen2.5-0.5B-Instruct adapted locally with LoRA on an RTX 4060. ${trained.trainable_parameters.toLocaleString()} trainable adapter parameters.`,`${trained.train_examples} factual training examples. Customers remain separate across training, development and final testing.`,`Final factual-format checks: ${finalTest.examples} outputs across ${finalTest.unique_cases} cases, including missing values and unsafe instruction challenges.`,`Complete exact-value output: ${(finalTest.complete_rate*100).toFixed(1)}%. Contact permission and recommended actions still come from deterministic rules.`]);
s=slide('Additional reviewed use cases','Source: decisions.py, calls.py, reports/qa_evaluation.json. All are prototype proposals or evidence triage, not production optimization or automated compliance judgments. This covers the six Layer 4 choices in System Design Phase/CIBC Collections Hackathon Problem Statement-3.pdf.');
paragraphs(s,['Next Best Action explains safeguards, alternatives, programme checks and policy conflicts.','Channels show uncertainty and capacity limits. Routing checks skills, French site, support certification and load.','Structured call notes separate customer proposals, explicit commitments, issue mentions and follow-ups with timestamps.','All ten QA items show context and uncertainty. Employees record per-item evidence; no automatic compliance verdict is issued.']);
s=slide('Measured checks and remaining work','Sources: unit tests, reports/benchmark_dev_evaluation.json, reports/speech_evaluation_small_en_2000.json, reports/local_llm_evaluation.json. No paid API requests were made. Local Qwen is pretrained, separate from the team-trained classifier. No hidden benchmark, semantic summary accuracy or business-time improvement claim is made.');
paragraphs(s,[`${checks.tests} automated checks pass, including the local UI. Public numeric benchmarks pass; ${semantics.passed} policy/scope acceptance checks pass.`,`Whisper small.en: ${(speech.aggregate_wer*100).toFixed(2)}% word error rate on ${speech.samples.length} approved synthetic recordings. Speaker attribution still requires review.`,`CPU Qwen drafts: ${local.validation_passed}/${local.samples} passed typed exact-value checks. Median latency ${local.median_latency_seconds.toFixed(1)} seconds; summary usefulness requires employee review.`,'Next: incorporate the final rubric and extra questions, connect the private repository, publish the C360 link, and record the demo.']);
const candidate=staging+'/candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
const final=root+'/submission/5C2_pitch_draft_v7.pptx';
await finalizePresentation({workspaceDir:root,candidatePath:candidate,finalPath:final,pythonExecutable:runtime+'/python/python.exe',integrityValidatorPath:skill+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:skill+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],explicitTotalSlideCount:9,requiredNativeChartOwnerSlides:[6],fontPolicy:{basis:'design',families:[family]},materializeLiteralChartWorkbooks:true,verifyArtifactToolImport:true,receiptPath:staging+'/validation.json'});
for(let i=0;i<p.slides.items.length;i++){const blob=await p.export({slide:p.slides.items[i],format:'png',scale:2});await fs.writeFile(staging+`/slide-${i+1}.png`,new Uint8Array(await blob.arrayBuffer()));}
console.log(final);

