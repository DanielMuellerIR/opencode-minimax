**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

MiniMax als **agentischen Coding-Assistenten** über [OpenCode](https://opencode.ai) nutzen —
alltägliche Coding-Aufgaben an ein starkes, günstiges Modell delegieren und das teure
Frontier-Abo für die Arbeit aufheben, die es wirklich braucht.

Du zeigst es auf einen Ordner und beschreibst eine Aufgabe in normaler Sprache („fixe den
fehlschlagenden Test", „lagere das in eine eigene Datei aus"). Das Modell liest deine
Dateien, macht die Änderung und prüft sein eigenes Ergebnis. Du siehst dir das Resultat an
und behältst es oder verwirfst es.

## Einrichten

Du brauchst drei Dinge:

1. **OpenCode** — von [opencode.ai](https://opencode.ai) installieren und prüfen, dass es
   läuft:
   ```bash
   opencode --version
   ```
2. **Python 3.8+** (nur Standardbibliothek — nichts zu installieren).
3. **Einen MiniMax-API-Key** — auf der [MiniMax](https://www.minimax.io)-Plattform erstellen
   und im Terminal verfügbar machen:
   ```bash
   export MINIMAX_API_KEY=dein-key-hier
   ```
   (Diese Zeile ins Shell-Profil aufnehmen, damit sie bestehen bleibt. Man kann den Key auch
   aus einem Passwort-Manager lesen — siehe **Den Key sicher halten** in den einklappbaren
   Abschnitten weiter unten.)

Dann dieses Repository holen:

```bash
git clone https://github.com/DanielMuellerIR/opencode-minimax.git
cd opencode-minimax
```

## Ausprobieren (etwa eine Minute)

Eine fertige Demo fixt für dich eine absichtlich kaputte Funktion — in einer Wegwerf-Kopie,
deine eigenen Dateien werden nie angefasst:

```bash
export MINIMAX_API_KEY=dein-key-hier
examples/run-demo.sh
```

Was du siehst (echte Ausgabe, leicht gekürzt):

```console
$ python3 test_calc.py
FAIL: ZeroDivisionError: division by zero

$ minimax_agent.py --dir ./demo --sandbox \
    "Fix average(): return 0.0 on empty input instead of raising. Keep it minimal."
-> MiniMax agentic: model MiniMax-M3, dir ./demo [sandboxed]
→ Read calc.py
→ Read test_calc.py
← Edit calc.py
$ python3 test_calc.py         # das Modell verifiziert seinen eigenen Fix
OK

$ git diff
 def average(numbers):
     # Return the mean of a list of numbers.
+    if not numbers:
+        return 0.0
     return sum(numbers) / len(numbers)
```

Roter Test → Aufgabe in Worten → kleine, korrekte Änderung → grün. Das ist die ganze Idee.

## Am eigenen Code nutzen

Zwei sichere Muster, beide lauffähig in [`examples/`](examples):

```bash
# 1) Um ein Review bitten, OHNE etwas zu ändern (läuft gegen eine Wegwerf-Kopie):
examples/review-repo.sh /pfad/zu/deinem/repo

# 2) Um einen Fix bitten, eingesperrt in eine Wegwerf-Kopie, die du vor dem Übernehmen prüfst:
examples/fix-in-sandbox.sh /pfad/zu/deinem/repo "Fixe den Absturz bei leerer Eingabeliste."
```

Oder das Tool direkt aufrufen:

```bash
minimax_agent.py --dir ./mein-projekt --sandbox "Füge cli.py eine --verbose-Option hinzu."
```

Das Wichtigste für gute Delegation ist eine **klare Aufgabenbeschreibung** — Ziel, wo zu
suchen ist, woran man „fertig" erkennt und was nicht angefasst werden darf. Die fertigen
[Aufgaben-Vorlagen](examples/briefs) zeigen die Form eines guten Auftrags. Eine davon kann man
hineinpipen:

```bash
minimax_agent.py --dir ./mein-projekt --sandbox < examples/briefs/fix-failing-test.md
```

## Sicher bleiben

Der Assistent editiert selbstständig Dateien, also sperr ihn ein — die Beispiele oben tun das
bereits für dich:

- **Reviews** laufen gegen eine **Wegwerf-Kopie** deines Repos, sodass nichts deine Arbeit
  verändern kann.
- **Fixes** laufen mit `--sandbox` (macOS): das hindert den Assistenten daran, außerhalb des
  Zielordners zu schreiben — auch versehentlich nicht.
- **Sieh dir die Änderung an, bevor du sie behältst** (`git diff`). Behandle den Assistenten
  als schnellen, fähigen Helfer, dessen Arbeit du prüfst — nicht als Orakel.
- `--dir` niemals auf dein Home-Verzeichnis oder einen breiten Pfad zeigen lassen.

<details>
<summary><b>Unter der Haube — die vier Einrichtungs-Fallen, die das löst</b> (optional; zum
Benutzen nicht nötig)</summary>

<br>

OpenCode unterstützt eigene Provider, im Prinzip zeigt man es also einfach auf MiniMax. In der
Praxis lassen vier nicht offensichtliche Dinge es so aussehen, als könne „das Modell keine
Dateien schreiben", obwohl die Ursache in der Einrichtung liegt. `minimax_agent.py` erledigt
alle vier für dich:

1. **Das Kontextfenster explizit deklarieren.** Für einen *eigenen* Provider zieht OpenCode
   keine Limits aus `models.dev`. Ohne `models.<name>.limit.context` nimmt es einen
   konservativen Default an und kürzt den Verlauf viel zu früh — das volle Fenster bekommt man
   nie zu sehen. Der Wrapper setzt es (Default `1000000`).
2. **OpenCodes State unter das System-Temp-Verzeichnis legen.** OpenCode hält seine
   SQLite-State-DB unter `~/.local/share/opencode`. Sperrt man das Schreiben auf das
   Arbeitsverzeichnis ein (die Sandbox), wird dieser DB-Zugriff verweigert und OpenCode
   stürzt *sofort* ab (`PRAGMA wal_checkpoint`) — noch bevor das Modell läuft. Genau das ist
   das „MiniMax kann nicht schreiben"-Symptom. Die Lösung: jedem Lauf ein isoliertes
   `XDG_*`-Heim unter dem System-Temp geben, das die Sandbox stets freigibt.
3. **Die globale Konfiguration umgehen, um Plugin-Hänger zu vermeiden.** Eine globale
   `~/.config/opencode` kann ein `@latest`-Plugin laden, das bei jedem Start gegen npm
   revalidiert und OpenCode bei langsamem npm blockiert. Ein isoliertes `XDG_CONFIG_HOME`
   umgeht das komplett.
4. **Einen Start-Timeout mit Retry einbauen.** OpenCode hängt gelegentlich beim Session-Start
   (ein kleiner Titel-/Provider-Init-Call), während die API selbst gesund ist. Der Hänger
   liegt vor dem ersten Tool-Call, ein Neustart ist also gefahrlos. Der Wrapper setzt Timeout
   und Retry; jeder Versuch läuft in einer eigenen Prozessgruppe, damit auch Kindprozesse
   aufgeräumt werden.

Das Ganze sind rund 200 Zeilen Python, die man in einem Rutsch liest.

</details>

<details>
<summary><b>Den Key sicher halten</b> und andere Provider nutzen</summary>

<br>

**Den Key sicher halten.** Statt einer Umgebungsvariablen kann man dem Tool ein Kommando
übergeben, das den Key ausgibt — so landet das Geheimnis nie in der Shell-History:

```bash
# Beispiel macOS-Schlüsselbund:
minimax_agent.py --dir ./mein-projekt \
  --key-command "security find-generic-password -s minimax-api-key -w" "..."
```

**Andere Provider.** Außer den Defaults ist hier nichts MiniMax-spezifisch. `--base-url` auf
einen beliebigen Anthropic-kompatiblen Endpunkt zeigen und `--model` entsprechend setzen; die
genaue Modell-ID steht in der Doku des jeweiligen Providers.

</details>

## Gut zu wissen

- Gebaut und getestet auf **macOS** mit **OpenCode 1.16–1.17.x**. Die `--sandbox`-Einsperrung
  ist macOS-only; unter Linux den Assistenten gegen einen wegwerfbaren git-Worktree laufen
  lassen, den man revertieren kann (das tun die Beispiele), oder mit `bubblewrap`/`firejail`
  umschließen.
- OpenCode entwickelt sich schnell. Als **funktionierendes Rezept** verstehen, nicht als
  gepflegtes Produkt — ändert eine künftige OpenCode-Version das Verhalten, das kurze Skript
  lesen und anpassen.
- Viele MiniMax-Tarife haben ein **rollendes Nutzungsfenster**; wird es überschritten, kommt
  ein generischer Serverfehler statt einer klaren Kontingent-Meldung. Kurz warten und erneut
  versuchen.

## Lizenz

MIT — siehe [LICENSE](LICENSE).
