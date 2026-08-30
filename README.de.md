**🌐 Sprache / Language:** [English](README.md) · [Deutsch](README.de.md)

# opencode-minimax

MiniMax als **agentischen Coding-Assistenten** über [OpenCode](https://opencode.ai) nutzen —
alltägliche Coding-Aufgaben an ein starkes, günstiges Modell delegieren und das teure
Frontier-Abo für die Arbeit aufheben, die es wirklich braucht.

Du zeigst es auf einen Ordner und beschreibst eine Aufgabe in normaler Sprache („fixe den
fehlschlagenden Test", „lagere das in eine eigene Datei aus"). Das Modell liest deine
Dateien, macht die Änderung und prüft sein eigenes Ergebnis. Du siehst dir das Resultat an
und behältst es oder verwirfst es.

## TL;DR

1. [OpenCode](https://opencode.ai) installieren und einen MiniMax-API-Key holen — ein
   **Token-Plan**-Abo (der **Plus**-Plan für ~20 US$ enthält bereits ~1,7 Mrd. Tokens).
2. **Key einmal ablegen** im macOS-Schlüsselbund (verschlüsselte dauerhafte Ablage; Hinweis
   zur temporären Laufzeitdatei weiter unten):
   ```bash
   security add-generic-password -a "$USER" -s minimax-api-key -U -w   # Key einfügen; Eingabe bleibt verborgen
   ```
3. Dieses Repo klonen und zusehen, wie es einen Bug für dich fixt:
   ```bash
   examples/run-demo.sh
   ```
4. Auf deinen eigenen Code loslassen — es editiert eine Wegwerf-Kopie, die du vor dem Behalten prüfst:
   ```bash
   examples/fix-in-sandbox.sh /pfad/zu/deinem/repo "Fixe den Absturz bei leerer Eingabe."
   ```

Alles Weitere erklärt nur diese Schritte, sichereren Gebrauch und wie du es freihändig aus
deinem KI-Assistenten steuerst. Nicht auf macOS? Der [Einrichten](#einrichten)-Abschnitt
beschreibt den Weg über die Umgebungsvariable.

## Einrichten

Du brauchst drei Dinge:

1. **OpenCode** — von [opencode.ai](https://opencode.ai) installieren und prüfen, dass es
   läuft:
   ```bash
   opencode --version
   ```
2. **Python 3.8+** (nur Standardbibliothek — nichts zu installieren).
3. **Einen MiniMax-API-Key aus einem Token Plan.** Am günstigsten nutzt man MiniMax über ein
   **Token-Plan**-Abo — ein großes monatliches Token-Kontingent statt nutzungsabhängiger
   Abrechnung. Der **Plus**-Plan (zum jetzigen Stand rund 20 US$/Monat) enthält bereits
   ~1,7 Milliarden Tokens, was für delegierte Coding-Arbeit weit reicht. Auf der
   [MiniMax-Plattform](https://www.minimax.io) einen Plan wählen, dann aus dem Abo einen
   API-Key generieren.

   **Sicher ablegen (empfohlen, macOS).** Die dauerhafte Kopie im Schlüsselbund halten —
   dort bleibt sie verschlüsselt und aus deiner Shell-History heraus:
   ```bash
   # Fragt nach dem Key; einfügen — die Eingabe bleibt verborgen; -U aktualisiert auch einen alten Eintrag.
   security add-generic-password -a "$USER" -s minimax-api-key -U -w
   ```
   Das war's — das Tool und die Beispielskripte lesen den Key automatisch aus dem Schlüsselbund.

   **Exposition während des Laufs:** OpenCode benötigt das Credential in seiner erzeugten
   Konfiguration. Der Wrapper schreibt es deshalb für jeden Lauf im Klartext in eine
   `config.json` mit Modus `0600`, innerhalb eines privaten System-Temp-Verzeichnisses mit
   Modus `0700` und Namen `opencode-minimax-*`. Bei normalem Ende wird dieses Verzeichnis
   gelöscht, ebenso bei einem Abbruch mit Strg-C, `SIGTERM` oder `SIGHUP`.
   Ein harter Abbruch, `SIGKILL` oder Stromausfall kann die temporäre Kopie zurücklassen;
   nach einem solchen Abbruch das System-Temp-Verzeichnis prüfen und verwaiste
   `opencode-minimax-*`-Verzeichnisse entfernen.

   **Oder schnell:** stattdessen eine Umgebungsvariable für das aktuelle Terminal setzen:
   ```bash
   # Temporär — nur für dieses Terminal-Fenster. Für dauerhaft in ~/.zshrc eintragen (Klartext-Datei).
   export MINIMAX_API_KEY=dein-key-hier
   ```

Dann dieses Repository holen:

```bash
git clone https://github.com/DanielMuellerIR/opencode-minimax.git
cd opencode-minimax
```

## Ausprobieren (etwa eine Minute)

Eine fertige Demo fixt für dich eine absichtlich kaputte Funktion — in einer Wegwerf-Kopie,
deine eigenen Dateien werden nie angefasst:

```bash
examples/run-demo.sh
```

Was du siehst (echte Ausgabe, leicht gekürzt):

```console
$ python3 test_calc.py
FAIL: ZeroDivisionError: division by zero

$ python3 ./minimax_agent.py --dir ./demo --sandbox \
    "Fix average(): return 0.0 on empty input instead of raising. Keep it minimal."
-> MiniMax agentic: model MiniMax-M3, dir ./demo [sandboxed]
→ Read calc.py
→ Read test_calc.py
← Edit calc.py
$ python3 test_calc.py         # das Modell verifiziert seinen eigenen Fix
OK

$ examples/_show-worktree-changes.py ...
 def average(numbers):
     # Return the mean of a list of numbers.
+    if not numbers:
+        return 0.0
     return sum(numbers) / len(numbers)

Nach der Prüfung den Test jetzt ausführen? [y/N] y
OK
```

Roter Test → Aufgabe in Worten → vollständige Prüfung mit gesperrter Git-Konfiguration →
erst danach den erzeugten Code ausführen. Das äußere Demo-Skript importiert agentengeschriebenes
Python erst, wenn du bestätigst, dass du die angezeigte Änderung geprüft hast.

## Am eigenen Code nutzen

Zwei sichere Muster, beide lauffähig in [`examples/`](examples):

```bash
# 1) Um ein Review bitten, OHNE etwas zu ändern (läuft gegen eine Wegwerf-Kopie):
examples/review-repo.sh /pfad/zu/deinem/repo

# 2) Um einen Fix bitten, eingesperrt in eine Wegwerf-Kopie, die du vor dem Übernehmen prüfst:
examples/fix-in-sandbox.sh /pfad/zu/deinem/repo "Fixe den Absturz bei leerer Eingabeliste."
```

Beide Beispielskripte wählen die passende Einsperrung für dein System: auf macOS ergänzen sie
`--sandbox`, sonst läuft dieselbe Aufgabe ohne (siehe [Gut zu wissen](#gut-zu-wissen)).
Sie kopieren den committeten Stand `HEAD`, keine uncommitteten Änderungen, und brechen bei
einem schmutzigen Quell-Repo mit einer klaren Meldung ab. Committe vorher genau den Stand, den
du prüfen oder ändern lassen willst.

Oder das Tool direkt aufrufen:

```bash
# --sandbox gibt es nur auf macOS; auf anderen Systemen weglassen und in einer Wegwerf-Kopie arbeiten.
python3 ./minimax_agent.py --dir ./mein-projekt --sandbox "Füge cli.py eine --verbose-Option hinzu."
```

Das Wichtigste für gute Delegation ist eine **klare Aufgabenbeschreibung** — Ziel, wo zu
suchen ist, woran man „fertig" erkennt und was nicht angefasst werden darf. Die fertigen
[Aufgaben-Vorlagen](examples/briefs) zeigen die Form eines guten Auftrags. Eine davon kann man
hineinpipen:

```bash
python3 ./minimax_agent.py --dir ./mein-projekt --sandbox < examples/briefs/fix-failing-test.md
```

## Der bequeme Weg: aus deinem KI-Assistenten heraus

Am angenehmsten nutzt man das, indem man den Befehl gar nicht selbst tippt, sondern den
eigenen KI-Coding-Assistenten machen lässt. Kann dein Assistent Shell-Befehle ausführen —
Claude Code, Claude Desktop mit Dateizugriff, Cursor, Codex und Ähnliches — dann übernimmt dein
starkes Planungsmodell das Denken und die Orchestrierung und reicht die Routine-Implementierung
über dieses Tool an MiniMax weiter. Du beschreibst nur in normaler Sprache, was du willst:

> „Implementiere den CSV-Export in `exporter.py`. Delegier die Implementierung an MiniMax und
> zeig mir dann den Diff."

Die kanonische, fertig einfügbare Anweisung liegt in
[`examples/assistant-instructions.md`](examples/assistant-instructions.md). Füge diesen Text in
`CLAUDE.md`, `AGENTS.md`, einen System-Prompt oder ein Custom-Instructions-Feld deines
Assistenten ein und passe den Pfad an. Eine kanonische Kopie verhindert, dass drei Varianten
auseinanderlaufen. Danach genügt „mach X und delegier die Implementierung an MiniMax" — dein
Assistent ruft das Tool auf, prüft den Diff und meldet zurück.

## Sicher bleiben

Der Assistent editiert selbstständig Dateien, also sperr ihn ein — die Beispiele oben tun das
bereits für dich:

- **Reviews** laufen gegen eine **Wegwerf-Kopie** deines Repos, dein Arbeitsstand ist also
  aus dem Weg. Auf macOS läuft das Review zusätzlich in der Sandbox — erst die verhindert
  wirklich einen Schreibzugriff auf den Original-Checkout, mit dem sich der Wegwerf-Worktree
  sein Git-Verzeichnis teilt. Dieses gemeinsame Git-Verzeichnis bleibt in der Sandbox
  schreibgeschützt; `git add` und `git commit` scheitern dort absichtlich. Der mitgelieferte
  Review-Auftrag liest und berichtet nur.
- **Fixes** laufen mit `--sandbox` (macOS): das hindert den Assistenten daran, außerhalb des
  Zielordners zu schreiben — auch versehentlich nicht. Beschreibbar ist sonst nur das eigene
  Temp-Verzeichnis des Laufs, das am Ende gelöscht wird; die Temp- und Cache-Dateien deiner
  anderen Programme bleiben tabu.
- **Prüfe die vollständige Änderung, bevor du sie behältst oder ausführst.** Fix- und
  Demo-Skript vergleichen alle getrackten Dateien mit dem vor dem Lauf erfassten Basisstand,
  deaktivieren externe Diffs und Textkonvertierung, ignorieren die beschreibbare `.git`-Datei
  des Worktrees und listen ungetrackte Dateien in einem maschinenlesbaren Statusblock.
  Behandle den Assistenten als schnellen, fähigen Helfer, dessen Arbeit du prüfst — nicht als
  Orakel.
- `--dir` niemals auf dein Home-Verzeichnis oder einen breiten Pfad zeigen lassen.
- `--sandbox` begrenzt **Schreibzugriffe**, nicht Lesezugriffe, Netzverbindungen oder Secrets.
  OpenCode erbt die Umgebung des Aufrufers, damit delegierte Builds ihre Toolchains, Proxys und
  Credentials finden. Starte den Wrapper nur mit Umgebungsvariablen, die der delegierte Auftrag
  lesen darf; das Modell kann außerdem alle für das aktuelle Konto lesbaren Dateien lesen.

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
   `XDG_*`-Heim unter dem System-Temp geben und in der Sandbox genau dieses Verzeichnis
   (plus `--dir`) zum Schreiben freigeben. `TMPDIR` zeigt ebenfalls dorthin, damit Werkzeuge,
   die `TMPDIR` beachten, Platz für Zwischendateien haben. macOS-APIs, die direkt
   `DARWIN_USER_TEMP_DIR` oder `DARWIN_USER_CACHE_DIR` verwenden, bleiben in der Sandbox
   schreibgeschützt; eine Freigabe dieser gemeinsamen Verzeichnisse ließe den Agenten auch
   Temp- und Cache-Dateien anderer Prozesse verändern.
3. **Die globale Konfiguration umgehen, um Plugin-Hänger zu vermeiden.** Eine globale
   `~/.config/opencode` kann ein `@latest`-Plugin laden, das bei jedem Start gegen npm
   revalidiert und OpenCode bei langsamem npm blockiert. Ein isoliertes `XDG_CONFIG_HOME`
   umgeht das komplett.
4. **Stille begrenzen, ohne Arbeitsbeginn zu erraten.** Der Wrapper zählt Ausgabestille,
   nicht die Gesamtlaufzeit: Solange ein Lauf etwas ausgibt, wird er nicht abgeschnitten.
   Auch ein stiller Versuch kann bereits ein Werkzeug mit Nebenwirkung gestartet haben;
   automatische Neustarts sind deshalb standardmäßig aus. `--retries` ist eine ausdrückliche
   Option nur für Aufgaben, deren Start keine Nebenwirkungen haben kann. Jeder Versuch läuft
   in einer eigenen Prozessgruppe. Bei Ende oder Abbruch — Timeout, Strg-C, `SIGTERM`,
   `SIGHUP` oder ein bereits beendeter OpenCode-Elternprozess — entfernt der Wrapper übrige
   Nachfahren, bevor er die temporäre Konfiguration löscht.

Das Ganze ist eine Python-Datei, die man in einem Rutsch liest.

Die seltener benötigten Einstellungen haben eigene CLI-Schalter:

| Schalter | Standard | Wirkung |
| --- | --- | --- |
| `--timeout` | `300` | Sekunden Ausgabestille; `0` schaltet Timeout und Neustart aus. |
| `--retries` | `0` | Ausdrückliche Neustarts nach völlig stillem Lauf; nur für nebenwirkungsfreie Starts. |
| `--context` | `1000000` | Gegenüber OpenCode deklariertes Kontextfenster. |
| `--max-output` | `16384` | Gegenüber OpenCode deklariertes Ausgabe-Tokenlimit. |
| `--system-prompt` | mitgelieferte `system-prompt.md` | In den Lauf geladene Instruktionsdatei. |
| `--variant` | nicht gesetzt | Optionale OpenCode-Agentenvariante. |

</details>

<details>
<summary><b>Einen anderen Provider</b> oder eine andere Key-Quelle nutzen</summary>

<br>

**Andere Provider.** Außer den Defaults ist hier nichts MiniMax-spezifisch. `--base-url` auf
einen beliebigen Anthropic-kompatiblen Endpunkt zeigen und `--model` entsprechend setzen; die
genaue Modell-ID steht in der Doku des jeweiligen Providers.

**Key-Quellen.** Für den Standard-MiniMax-Endpunkt sucht das Tool in dieser Reihenfolge:
`--key-command` (ein Kommando, das binnen 30 Sekunden genau eine nicht leere Zeile ausgeben
muss), dann `$MINIMAX_API_KEY`, dann — auf macOS — den Eintrag `minimax-api-key` des aktuellen
Kontos. Ein ausdrücklich gesetztes Key-Kommando ist verbindlich: Fehler, Timeout oder mehrere
Ausgabezeilen brechen ab, statt auf ein anderes Credential zurückzufallen. Ein eigener
`--base-url` verlangt
`--key-command`; MiniMax-Umgebungsvariable und -Schlüsselbund-Fallback werden bewusst ignoriert,
damit ihr Credential nicht an einen anderen Provider gelangen kann. Dafür einen
providerspezifischen Eintrag oder Passwort-Manager-Befehl verwenden:
```bash
python3 ./minimax_agent.py --dir ./mein-projekt --sandbox \
  --key-command "security find-generic-password -a \"$USER\" -s mein-anderer-key -w" "..."
```

</details>

## Einordnung nach dem EU AI Act

Dieses Repository ist nach seinem Stand vom 2026-08-24 eine
Open-Source-Integrationskomponente und kein unter seinem Projektnamen angebotenes
vollständiges generatives KI-System. Es enthält weder ein Modell noch die
OpenCode-Laufzeit oder einen gehosteten Endpunkt. Nutzer installieren OpenCode
separat, wählen einen kompatiblen Modellanbieter, beschaffen eigene
Zugangsdaten und bleiben Kunden dieser Anbieter. Der Wrapper schreibt nur die
Konfiguration für diese Kombination, startet OpenCode und überwacht den lokalen
Prozess.

Diese Einordnung muss erneut geprüft werden, falls das Projekt später Laufzeit
und Modellzugang bündelt, einen gehosteten Dienst betreibt oder als vollständiges
KI-System unter einem eigenen Namen oder einer eigenen Marke angeboten wird.
Grundlagen sind die
[Leitlinien der EU-Kommission zu Artikel 50](https://digital-strategy.ec.europa.eu/en/policies/guidelines-ai-transparency-obligations)
und die [Anbieterdefinition des EU AI Act](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-3).

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
