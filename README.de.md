**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

MiniMax (oder ein beliebiges Anthropic-kompatibles Modell) als **agentischen Coder** über
[OpenCode](https://opencode.ai) betreiben — ein kleiner, ehrlicher Wrapper, der vier nicht
offensichtliche Stolperfallen löst. So lassen sich gut spezifizierte Coding-Aufgaben an ein
starkes, günstiges Modell delegieren, und das teure Frontier-Abo bleibt der Arbeit
vorbehalten, die es wirklich braucht.

## Wozu

Der teure Teil eines agentischen Workflows sind die Frontier-Abos (Claude, GPT). Ein
leistungsfähiges Modell mit großem Kontingent wie MiniMax kann einen erheblichen Teil der
gut spezifizierbaren Implementierungsarbeit übernehmen — Refactorings, mechanische
Änderungen, erste Entwürfe, Massenänderungen — zu einem Bruchteil der Kosten. Der Kniff ist,
es **agentisch** laufen zu lassen (das Modell liest Dateien, grept, editiert, verifiziert
sich selbst), nicht bloß als einmalige Text-Vervollständigung.

OpenCode unterstützt eigene Provider, im Prinzip zeigt man es also einfach auf MiniMax. In
der Praxis lassen vier Fallen es so aussehen, als könne „das Modell keine Dateien
schreiben", obwohl die Ursache im Harness liegt. Dieser Wrapper baut die Lösungen ein und
hält sich sonst zurück.

## Wie es funktioniert

`minimax_agent.py` erzeugt für einen Lauf eine **ephemere, isolierte OpenCode-Konfiguration**
und ruft `opencode run` auf. Den Rest macht das Modell: lesen, grep, editieren, Tests
ausführen, iterieren. Mehr nicht — kein Daemon, keine Abhängigkeit. Rund 200 Zeilen, die man
in einem Rutsch liest.

## Voraussetzungen

- [OpenCode](https://opencode.ai) im `PATH` (getestet mit 1.16–1.17.x).
- Python 3.8+ (nur Standardbibliothek).
- Ein MiniMax-API-Key (oder ein anderer Anthropic-kompatibler Endpunkt + Key).
- macOS für die eingebaute `--sandbox`-Einsperrung (seatbelt). Unter Linux läuft es ohne;
  siehe [Sicherheit](#sicherheit).

## Schnellstart

```bash
export MINIMAX_API_KEY=...        # oder --key-command (siehe unten)

# Read-only-Audit gegen einen wegwerfbaren git-Worktree (empfohlen für Reviews):
git worktree add -f /tmp/wt HEAD
python3 minimax_agent.py --dir /tmp/wt \
  "Prüfe dieses Repo auf echte Bugs. Nenne jeden mit Datei:Zeile und einem konkreten Fix."
git worktree remove --force /tmp/wt

# Schreib-Aufgabe, OS-seitig auf das Zielverzeichnis eingesperrt (macOS):
python3 minimax_agent.py --dir ./mein-projekt --sandbox \
  "Extrahiere den URL-Parser aus utils.py in eine neue url.py; Verhalten unverändert lassen."
```

Die Aufgabe kann auch über stdin kommen — praktisch für längere Briefings:

```bash
python3 minimax_agent.py --dir ./mein-projekt --sandbox < brief.txt
```

### Den Key aus der Shell-History heraushalten

Statt einer Umgebungsvariablen kann man dem Skript ein Kommando übergeben, das den Key
ausgibt:

```bash
# Beispiel macOS-Schlüsselbund:
python3 minimax_agent.py --dir ./mein-projekt \
  --key-command "security find-generic-password -s minimax-api-key -w" "..."
```

## Die vier Fallen (der eigentliche Wert hier)

Diese kosten echte Debugging-Zeit. Wer sich einen eigenen Wrapper baut, sollte sie kennen:

1. **Das Kontextfenster explizit deklarieren.** Für einen *eigenen* Provider zieht OpenCode
   keine Limits aus `models.dev`. Ohne `models.<name>.limit.context` nimmt es einen
   konservativen Default an und kompaktiert den Verlauf viel zu früh — das volle Fenster
   bekommt man nie zu sehen. Dieser Wrapper setzt es (Default `1000000`).
2. **OpenCodes State unter das System-Temp-Verzeichnis legen.** OpenCode hält seine
   SQLite-State-DB unter `~/.local/share/opencode`. Sperrt man das Schreiben auf das
   Arbeitsverzeichnis ein (Sandbox), wird dieser DB-Zugriff verweigert und OpenCode stürzt
   *sofort* ab (`PRAGMA wal_checkpoint`) — noch bevor das Modell läuft. Genau das ist das
   „MiniMax kann nicht schreiben"-Symptom. Die Lösung: jedem Lauf ein isoliertes `XDG_*`-Heim
   unter dem System-Temp geben, das die Sandbox stets freigibt.
3. **Die globale Konfiguration umgehen, um Plugin-Hänger zu vermeiden.** Eine globale
   `~/.config/opencode` kann ein `@latest`-Plugin laden, das bei jedem Start gegen npm
   revalidiert und OpenCode bei langsamem npm blockiert. Ein isoliertes `XDG_CONFIG_HOME`
   umgeht das komplett.
4. **Einen Start-Timeout mit Retry einbauen.** OpenCode hängt gelegentlich beim
   Session-Start (ein kleiner Titel-/Provider-Init-Call), während die API selbst gesund ist.
   Der Hänger liegt vor dem ersten Tool-Call, ein Neustart ist also gefahrlos. Dieser Wrapper
   setzt Timeout und Retry; jeder Versuch läuft in einer eigenen Prozessgruppe, damit auch
   Kindprozesse (bun) mitgekillt werden.

## Sicherheit

`opencode run` editiert Dateien unter `--dir` **ohne Rückfrage**. Zwei Schichten halten das
im Zaum:

- **Read-only-Arbeit** (Audits, Reviews, Analyse): gegen einen **wegwerfbaren git-Worktree**
  laufen lassen (`git worktree add -f <tmp> HEAD`). Etwaige Schreibversuche landen im Worktree
  und werden verworfen.
- **Schreib-Arbeit:** **`--sandbox`** übergeben (macOS). Der Lauf erfolgt unter `sandbox-exec`
  mit einem seatbelt-Profil, das Schreiben/Löschen nur unter `--dir` (plus System-Temp)
  erlaubt. Selbst ein Amok laufender Agent kann außerhalb des Ziels physisch nichts schreiben.
  Unter Linux gibt es noch keine eingebaute Einsperrung — mit `bubblewrap`/`firejail`
  umschließen oder zumindest `--dir` als eigenen, revertierbaren git-Worktree halten.

`--dir` niemals auf das Home-Verzeichnis oder einen breiten Pfad zeigen lassen.

## Vor dem Mergen prüfen

Ein günstiges Modell ist ein fähiger Junior, kein Orakel. Der Ablauf, der das sicher macht:

1. Aufgabe als präzises Briefing formulieren (Ziel, Dateien, Erfolgskriterium, Stil, was
   *nicht* anzufassen ist).
2. In einem isolierten Worktree ausführen.
3. **Das Diff lesen** (`git -C <dir> diff`) und Korrektheit, Umfang und Stil selbst prüfen.
4. Erst dann übernehmen (cherry-pick/merge). Maschinen-Output nie blind mergen.

## Beliebiger Anthropic-kompatibler Provider

Außer den Defaults ist hier nichts MiniMax-spezifisch. `--base-url` auf einen beliebigen
Anthropic-kompatiblen Endpunkt zeigen und `--model` entsprechend setzen; die genaue
Modell-ID und ob ein Bearer-Token erwartet wird, steht in der Doku des jeweiligen Providers.

## Grenzen & Haftungsausschluss

- **Das folgt OpenCodes Verhalten zu einem bestimmten Zeitpunkt** (1.16–1.17.x). OpenCode
  entwickelt sich schnell; eine Änderung am Config-Schema oder CLI kann einen der Workarounds
  brechen. Als funktionierendes Rezept verstehen, nicht als gepflegtes Produkt — und den Code
  lesen, bevor man sich darauf verlässt.
- **`--sandbox` ist macOS-only** (seatbelt). Keine eingebaute Linux-Einsperrung.
- **Rate-Limits sind opak.** Viele MiniMax-Tarife haben ein rollendes Fenster; wird es
  überschritten, kommt ein generischer Serverfehler statt eines Kontingent-Signals. Kurz
  warten und später erneut versuchen.
- **Keine Nutzungs-Telemetrie.** Agentische Läufe gehen über OpenCode, dieses Skript zählt
  also weder Tokens noch Kosten. Das Dashboard des Providers im Blick behalten.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
