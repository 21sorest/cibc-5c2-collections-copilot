# Case workspace design

A collections review workspace, designed for recorded demonstration and evidence inspection.

The first pass used a large serif title, a rose accent and four repeated metric cards. The user rejected that pass. The revised layout spends space on the case and evidence instead.

- Charcoal canvas #14161b, inset surface #1c1f26, rules #30333b, text #f0f0ef and warm gold #c6a577.
- Segoe UI with a local sans-serif fallback. Tabular financial numbers, a dominant overdue amount and quieter operational context.
- A compact app bar; case ID/status; one financial summary band; native workflow tabs; accounts and promises beside each other; contacts below.
- Sidebar controls separate case selection from optional review settings. The snapshot simulation and employee-review restrictions stay visible.
- No invented charts, portfolio imagery, remote fonts, decorative motion or framework migration. Native Streamlit forms, tables and keyboard interaction remain intact.

References inspected: https://ui-design-bench.vercel.app/ and https://github.com/Leonxlnx/taste-skill/blob/main/skills/redesign-skill/SKILL.md. The gallery's landing-page compositions informed restraint and hierarchy; they were not copied as a dashboard template. Skill text was read as guidance, with no third-party executable installation.

Verification: existing dataset-backed test_ui checks passed, and the dashboard and conversation form were inspected through the browser. Presentation styling is in ui.css; native dark-theme tokens are in .streamlit/config.toml.
