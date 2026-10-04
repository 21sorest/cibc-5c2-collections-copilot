"""Export reviewed slide renders to a standalone nine-page pitch PDF."""
from pathlib import Path
try:
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader
except ModuleNotFoundError:
    import subprocess
    import sys
    runtime=Path('C:/Users/desai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
    if Path(sys.executable).resolve()==runtime.resolve():
        raise
    raise SystemExit(subprocess.call([str(runtime),str(Path(__file__).resolve())]))

root=Path(__file__).resolve().parents[1]
output=root/'submission/5C2_pitch_draft_v7.pdf'
pdf=canvas.Canvas(str(output),pagesize=(960,540))
pdf.setTitle('Team 5C2 Collections Copilot: build phase pitch draft')
pdf.setAuthor('Team 5C2')
for index in range(1,10):
    pdf.drawImage(str(root/f'tmp/deck_v7/slide-{index}.png'),0,0,width=960,height=540)
    pdf.showPage()
pdf.save()
assert len(PdfReader(output).pages)==9
print(output)
