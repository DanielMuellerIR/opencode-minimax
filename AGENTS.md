# opencode-minimax — Projektfakten für Agenten

Einstiegspunkt für die Nutzung sind die READMEs ([README.md](README.md) /
[README.de.md](README.de.md)). Diese Datei hält nur, was für Agenten nicht direkt
aus dem Code/README ablesbar ist.

## Typ & Zweck
- **Typ:** CLI/Terminal-Tool (MiniMax-Delegation via OpenCode)
- **Zweck:** MiniMax als agentischen Coding-Assistenten über OpenCode nutzen — alltägliche Coding-Aufgaben an ein starkes, günstiges Modell delegieren.
- **Plattform:** CLI

## Tests

Die Regressionstests liegen in [tests/](tests) und brauchen keine Zusatzpakete:

```bash
python3 -m unittest discover          # Repo-Wurzel; findet tests/ als Paket
python3 tests/test_minimax_agent.py   # dieselbe Datei direkt aufgerufen
```

Kein Test ruft die MiniMax-API oder OpenCode auf; die Prozess- und Sandbox-Tests
starten nur kurze lokale Hilfsprozesse.

## Verzeichnisstruktur

<!-- directory-structure: generated -->
- [AGENTS.md](AGENTS.md) — Projektprofil, Arbeitsregeln und dieses Datei-Verzeichnis.
- [README.de.md](README.de.md) — Projekt-Einstieg und Nutzerdokumentation.
- [README.md](README.md) — Projekt-Einstieg und Nutzerdokumentation.
- [system-prompt.md](system-prompt.md) — Projektdokumentation.
- `examples/` — Projektbestandteil; Details stehen im Code bzw. in der verlinkten Dokumentation.
<!-- /directory-structure -->
