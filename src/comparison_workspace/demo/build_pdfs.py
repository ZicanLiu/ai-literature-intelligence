"""Developer-only fixture authoring. Requires reportlab; ships only synthetic sources."""
from pathlib import Path
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .content import PAPERS, statements


def build():
    directory = Path(__file__).parent / "fixtures"
    directory.mkdir(exist_ok=True)
    for paper in PAPERS:
        target = directory / f"paper_{paper['letter']}.pdf"
        c = canvas.Canvas(str(target), pagesize=A4, invariant=True)
        c.setTitle(paper["title"] + " / SYNTHETIC DEMO")
        width, height = A4
        def frame(number):
            c.setFillColor(HexColor("#edf3fd"))
            c.rect(0, height - 100, width, 100, fill=1, stroke=0)
            c.setFillColor(HexColor("#2456a7"))
            c.setFont("Helvetica-Bold", 12)
            c.drawString(46, height - 40, "SYNTHETIC DEMO")
            c.setFont("Helvetica", 11)
            c.drawString(46, height - 60, "NOT RESEARCH EVIDENCE")
            c.setFillColor(HexColor("#516078"))
            c.setFont("Helvetica", 9)
            c.drawString(46, 30, f"SRTP Comparison Workspace | synthetic fixture | page {number} / 2")
        frame(1)
        c.setFillColor(HexColor("#152c4b"))
        c.setFont("Helvetica-Bold", 23)
        c.drawString(46, height - 155, f"Paper {paper['letter']}")
        c.setFont("Helvetica-Bold", 16)
        c.drawString(46, height - 186, paper["title"].split(":")[0])
        c.setFont("Helvetica", 12)
        c.drawString(46, height - 215, paper["title"].split(":")[1].strip())
        lines = [
            "Synthetic Demo Authors",
            "",
            "Purpose",
            "This document is invented solely to demonstrate a local comparison workflow.",
            "Its datasets, methods, numbers and conclusions are not research evidence.",
            "No scientific gold label or benchmark is defined by this fixture.",
            "",
            "Question-dependent review",
            "Reported numbers can be inspected with experimental context.",
            "A split difference matters when a question requires the same protocol.",
            "Missing resource information does not justify an efficiency claim.",
        ]
        text = c.beginText(46, height - 262)
        text.setFont("Helvetica", 10)
        text.setLeading(21)
        for line in lines:
            text.textLine(line)
        c.drawText(text)
        c.showPage()
        frame(2)
        c.setFillColor(HexColor("#152c4b"))
        c.setFont("Helvetica-Bold", 18)
        c.drawString(46, height - 146, "Experimental conditions and results")
        text = c.beginText(46, height - 190)
        text.setFont("Helvetica", 10)
        text.setLeading(27)
        for line in statements(paper).values():
            if line:
                text.textLine(line)
        text.textLine("")
        text.textLine(statements(paper, True)["result"])
        text.textLine("")
        text.textLine("Every number on this page is synthetic.")
        c.drawText(text)
        c.save()


if __name__ == "__main__":
    build()
