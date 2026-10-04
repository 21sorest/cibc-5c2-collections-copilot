"""Render the implemented software architecture as a standalone engineering diagram."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parent
image=Image.new('RGB',(1600,1100),'#f5f6f8')
draw=ImageDraw.Draw(image)
font_path=Path('C:/Windows/Fonts/segoeui.ttf')
def font(size):
    return ImageFont.truetype(str(font_path),size) if font_path.exists() else ImageFont.load_default(size=size)

draw.text((55,35),'Collections Copilot: implemented architecture',fill='#182634',font=font(38))
draw.text((55,92),'Team 5C2 · Synthetic release · Current snapshot 2026-09-28',fill='#526473',font=font(22))

def box(rect,title,lines,color='#ffffff'):
    x,y,x2,y2=rect
    draw.rounded_rectangle(rect,radius=14,fill=color,outline='#b9c3cb',width=2)
    draw.text((x+20,y+16),title,fill='#182634',font=font(25))
    for index,line in enumerate(lines):
        draw.text((x+20,y+60+index*31),line,fill='#425567',font=font(20))

def arrow(start,end):
    draw.line([start,end],fill='#647786',width=4)
    x,y=end
    if end[1]>start[1]:
        draw.polygon([(x,y),(x-8,y-13),(x+8,y-13)],fill='#647786')
    else:
        draw.polygon([(x,y),(x-13,y-8),(x-13,y+8)],fill='#647786')

box((55,150,1545,290),'Dataset and reference files',['31 raw tables · Policies · Notes and customer transcripts · Verified synthetic audio sample'])
arrow((400,290),(400,330))
arrow((1175,290),(1175,330))
box((55,330,750,500),'Data foundation',['DuckDB validation and deduplication','Five-system identity links and quarantine','Approved customer, account and call provenance'])
box((805,330,1545,500),'Questions and evidence',['Trusted parameterised SQL catalogue','Applicable policy sections and call evidence','Refusals and system-generated benchmark CSV'])
arrow((400,500),(400,545))
arrow((1175,500),(1175,740))
box((55,545,750,700),'Versioned case features and local NLP',['12 v0.5 features, source IDs and missingness','Shared rules + trained hardship classifier','Customer-separated factual LoRA experiment'])
arrow((400,700),(400,740))
box((55,740,1545,885),'Local Streamlit workspace and employee review',['Conversation help · Action / channel / agent proposals · Post-call signals and QA evidence','Qwen / LoRA / optional paid API select exact cited fields. Employee accepts / edits / rejects.'],'#fcebf1')
arrow((400,885),(400,930))
box((55,930,750,1045),'Review history',['Verify SQLite chain before append · Sources and versions'])
box((805,930,1545,1045),'Deployment boundary',['Local accounts available · Production identity pending'],'#fff2d8')
image.save(ROOT/'architecture.png')
print(ROOT/'architecture.png')
